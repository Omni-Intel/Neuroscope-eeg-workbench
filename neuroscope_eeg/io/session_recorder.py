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
    "eeg_session_sec",
    "eeg_sample_index",
    "paradigm",
    "phase",
    "label",
    "is_practice",
    "payload",
)


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
        self.participant_id = participant_id
        self.paradigm = paradigm
        self.preset = preset
        self.metadata = metadata
        self.source_sample_offset = int(source_sample_offset)
        self.sfreq = int(round(metadata.sfreq))
        self.channel_labels = _bdf_labels(metadata.channel_names)
        self.started_at = datetime.now(timezone.utc)
        self.ended_at: datetime | None = None
        self.error: str | None = None
        self._valid_samples = 0
        self._padded_samples = 0
        self._chunks_written = 0
        self._events_written = 0
        self._submitted_samples = 0
        self._queued_samples = 0
        self._max_queue_depth = 0
        self._queue_capacity_samples = max(self.sfreq * 10, self.sfreq)
        self._queue: Queue[np.ndarray | None] = Queue()
        self._lock = threading.Lock()
        self._events_lock = threading.Lock()
        self._accepting = True
        self._stopped = False

        self._write_session_json("initializing", "")
        self._events_handle = self.events_path.open("w", newline="", encoding="utf-8-sig")
        self._events_writer = csv.DictWriter(self._events_handle, fieldnames=_EVENT_FIELDS)
        self._events_writer.writeheader()
        self._events_handle.flush()

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
                    "dimension": unit,
                    "sample_frequency": self.sfreq,
                    "physical_min": -262144,
                    "physical_max": 262143,
                    "digital_min": -8388608,
                    "digital_max": 8388607,
                    "transducer": "",
                    "prefilter": "",
                }
                for label, unit in zip(self.channel_labels, metadata.channel_units)
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

    def record_event(
        self,
        event: StimulusEvent,
        *,
        eeg_sample_index: int,
        eeg_session_sec: float,
    ) -> None:
        row = event.as_dict()
        row.update(
            {
                "eeg_session_sec": float(eeg_session_sec),
                "eeg_sample_index": int(eeg_sample_index),
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

    def _write_record(self, values: np.ndarray, *, valid_samples: int) -> None:
        cleaned = np.asarray(values, dtype=np.float64)
        nonfinite = ~np.isfinite(cleaned)
        nonfinite_count = int(nonfinite.sum())
        if nonfinite_count:
            cleaned = cleaned.copy()
            cleaned[nonfinite] = 0.0
        clipped_count = int(((cleaned < -262144.0) | (cleaned > 262143.0)).sum())
        if clipped_count:
            cleaned = np.clip(cleaned, -262144.0, 262143.0)
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
            "timing_status": TIMING_STATUS,
            "neuroscope_version": _package_version(),
            "python_version": platform.python_version(),
            "error": self.error,
        }
        temporary = self.session_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.session_path)
