from __future__ import annotations

import csv
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
import json
import math
import os
from pathlib import Path
import platform
from queue import Queue
import re
import threading
from typing import Any

import numpy as np

from neuroscope_eeg.acquisition.td10_lsl import TD10Sidecars
from neuroscope_eeg.core.models import EEGChunk, SourceMetadata
from neuroscope_eeg.desktop.protocols import PROTOCOL_VERSION, TIMING_STATUS, StimulusEvent


_PARTICIPANT_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")
_PARADIGM_SLUGS = {
    "静息睁眼/闭眼": "rest",
    "2-back 工作记忆": "nback",
    "Stroop 色词冲突": "stroop",
    "听觉 ASSR": "assr",
    "听觉 Oddball": "oddball",
    "情绪图片唤醒": "emotion",
    "SSVEP": "ssvep",
    "运动想象": "motor_imagery",
    "视觉图像识别": "visual",
    "注意力": "attention",
}
_EVENT_FIELDS = (
    "monotonic_time",
    "wall_time",
    "lsl_time",
    "eeg_session_sec",
    "eeg_sample_index",
    "alignment_method",
    "alignment_error_ms",
    "alignment_status",
    "paradigm",
    "phase",
    "label",
    "is_practice",
    "payload",
)

_BDF_DIGITAL_MIN = -8_388_608
_BDF_DIGITAL_MAX = 8_388_607
_DEFAULT_PHYSICAL_MIN = -262_144.0
_DEFAULT_PHYSICAL_MAX = 262_143.0


def _is_adc_counts(unit: str) -> bool:
    return unit.strip().casefold() in {"adc count", "adc counts", "counts"}


def _bdf_dimension(unit: str) -> str:
    return "ADCcnt" if _is_adc_counts(unit) else unit


def _physical_limits(unit: str) -> tuple[float, float]:
    if _is_adc_counts(unit):
        return _BDF_DIGITAL_MIN, _BDF_DIGITAL_MAX
    return _DEFAULT_PHYSICAL_MIN, _DEFAULT_PHYSICAL_MAX


class RecordingError(RuntimeError):
    pass


def _package_version() -> str:
    try:
        return version("neuroscope-eeg-workbench")
    except PackageNotFoundError:
        return "unknown"


def _bdf_labels(channel_names: tuple[str, ...]) -> tuple[str, ...]:
    used: set[str] = set()
    labels: list[str] = []
    for index, original in enumerate(channel_names, start=1):
        base = str(original).strip() or f"CH{index}"
        candidate = base[:16]
        suffix_index = 2
        while candidate.casefold() in used:
            suffix = f"_{suffix_index}"
            candidate = f"{base[: 16 - len(suffix)]}{suffix}"
            suffix_index += 1
        used.add(candidate.casefold())
        labels.append(candidate)
    return tuple(labels)


class SessionRecorder:
    """Stream full-channel EEG and stimulus events into one paradigm session."""

    def __init__(
        self,
        *,
        session_dir: Path,
        participant_id: str,
        paradigm: str,
        preset: str,
        metadata: SourceMetadata,
        source_sample_offset: int,
        pyedflib_module: Any,
    ) -> None:
        self.session_dir = session_dir
        self.inprogress_path = session_dir / "eeg.inprogress.bdf"
        self.final_path = session_dir / "eeg.bdf"
        self.events_path = session_dir / "events.csv"
        self.session_path = session_dir / "session.json"
        self.lsl_timestamps_path = session_dir / "lsl_timestamps.f64"
        self.lsl_timestamps_corrected_path = session_dir / "lsl_timestamps_corrected.f64"
        self.quality_raw_path = session_dir / "quality_raw.i32"
        self.quality_timestamps_path = session_dir / "quality_timestamps.f64"
        self.quality_timestamps_corrected_path = session_dir / "quality_timestamps_corrected.f64"
        self.quality_aligned_path = session_dir / "quality_aligned.i32"
        self.ifet_markers_path = session_dir / "ifet_markers.jsonl"
        self.neuroscope_markers_path = session_dir / "neuroscope_markers.jsonl"
        self.clock_corrections_path = session_dir / "clock_corrections.jsonl"
        self.participant_id = participant_id
        self.paradigm = paradigm
        self.preset = preset
        self.metadata = metadata
        self.source_sample_offset = int(source_sample_offset)
        self.sfreq = int(round(metadata.sfreq))
        self.channel_labels = _bdf_labels(metadata.channel_names)
        self._physical_ranges = tuple(_physical_limits(unit) for unit in metadata.channel_units)
        self.started_at = datetime.now(timezone.utc)
        self.ended_at: datetime | None = None
        self.error: str | None = None
        self._valid_samples = 0
        self._padded_samples = 0
        self._chunks_written = 0
        self._events_written = 0
        self._event_rows: list[dict[str, Any]] = []
        self._eeg_timing_samples = 0
        self._quality_samples = 0
        self._quality_invalid_samples = 0
        self._ifet_markers_written = 0
        self._neuroscope_markers_written = 0
        self._clock_corrections_written = 0
        self._clock_correction_values: dict[str, list[float]] = {}
        self._timing_health: dict[str, Any] = {}
        self._submitted_samples = 0
        self._queued_samples = 0
        self._max_queue_depth = 0
        self._queue_capacity_samples = max(self.sfreq * 10, self.sfreq)
        self._queue: Queue[np.ndarray | TD10Sidecars | None] = Queue()
        self._lock = threading.Lock()
        self._events_lock = threading.Lock()
        self._accepting = True
        self._stopped = False

        self._write_session_json("initializing", "")
        self._events_handle = self.events_path.open("w", newline="", encoding="utf-8-sig")
        self._events_writer = csv.DictWriter(self._events_handle, fieldnames=_EVENT_FIELDS)
        self._events_writer.writeheader()
        self._events_handle.flush()
        self._sidecar_handles: dict[str, Any] = {}
        if metadata.source_type == "td10_lsl":
            self._sidecar_handles = {
                "eeg_raw": self.lsl_timestamps_path.open("wb"),
                "eeg_corrected": self.lsl_timestamps_corrected_path.open("wb"),
                "quality_raw": self.quality_raw_path.open("wb"),
                "quality_ts": self.quality_timestamps_path.open("wb"),
                "quality_corrected": self.quality_timestamps_corrected_path.open("wb"),
                "ifet_markers": self.ifet_markers_path.open("w", encoding="utf-8"),
                "neuroscope_markers": self.neuroscope_markers_path.open("w", encoding="utf-8"),
                "clock_corrections": self.clock_corrections_path.open("w", encoding="utf-8"),
            }

        self._writer = pyedflib_module.EdfWriter(
            str(self.inprogress_path),
            metadata.n_channels,
            file_type=pyedflib_module.FILETYPE_BDFPLUS,
        )
        self._writer.setPatientCode(participant_id)
        self._writer.setEquipment(metadata.source_type)
        self._writer.setStartdatetime(self.started_at.replace(tzinfo=None))
        self._writer.setSignalHeaders(
            [
                {
                    "label": label,
                    "dimension": _bdf_dimension(unit),
                    "sample_frequency": self.sfreq,
                    "physical_min": physical_min,
                    "physical_max": physical_max,
                    "digital_min": _BDF_DIGITAL_MIN,
                    "digital_max": _BDF_DIGITAL_MAX,
                    "transducer": "",
                    "prefilter": "",
                }
                for label, unit, (physical_min, physical_max) in zip(
                    self.channel_labels,
                    metadata.channel_units,
                    self._physical_ranges,
                )
            ]
        )
        self._write_session_json("recording", "")
        self._thread = threading.Thread(target=self._write_loop, name="neuroscope-bdf-writer", daemon=True)
        self._thread.start()

    @classmethod
    def start(
        cls,
        *,
        root_dir: Path | str,
        participant_id: str,
        paradigm: str,
        preset: str,
        metadata: SourceMetadata,
        source_sample_offset: int = 0,
    ) -> "SessionRecorder":
        participant = participant_id.strip()
        if not participant or _PARTICIPANT_PATTERN.fullmatch(participant) is None:
            raise ValueError("受试者编号只能包含字母、数字、短横线和下划线")
        if not str(root_dir).strip():
            raise ValueError("请选择脑电记录目录")
        rounded_sfreq = round(metadata.sfreq)
        if not math.isclose(metadata.sfreq, rounded_sfreq, rel_tol=0.0, abs_tol=1e-9):
            raise ValueError(f"BDF 自动记录要求整数采样率，当前为 {metadata.sfreq:g} Hz")
        try:
            import pyedflib
        except ImportError as exc:
            raise RecordingError(
                "完整采集需要 PyEDFlib，请执行：python -m pip install 'pyedflib>=0.1.40,<0.2'"
            ) from exc

        root = Path(root_dir).expanduser().resolve()
        participant_dir = root / participant
        participant_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        slug = _PARADIGM_SLUGS.get(paradigm, "paradigm")
        base_name = f"{timestamp}_{slug}_full"
        session_dir = participant_dir / base_name
        suffix = 2
        while session_dir.exists():
            session_dir = participant_dir / f"{base_name}_{suffix}"
            suffix += 1
        session_dir.mkdir()
        try:
            return cls(
                session_dir=session_dir,
                participant_id=participant,
                paradigm=paradigm,
                preset=preset,
                metadata=metadata,
                source_sample_offset=source_sample_offset,
                pyedflib_module=pyedflib,
            )
        except Exception as exc:
            error_path = session_dir / "session.json"
            error_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "participant_id": participant,
                        "paradigm": paradigm,
                        "preset": preset,
                        "status": "error",
                        "stop_reason": "initialization_failed",
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            raise RecordingError(f"无法初始化脑电记录：{exc}") from exc

    @property
    def submitted_samples(self) -> int:
        with self._lock:
            return self._submitted_samples

    def submit(self, chunk: EEGChunk) -> None:
        if chunk.metadata != self.metadata:
            raise RecordingError("记录期间数据源通道或采样率发生变化")
        if chunk.n_samples == 0:
            return
        values = np.asarray(chunk.data, dtype=np.float64).copy(order="C")
        with self._lock:
            if self.error:
                raise RecordingError(self.error)
            if not self._accepting:
                raise RecordingError("记录器已停止接收数据")
            if self._queued_samples + chunk.n_samples > self._queue_capacity_samples:
                self.error = "脑电写盘队列超过 10 秒容量"
                self._accepting = False
                raise RecordingError(self.error)
            self._queued_samples += chunk.n_samples
            self._submitted_samples += chunk.n_samples
            self._max_queue_depth = max(self._max_queue_depth, self._queued_samples)
        self._queue.put_nowait(values)

    def submit_sidecars(self, sidecars: TD10Sidecars) -> None:
        if not isinstance(sidecars, TD10Sidecars) or sidecars.is_empty:
            return
        with self._lock:
            if self.error:
                raise RecordingError(self.error)
            if not self._accepting:
                raise RecordingError("记录器已停止接收数据")
        self._queue.put_nowait(sidecars)

    def record_event(
        self,
        event: StimulusEvent,
        *,
        eeg_sample_index: int,
        eeg_session_sec: float,
        lsl_time: float | None = None,
    ) -> None:
        row = event.as_dict()
        row.update(
            {
                "eeg_session_sec": float(eeg_session_sec),
                "eeg_sample_index": int(eeg_sample_index),
                "lsl_time": "" if lsl_time is None else float(lsl_time),
                "alignment_method": "pending" if lsl_time is not None else "sample_counter",
                "alignment_error_ms": "",
                "alignment_status": "pending" if lsl_time is not None else "legacy",
                "is_practice": bool(event.payload.get("is_practice", False)),
                "payload": json.dumps(row["payload"], ensure_ascii=False, separators=(",", ":")),
            }
        )
        with self._events_lock:
            if self._events_handle.closed:
                raise RecordingError("事件文件已经关闭")
            try:
                self._events_writer.writerow(row)
                self._events_handle.flush()
            except Exception as exc:
                self._set_error(f"写入事件失败：{exc}")
                raise RecordingError(self.error or str(exc)) from exc
            self._events_written += 1
            self._event_rows.append(dict(row))

    def stop(self, *, status: str, reason: str) -> None:
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            self._accepting = False
        self._queue.put(None)
        self._thread.join(timeout=15.0)
        if self._thread.is_alive():
            self._set_error("脑电写盘线程未能在 15 秒内停止")
        try:
            self._writer.close()
        except Exception as exc:
            self._set_error(f"关闭 BDF 失败：{exc}")
        with self._events_lock:
            try:
                self._events_handle.flush()
                self._events_handle.close()
            except Exception as exc:
                self._set_error(f"关闭事件文件失败：{exc}")
        self._close_sidecars()
        if not self.error and self.metadata.source_type == "td10_lsl" and self._submitted_samples:
            try:
                self._finalize_td10_sidecars()
                self._realign_events()
            except Exception as exc:
                self._set_error(f"完成 TD10 时间轴失败：{exc}")
        self.ended_at = datetime.now(timezone.utc)
        final_status = "error" if self.error else status
        final_reason = "recording_error" if self.error else reason
        if not self.error:
            try:
                os.replace(self.inprogress_path, self.final_path)
            except Exception as exc:
                self._set_error(f"完成 BDF 文件失败：{exc}")
                final_status = "error"
                final_reason = "recording_error"
        self._write_session_json(final_status, final_reason)

    def _write_loop(self) -> None:
        pending = np.empty((self.metadata.n_channels, 0), dtype=np.float64)
        try:
            while True:
                item = self._queue.get()
                if item is None:
                    break
                if isinstance(item, TD10Sidecars):
                    self._write_sidecars(item)
                    continue
                with self._lock:
                    self._queued_samples -= item.shape[1]
                    self._chunks_written += 1
                pending = np.concatenate((pending, item), axis=1)
                while pending.shape[1] >= self.sfreq:
                    self._write_record(pending[:, : self.sfreq], valid_samples=self.sfreq)
                    pending = pending[:, self.sfreq :]
            if pending.shape[1] and not self.error:
                valid = pending.shape[1]
                padded = np.zeros((self.metadata.n_channels, self.sfreq), dtype=np.float64)
                padded[:, :valid] = pending
                self._write_record(padded, valid_samples=valid)
                self._padded_samples = self.sfreq - valid
        except Exception as exc:
            self._set_error(f"写入 BDF 失败：{exc}")

    def _write_sidecars(self, sidecars: TD10Sidecars) -> None:
        if not self._sidecar_handles:
            return
        for batch in sidecars.eeg_timing:
            np.asarray(batch.raw_timestamps, dtype="<f8").tofile(self._sidecar_handles["eeg_raw"])
            np.asarray(batch.corrected_timestamps, dtype="<f8").tofile(
                self._sidecar_handles["eeg_corrected"]
            )
            self._eeg_timing_samples += len(batch.raw_timestamps)
        for batch in sidecars.quality:
            values = np.asarray(batch.values, dtype="<i4")
            values.tofile(self._sidecar_handles["quality_raw"])
            np.asarray(batch.raw_timestamps, dtype="<f8").tofile(self._sidecar_handles["quality_ts"])
            np.asarray(batch.corrected_timestamps, dtype="<f8").tofile(
                self._sidecar_handles["quality_corrected"]
            )
            self._quality_samples += len(values)
            self._quality_invalid_samples += int(np.count_nonzero(values[:, 0] == 0))
        for marker in sidecars.ifet_markers:
            self._write_jsonl(
                "ifet_markers",
                {
                    "value": marker.value,
                    "raw_timestamp": marker.raw_timestamp,
                    "corrected_timestamp": marker.corrected_timestamp,
                    "time_correction": marker.time_correction,
                },
            )
            self._ifet_markers_written += 1
        for marker in sidecars.neuroscope_markers:
            self._write_jsonl(
                "neuroscope_markers",
                {"payload": marker.payload, "lsl_timestamp": marker.lsl_timestamp},
            )
            self._neuroscope_markers_written += 1
        for correction in sidecars.clock_corrections:
            self._write_jsonl(
                "clock_corrections",
                {
                    "stream": correction.stream,
                    "measured_at": correction.measured_at,
                    "correction_sec": correction.correction_sec,
                },
            )
            self._clock_corrections_written += 1
            self._clock_correction_values.setdefault(correction.stream, []).append(
                correction.correction_sec
            )

    def _write_jsonl(self, handle_name: str, payload: dict[str, Any]) -> None:
        self._sidecar_handles[handle_name].write(
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n"
        )

    def _close_sidecars(self) -> None:
        for handle in self._sidecar_handles.values():
            try:
                handle.flush()
                handle.close()
            except Exception as exc:
                self._set_error(f"关闭 TD10 sidecar 失败：{exc}")

    def _finalize_td10_sidecars(self) -> None:
        if self._eeg_timing_samples != self._submitted_samples:
            raise RecordingError(
                f"EEG 时间戳数 {self._eeg_timing_samples} 与 EEG 样本数 {self._submitted_samples} 不一致"
            )
        eeg_timestamps = np.fromfile(self.lsl_timestamps_corrected_path, dtype="<f8")
        if len(eeg_timestamps) != self._submitted_samples:
            raise RecordingError("EEG 校正时间轴文件长度无效")
        self._require_strictly_increasing(eeg_timestamps, "EEG")
        eeg_intervals = np.diff(eeg_timestamps)
        self._timing_health.update(
            {
                "eeg_effective_sfreq": (
                    None
                    if len(eeg_timestamps) < 2
                    else (len(eeg_timestamps) - 1) / (eeg_timestamps[-1] - eeg_timestamps[0])
                ),
                "eeg_max_interval_sec": (
                    None if not len(eeg_intervals) else float(np.max(eeg_intervals))
                ),
                "eeg_gap_count": int(np.count_nonzero(eeg_intervals > 1.5 / self.sfreq)),
            }
        )
        quality_values = np.fromfile(self.quality_raw_path, dtype="<i4")
        quality_timestamps = np.fromfile(self.quality_timestamps_corrected_path, dtype="<f8")
        if quality_values.size != quality_timestamps.size * 3:
            raise RecordingError("Quality 数值与时间戳数量不一致")
        quality_values = quality_values.reshape(-1, 3)
        if len(quality_timestamps):
            self._require_strictly_increasing(quality_timestamps, "Quality")
        aligned = np.tile(np.asarray([0, -1, -1], dtype="<i4"), (len(eeg_timestamps), 1))
        if len(quality_timestamps):
            nearest, errors = self._nearest_indices(eeg_timestamps, quality_timestamps)
            matched = errors <= 0.5 / self.sfreq
            aligned[matched] = quality_values[nearest[matched]]
        else:
            matched = np.zeros(len(eeg_timestamps), dtype=bool)
        wraps, duplicates, gaps = self._device_sequence_health(quality_values[:, 1])
        self._timing_health.update(
            {
                "quality_valid_ratio": (
                    None
                    if not len(quality_values)
                    else float(np.count_nonzero(quality_values[:, 0])) / len(quality_values)
                ),
                "quality_aligned_samples": int(np.count_nonzero(matched)),
                "quality_unmatched_samples": int(len(matched) - np.count_nonzero(matched)),
                "device_seq_wraps": wraps,
                "device_seq_duplicates": duplicates,
                "device_seq_gaps": gaps,
                "clock_correction_ranges_sec": {
                    stream: {
                        "min": min(values),
                        "max": max(values),
                        "latest": values[-1],
                    }
                    for stream, values in self._clock_correction_values.items()
                },
            }
        )
        temporary = self.quality_aligned_path.with_suffix(".i32.tmp")
        aligned.tofile(temporary)
        os.replace(temporary, self.quality_aligned_path)

    def _realign_events(self) -> None:
        if not self._event_rows:
            return
        eeg_timestamps = np.fromfile(self.lsl_timestamps_corrected_path, dtype="<f8")
        tolerance = 0.5 / self.sfreq
        for row in self._event_rows:
            if row["lsl_time"] == "":
                continue
            target = float(row["lsl_time"])
            nearest, errors = self._nearest_indices(np.asarray([target]), eeg_timestamps)
            error = float(errors[0])
            row["alignment_error_ms"] = error * 1000.0
            if error <= tolerance:
                index = int(nearest[0])
                row["eeg_sample_index"] = index
                row["eeg_session_sec"] = float(eeg_timestamps[index] - eeg_timestamps[0])
                row["alignment_method"] = "nearest_lsl_timestamp"
                row["alignment_status"] = "aligned"
            else:
                row["eeg_sample_index"] = -1
                row["eeg_session_sec"] = ""
                row["alignment_method"] = "nearest_lsl_timestamp"
                row["alignment_status"] = "outside_tolerance"
        temporary = self.events_path.with_suffix(".csv.tmp")
        with temporary.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=_EVENT_FIELDS)
            writer.writeheader()
            writer.writerows(self._event_rows)
        os.replace(temporary, self.events_path)

    @staticmethod
    def _nearest_indices(targets: np.ndarray, reference: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        if reference.size == 0:
            raise RecordingError("权威 LSL 时间轴为空")
        right = np.searchsorted(reference, targets, side="left")
        right = np.clip(right, 0, len(reference) - 1)
        left = np.clip(right - 1, 0, len(reference) - 1)
        choose_left = np.abs(targets - reference[left]) <= np.abs(reference[right] - targets)
        nearest = np.where(choose_left, left, right)
        return nearest, np.abs(reference[nearest] - targets)

    @staticmethod
    def _require_strictly_increasing(values: np.ndarray, label: str) -> None:
        if not np.all(np.isfinite(values)) or np.any(np.diff(values) <= 0):
            raise RecordingError(f"{label} 校正时间轴必须有限且严格递增")

    @staticmethod
    def _device_sequence_health(values: np.ndarray) -> tuple[int, int, int]:
        wraps = duplicates = gaps = 0
        if len(values) < 2:
            return wraps, duplicates, gaps
        previous: int | None = None
        for value in values:
            current = int(value)
            if current == -1:
                previous = None
                continue
            if previous is None:
                previous = current
                continue
            delta = (current - previous) & 0xFF
            if previous == 255 and current == 0:
                wraps += 1
            elif delta == 0:
                duplicates += 1
            elif delta > 1:
                gaps += delta - 1
            previous = current
        return wraps, duplicates, gaps

    def _write_record(self, values: np.ndarray, *, valid_samples: int) -> None:
        cleaned = np.asarray(values, dtype=np.float64)
        nonfinite = ~np.isfinite(cleaned)
        nonfinite_count = int(nonfinite.sum())
        if nonfinite_count:
            cleaned = cleaned.copy()
            cleaned[nonfinite] = 0.0
        physical_min = np.asarray([limits[0] for limits in self._physical_ranges], dtype=np.float64)[:, None]
        physical_max = np.asarray([limits[1] for limits in self._physical_ranges], dtype=np.float64)[:, None]
        clipped_count = int(((cleaned < physical_min) | (cleaned > physical_max)).sum())
        if clipped_count:
            cleaned = np.minimum(np.maximum(cleaned, physical_min), physical_max)
        self._writer.writeSamples([np.ascontiguousarray(channel) for channel in cleaned])
        with self._lock:
            self._valid_samples += int(valid_samples)
            self._nonfinite_samples = getattr(self, "_nonfinite_samples", 0) + nonfinite_count
            self._clipped_samples = getattr(self, "_clipped_samples", 0) + clipped_count

    def _set_error(self, message: str) -> None:
        with self._lock:
            if not self.error:
                self.error = message
            self._accepting = False

    def _write_session_json(self, status: str, stop_reason: str) -> None:
        payload = {
            "schema_version": 1,
            "participant_id": self.participant_id,
            "paradigm": self.paradigm,
            "preset": self.preset,
            "protocol_version": PROTOCOL_VERSION,
            "source_id": self.metadata.source_id,
            "source_type": self.metadata.source_type,
            "sfreq": self.metadata.sfreq,
            "channel_names": list(self.metadata.channel_names),
            "bdf_channel_labels": list(self.channel_labels),
            "channel_types": list(self.metadata.channel_types),
            "channel_units": list(self.metadata.channel_units),
            "source_extra": dict(self.metadata.extra),
            "source_sample_offset": self.source_sample_offset,
            "started_at": self.started_at.isoformat(),
            "ended_at": self.ended_at.isoformat() if self.ended_at else None,
            "status": status,
            "stop_reason": stop_reason,
            "valid_samples": self._valid_samples,
            "padded_samples": self._padded_samples,
            "chunks_written": self._chunks_written,
            "events_written": self._events_written,
            "nonfinite_samples": getattr(self, "_nonfinite_samples", 0),
            "clipped_samples": getattr(self, "_clipped_samples", 0),
            "max_queue_depth": self._max_queue_depth,
            "timing_status": (
                "lsl_software_sync_uncalibrated"
                if self.metadata.source_type == "td10_lsl"
                else TIMING_STATUS
            ),
            "eeg_timing_samples": self._eeg_timing_samples,
            "quality_samples": self._quality_samples,
            "quality_invalid_samples": self._quality_invalid_samples,
            "ifet_markers_written": self._ifet_markers_written,
            "neuroscope_markers_written": self._neuroscope_markers_written,
            "clock_corrections_written": self._clock_corrections_written,
            "timing_health": self._timing_health,
            "neuroscope_version": _package_version(),
            "python_version": platform.python_version(),
            "error": self.error,
        }
        temporary = self.session_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.session_path)
