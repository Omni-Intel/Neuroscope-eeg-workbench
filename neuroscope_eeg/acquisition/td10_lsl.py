"""TD10 headband EEG acquisition through the Lab Streaming Layer."""

from __future__ import annotations

import importlib
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import numpy as np

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata


TD10_CHANNEL_NAMES = ("EEG1", "EEG2", "EEG3", "EEG4")
TD10_SAMPLE_RATES = (125, 250, 500, 1000)
TD10_ADC_MIN = -8_388_608
TD10_ADC_MAX = 8_388_607
DEFAULT_TD10_BASE_SOURCE_ID = "ifet-td10-headset"
TD10_QUALITY_CHANNEL_NAMES = ("Valid", "DeviceSeq", "DeviceFlag")


@dataclass(frozen=True, slots=True)
class EEGTimingBatch:
    sequence: int
    raw_timestamps: np.ndarray
    corrected_timestamps: np.ndarray
    time_correction: float


@dataclass(frozen=True, slots=True)
class QualityBatch:
    values: np.ndarray
    raw_timestamps: np.ndarray
    corrected_timestamps: np.ndarray
    time_correction: float


@dataclass(frozen=True, slots=True)
class LSLMarker:
    value: str
    raw_timestamp: float
    corrected_timestamp: float
    time_correction: float


@dataclass(frozen=True, slots=True)
class ClockCorrectionSample:
    stream: str
    measured_at: str
    correction_sec: float


@dataclass(frozen=True, slots=True)
class NeuroScopeMarker:
    payload: str
    lsl_timestamp: float


@dataclass(frozen=True, slots=True)
class TD10Sidecars:
    eeg_timing: tuple[EEGTimingBatch, ...] = ()
    quality: tuple[QualityBatch, ...] = ()
    ifet_markers: tuple[LSLMarker, ...] = ()
    neuroscope_markers: tuple[NeuroScopeMarker, ...] = ()
    clock_corrections: tuple[ClockCorrectionSample, ...] = ()

    @property
    def is_empty(self) -> bool:
        return not (
            self.eeg_timing
            or self.quality
            or self.ifet_markers
            or self.neuroscope_markers
            or self.clock_corrections
        )


@dataclass(frozen=True, slots=True)
class TD10LSLDevice:
    source_id: str
    stream_name: str
    sfreq: float

    @property
    def base_source_id(self) -> str:
        return self.source_id[:-4] if self.source_id.casefold().endswith(":eeg") else self.source_id


def eeg_source_id(base_source_id: str) -> str:
    """Return the protocol-defined EEG source ID from a base or full ID."""

    value = base_source_id.strip() or DEFAULT_TD10_BASE_SOURCE_ID
    return value if value.casefold().endswith(":eeg") else f"{value}:eeg"


def _base_source_id(value: str) -> str:
    stripped = value.strip() or DEFAULT_TD10_BASE_SOURCE_ID
    for suffix in (":eeg", ":quality", ":markers"):
        if stripped.casefold().endswith(suffix):
            return stripped[: -len(suffix)]
    return stripped


def _load_pylsl() -> Any:
    try:
        return importlib.import_module("pylsl")
    except (ImportError, RuntimeError, OSError) as exc:
        raise RuntimeError(
            "TD10 LSL 采集需要 pylsl==1.18.2 及可加载的 liblsl。"
            "请执行：python -m pip install -r requirements-desktop.txt"
        ) from exc


def discover_td10_devices(timeout_sec: float = 2.0) -> tuple[TD10LSLDevice, ...]:
    """Find protocol-compatible TD10 EEG outlets currently visible on the LAN."""

    if timeout_sec <= 0:
        raise ValueError("LSL discovery timeout must be positive")
    pylsl = _load_pylsl()
    expected_format = getattr(pylsl, "cf_int32", None)
    found: dict[str, TD10LSLDevice] = {}
    for info in pylsl.resolve_streams(wait_time=float(timeout_sec)):
        try:
            source_id = str(info.source_id()).strip()
            stream_type = str(info.type()).casefold()
            channel_count = int(info.channel_count())
            sfreq = float(info.nominal_srate())
            channel_format = info.channel_format()
            format_text = str(channel_format).casefold()
        except Exception:
            continue
        rounded_sfreq = int(round(sfreq))
        valid_format = channel_format == expected_format or format_text in {"int32", "cf_int32"}
        if (
            not source_id.casefold().endswith(":eeg")
            or stream_type != "eeg"
            or channel_count != len(TD10_CHANNEL_NAMES)
            or not math.isclose(sfreq, rounded_sfreq, rel_tol=0.0, abs_tol=1e-6)
            or rounded_sfreq not in TD10_SAMPLE_RATES
            or not valid_format
        ):
            continue
        found[source_id] = TD10LSLDevice(source_id, str(info.name()), float(rounded_sfreq))
    return tuple(found[key] for key in sorted(found, key=str.casefold))


class TD10LSLSource:
    """Receive the protocol's four-channel raw EEG stream as native EEG chunks."""

    def __init__(
        self,
        base_source_id: str = DEFAULT_TD10_BASE_SOURCE_ID,
        *,
        resolve_timeout_sec: float = 5.0,
        pull_timeout_sec: float = 0.2,
        max_chunk_samples: int = 1024,
        fallback_sfreq: float = 250.0,
    ) -> None:
        if resolve_timeout_sec <= 0:
            raise ValueError("LSL resolve timeout must be positive")
        if pull_timeout_sec < 0:
            raise ValueError("LSL pull timeout must be non-negative")
        if max_chunk_samples <= 0:
            raise ValueError("LSL max chunk samples must be positive")
        if int(fallback_sfreq) not in TD10_SAMPLE_RATES:
            raise ValueError(f"TD10 fallback sample rate must be one of {TD10_SAMPLE_RATES}")

        self.requested_source_id = eeg_source_id(base_source_id)
        self.base_source_id = _base_source_id(base_source_id)
        self.quality_source_id = f"{self.base_source_id}:quality"
        self.markers_source_id = f"{self.base_source_id}:markers"
        self.resolve_timeout_sec = float(resolve_timeout_sec)
        self.pull_timeout_sec = float(pull_timeout_sec)
        self.max_chunk_samples = int(max_chunk_samples)
        self.metadata = self._metadata(float(fallback_sfreq), stream_name="")
        self._pylsl: Any = None
        self._inlet: Any = None
        self._quality_inlet: Any = None
        self._markers_inlet: Any = None
        self._sample_index = 0
        self._eeg_timing: list[EEGTimingBatch] = []
        self._quality: list[QualityBatch] = []
        self._ifet_markers: list[LSLMarker] = []
        self._neuroscope_markers: list[NeuroScopeMarker] = []
        self._clock_corrections: list[ClockCorrectionSample] = []
        self._marker_outlet: Any = None
        self._last_device_seq: int | None = None
        self._timing_stats: dict[str, int | float | None] = {
            "eeg_samples": 0,
            "quality_samples": 0,
            "quality_invalid_samples": 0,
            "device_seq_wraps": 0,
            "device_seq_duplicates": 0,
            "device_seq_gaps": 0,
            "eeg_gap_count": 0,
            "eeg_nonmonotonic_count": 0,
            "eeg_max_interval_sec": 0.0,
        }
        self._correction_cache: dict[str, tuple[float, float]] = {}
        self._first_eeg_timestamp: float | None = None
        self._last_eeg_timestamp: float | None = None

    def _metadata(self, sfreq: float, *, stream_name: str) -> SourceMetadata:
        return SourceMetadata(
            source_id=self.requested_source_id,
            source_type="td10_lsl",
            sfreq=sfreq,
            channel_names=TD10_CHANNEL_NAMES,
            channel_types=tuple("eeg" for _ in TD10_CHANNEL_NAMES),
            channel_units=tuple("ADC counts" for _ in TD10_CHANNEL_NAMES),
            extra={
                "lsl_stream_name": stream_name,
                "lsl_source_id": self.requested_source_id,
                "lsl_quality_source_id": self.quality_source_id,
                "lsl_markers_source_id": self.markers_source_id,
                "lsl_timestamp_clock": "LSL local_clock",
                "timing_status": "lsl_software_sync_uncalibrated",
                "timestamp_semantics": "outlet chunk timestamps corrected to inlet clock",
                "raw_value_semantics": "signed 24-bit ADC counts",
                "voltage_conversion": "not configured",
            },
        )

    def start(self) -> None:
        self.stop()
        self._pylsl = _load_pylsl()
        streams = self._pylsl.resolve_byprop(
            "source_id",
            self.requested_source_id,
            minimum=1,
            timeout=self.resolve_timeout_sec,
        )
        if not streams:
            self._pylsl = None
            raise RuntimeError(
                f"未发现 TD10 LSL EEG 流：{self.requested_source_id}。"
                "请确认 iFET 上位机已开启 LSL，且设备与本机位于同一局域网。"
            )
        if len(streams) > 1:
            self._pylsl = None
            raise RuntimeError(
                f"发现多个相同 source_id 的 TD10 LSL 流：{self.requested_source_id}。"
                "请为每台上位机设置唯一来源 ID。"
            )

        info = streams[0]
        inlet = None
        quality_inlet = None
        markers_inlet = None
        try:
            sfreq = self._validate_stream(info)
            inlet = self._pylsl.StreamInlet(
                info,
                max_buflen=60,
                max_chunklen=0,
                recover=True,
                processing_flags=0,
            )
            inlet.open_stream(timeout=self.resolve_timeout_sec)
            quality_inlet = self._open_companion(
                self.quality_source_id,
                stream_type="Quality",
                channels=3,
                sfreq=sfreq,
                channel_format=getattr(self._pylsl, "cf_int32", None),
            )
            markers_inlet = self._open_companion(
                self.markers_source_id,
                stream_type="Markers",
                channels=1,
                sfreq=0.0,
                channel_format=getattr(self._pylsl, "cf_string", None),
            )
        except Exception:
            for opened_inlet in (inlet, quality_inlet, markers_inlet):
                if opened_inlet is not None:
                    try:
                        opened_inlet.close_stream()
                    except Exception:
                        pass
            self._pylsl = None
            raise

        self._inlet = inlet
        self._quality_inlet = quality_inlet
        self._markers_inlet = markers_inlet
        self.metadata = self._metadata(sfreq, stream_name=str(info.name()))
        self._sample_index = 0
        self._last_device_seq = None
        self._first_eeg_timestamp = None
        self._last_eeg_timestamp = None
        self._correction_cache.clear()
        for key in self._timing_stats:
            self._timing_stats[key] = 0

    def stop(self) -> None:
        inlets = (self._inlet, self._quality_inlet, self._markers_inlet)
        self._inlet = None
        self._quality_inlet = None
        self._markers_inlet = None
        self.stop_marker_outlet()
        self._pylsl = None
        for inlet in inlets:
            if inlet is None:
                continue
            try:
                inlet.close_stream()
            except Exception:
                pass

    @property
    def companions_ready(self) -> bool:
        return self._quality_inlet is not None and self._markers_inlet is not None

    @property
    def missing_companion_streams(self) -> tuple[str, ...]:
        missing = []
        if self._quality_inlet is None:
            missing.append("quality")
        if self._markers_inlet is None:
            missing.append("markers")
        return tuple(missing)

    @property
    def timing_stats(self) -> dict[str, int | float | None]:
        result = dict(self._timing_stats)
        total = int(result["quality_samples"] or 0)
        invalid = int(result["quality_invalid_samples"] or 0)
        result["quality_valid_ratio"] = None if total == 0 else (total - invalid) / total
        eeg_samples = int(result["eeg_samples"] or 0)
        if (
            eeg_samples > 1
            and self._first_eeg_timestamp is not None
            and self._last_eeg_timestamp is not None
            and self._last_eeg_timestamp > self._first_eeg_timestamp
        ):
            result["eeg_effective_sfreq"] = (eeg_samples - 1) / (
                self._last_eeg_timestamp - self._first_eeg_timestamp
            )
        else:
            result["eeg_effective_sfreq"] = None
        result["missing_companion_streams"] = self.missing_companion_streams
        result["timing_status"] = "lsl_software_sync_uncalibrated"
        return result

    def drain_sidecars(self) -> TD10Sidecars:
        drained = TD10Sidecars(
            eeg_timing=tuple(self._eeg_timing),
            quality=tuple(self._quality),
            ifet_markers=tuple(self._ifet_markers),
            neuroscope_markers=tuple(self._neuroscope_markers),
            clock_corrections=tuple(self._clock_corrections),
        )
        self._eeg_timing.clear()
        self._quality.clear()
        self._ifet_markers.clear()
        self._neuroscope_markers.clear()
        self._clock_corrections.clear()
        return drained

    def read_chunk(self) -> EEGChunk:
        if self._inlet is None:
            raise RuntimeError("TD10 LSL stream is not started")

        samples, timestamps = self._inlet.pull_chunk(
            timeout=self.pull_timeout_sec,
            max_samples=self.max_chunk_samples,
        )
        if len(samples) == 0:
            self._pull_companions()
            return EEGChunk(
                metadata=self.metadata,
                data=np.empty((len(TD10_CHANNEL_NAMES), 0), dtype=np.float32),
                timestamps=np.empty((0,), dtype=np.float64),
                sequence=self._sample_index,
            )

        sample_major = np.asarray(samples)
        if sample_major.ndim != 2 or sample_major.shape[1] != len(TD10_CHANNEL_NAMES):
            raise RuntimeError(
                "TD10 LSL EEG 数据必须为 (samples, 4)，"
                f"实际收到 {sample_major.shape}"
            )
        if not np.issubdtype(sample_major.dtype, np.number):
            raise RuntimeError(f"TD10 LSL EEG 数据不是数值类型：{sample_major.dtype}")
        if np.any(sample_major < TD10_ADC_MIN) or np.any(sample_major > TD10_ADC_MAX):
            raise RuntimeError("TD10 LSL EEG 数据超出有符号 24 位 ADC 范围")

        lsl_timestamps = np.asarray(timestamps, dtype=np.float64)
        if lsl_timestamps.shape != (sample_major.shape[0],):
            raise RuntimeError(
                "TD10 LSL 时间戳数量与样本数不一致："
                f"{lsl_timestamps.shape} vs {sample_major.shape[0]}"
            )
        if not np.all(np.isfinite(lsl_timestamps)):
            raise RuntimeError("TD10 LSL 时间戳包含非有限值")

        correction = self._time_correction(self._inlet, "eeg")
        corrected_timestamps = lsl_timestamps + correction
        self._update_eeg_timing_stats(corrected_timestamps)
        sequence = self._sample_index
        self._sample_index += sample_major.shape[0]
        self._timing_stats["eeg_samples"] = int(self._timing_stats["eeg_samples"] or 0) + sample_major.shape[0]
        self._eeg_timing.append(
            EEGTimingBatch(sequence, lsl_timestamps.copy(), corrected_timestamps.copy(), correction)
        )
        self._pull_companions()
        return EEGChunk(
            metadata=self.metadata,
            data=np.asarray(sample_major.T, dtype=np.float32),
            timestamps=corrected_timestamps,
            sequence=sequence,
        )

    def _open_companion(
        self,
        source_id: str,
        *,
        stream_type: str,
        channels: int,
        sfreq: float,
        channel_format: Any,
    ) -> Any | None:
        streams = self._pylsl.resolve_byprop(
            "source_id", source_id, minimum=1, timeout=self.resolve_timeout_sec
        )
        if not streams:
            return None
        if len(streams) > 1:
            raise RuntimeError(f"发现多个相同 source_id 的 TD10 LSL 流：{source_id}")
        info = streams[0]
        actual_type = str(info.type())
        if actual_type.casefold() != stream_type.casefold():
            raise RuntimeError(f"TD10 LSL {source_id} type 必须为 {stream_type}，实际为 {actual_type!r}")
        if str(info.source_id()) != source_id:
            raise RuntimeError(f"TD10 LSL source_id 不匹配：期望 {source_id!r}")
        if int(info.channel_count()) != channels:
            raise RuntimeError(f"TD10 LSL {stream_type} 必须为 {channels} 通道")
        actual_sfreq = float(info.nominal_srate())
        if not math.isclose(actual_sfreq, sfreq, rel_tol=0.0, abs_tol=1e-6):
            raise RuntimeError(
                f"TD10 LSL {stream_type} 标称采样率必须为 {sfreq:g} Hz，实际为 {actual_sfreq:g} Hz"
            )
        actual_format = info.channel_format()
        format_text = str(actual_format).casefold()
        expected_text = "string" if stream_type == "Markers" else "int32"
        if actual_format != channel_format and format_text not in {expected_text, f"cf_{expected_text}"}:
            raise RuntimeError(
                f"TD10 LSL {stream_type} 通道格式必须为 {expected_text}，实际为 {actual_format!r}"
            )
        inlet = self._pylsl.StreamInlet(
            info, max_buflen=60, max_chunklen=0, recover=True, processing_flags=0
        )
        inlet.open_stream(timeout=self.resolve_timeout_sec)
        return inlet

    def _time_correction(self, inlet: Any, stream: str) -> float:
        now = time.monotonic()
        cached = self._correction_cache.get(stream)
        if cached is not None and now - cached[0] < 5.0:
            return cached[1]
        try:
            correction = float(inlet.time_correction(timeout=0.0))
        except (AttributeError, TypeError):
            correction = float(inlet.time_correction()) if hasattr(inlet, "time_correction") else 0.0
        except Exception:
            if cached is not None:
                return cached[1]
            correction = float(inlet.time_correction(timeout=min(1.0, self.resolve_timeout_sec)))
        if not math.isfinite(correction):
            raise RuntimeError(f"TD10 LSL {stream} time_correction 不是有限值")
        self._correction_cache[stream] = (now, correction)
        self._clock_corrections.append(
            ClockCorrectionSample(stream, datetime.now(timezone.utc).isoformat(), correction)
        )
        self._timing_stats[f"{stream}_time_correction_sec"] = correction
        return correction

    def _pull_companions(self) -> None:
        if self._quality_inlet is not None:
            samples, timestamps = self._quality_inlet.pull_chunk(timeout=0.0, max_samples=self.max_chunk_samples)
            if samples:
                values = np.asarray(samples, dtype=np.int32)
                raw = np.asarray(timestamps, dtype=np.float64)
                if values.ndim != 2 or values.shape[1] != 3 or raw.shape != (values.shape[0],):
                    raise RuntimeError("TD10 LSL Quality 数据或时间戳形状无效")
                if np.any((values[:, 0] != 0) & (values[:, 0] != 1)):
                    raise RuntimeError("TD10 LSL Quality Valid 必须为 0 或 1")
                if np.any((values[:, 1] < -1) | (values[:, 1] > 255)):
                    raise RuntimeError("TD10 LSL Quality DeviceSeq 必须为 -1 或 0..255")
                correction = self._time_correction(self._quality_inlet, "quality")
                self._quality.append(QualityBatch(values.copy(), raw.copy(), raw + correction, correction))
                self._update_quality_stats(values)
        if self._markers_inlet is not None:
            samples, timestamps = self._markers_inlet.pull_chunk(timeout=0.0, max_samples=self.max_chunk_samples)
            if samples:
                raw = np.asarray(timestamps, dtype=np.float64)
                if raw.shape != (len(samples),):
                    raise RuntimeError("TD10 LSL Markers 时间戳数量无效")
                correction = self._time_correction(self._markers_inlet, "markers")
                for sample, timestamp in zip(samples, raw):
                    value = sample[0] if isinstance(sample, (list, tuple)) else sample
                    self._ifet_markers.append(
                        LSLMarker(str(value), float(timestamp), float(timestamp + correction), correction)
                    )

    def _update_quality_stats(self, values: np.ndarray) -> None:
        self._timing_stats["quality_samples"] = int(self._timing_stats["quality_samples"] or 0) + len(values)
        self._timing_stats["quality_invalid_samples"] = int(
            self._timing_stats["quality_invalid_samples"] or 0
        ) + int(np.count_nonzero(values[:, 0] == 0))
        for sequence in values[:, 1]:
            if int(sequence) == -1:
                self._last_device_seq = None
                continue
            current = int(sequence)
            if self._last_device_seq is not None:
                delta = (current - self._last_device_seq) & 0xFF
                if self._last_device_seq == 255 and current == 0:
                    self._timing_stats["device_seq_wraps"] = int(
                        self._timing_stats["device_seq_wraps"] or 0
                    ) + 1
                elif delta == 0:
                    self._timing_stats["device_seq_duplicates"] = int(
                        self._timing_stats["device_seq_duplicates"] or 0
                    ) + 1
                elif delta > 1:
                    self._timing_stats["device_seq_gaps"] = int(
                        self._timing_stats["device_seq_gaps"] or 0
                    ) + delta - 1
            self._last_device_seq = current

    def _update_eeg_timing_stats(self, timestamps: np.ndarray) -> None:
        if not len(timestamps):
            return
        if self._first_eeg_timestamp is None:
            self._first_eeg_timestamp = float(timestamps[0])
        previous = self._last_eeg_timestamp
        intervals = np.diff(timestamps)
        if previous is not None:
            intervals = np.concatenate(([float(timestamps[0]) - previous], intervals))
        if len(intervals):
            self._timing_stats["eeg_nonmonotonic_count"] = int(
                self._timing_stats["eeg_nonmonotonic_count"] or 0
            ) + int(np.count_nonzero(intervals <= 0))
            self._timing_stats["eeg_gap_count"] = int(
                self._timing_stats["eeg_gap_count"] or 0
            ) + int(np.count_nonzero(intervals > 1.5 / self.metadata.sfreq))
            self._timing_stats["eeg_max_interval_sec"] = max(
                float(self._timing_stats["eeg_max_interval_sec"] or 0.0),
                float(np.max(intervals)),
            )
        self._last_eeg_timestamp = float(timestamps[-1])

    def start_marker_outlet(self, session_id: str) -> None:
        if self._pylsl is None:
            raise RuntimeError("TD10 LSL stream is not started")
        info = self._pylsl.StreamInfo(
            "NeuroScope Markers",
            "Markers",
            1,
            0.0,
            getattr(self._pylsl, "cf_string"),
            f"neuroscope:{session_id}:markers",
        )
        self._marker_outlet = self._pylsl.StreamOutlet(info)

    def publish_marker(
        self, payload: dict[str, Any], *, retain_sidecar: bool = True
    ) -> NeuroScopeMarker:
        if self._pylsl is None or self._marker_outlet is None:
            raise RuntimeError("NeuroScope LSL Marker outlet is not started")
        timestamp = float(self._pylsl.local_clock())
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        self._marker_outlet.push_sample([text], timestamp=timestamp)
        marker = NeuroScopeMarker(text, timestamp)
        if retain_sidecar:
            self._neuroscope_markers.append(marker)
        return marker

    def stop_marker_outlet(self) -> None:
        self._marker_outlet = None

    def _validate_stream(self, info: Any) -> float:
        stream_type = str(info.type())
        if stream_type.casefold() != "eeg":
            raise RuntimeError(f"TD10 LSL 流 type 必须为 EEG，实际为 {stream_type!r}")
        actual_source_id = str(info.source_id())
        if actual_source_id != self.requested_source_id:
            raise RuntimeError(
                f"TD10 LSL source_id 不匹配：期望 {self.requested_source_id!r}，"
                f"实际 {actual_source_id!r}"
            )
        channel_count = int(info.channel_count())
        if channel_count != len(TD10_CHANNEL_NAMES):
            raise RuntimeError(f"TD10 LSL EEG 必须为 4 通道，实际为 {channel_count}")

        sfreq = float(info.nominal_srate())
        rounded_sfreq = int(round(sfreq))
        if not math.isclose(sfreq, rounded_sfreq, rel_tol=0.0, abs_tol=1e-6) or rounded_sfreq not in TD10_SAMPLE_RATES:
            raise RuntimeError(
                f"TD10 LSL 标称采样率必须为 {TD10_SAMPLE_RATES} Hz，实际为 {sfreq:g} Hz"
            )

        channel_format = info.channel_format()
        expected_format = getattr(self._pylsl, "cf_int32", None)
        format_text = str(channel_format).casefold()
        if channel_format != expected_format and format_text not in {"int32", "cf_int32"}:
            raise RuntimeError(f"TD10 LSL EEG 通道格式必须为 int32，实际为 {channel_format!r}")
        return float(rounded_sfreq)
