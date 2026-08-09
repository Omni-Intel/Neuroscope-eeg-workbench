"""TD10 headband EEG acquisition through the Lab Streaming Layer."""

from __future__ import annotations

import importlib
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata


TD10_CHANNEL_NAMES = ("EEG1", "EEG2", "EEG3", "EEG4")
TD10_SAMPLE_RATES = (125, 250, 500, 1000)
TD10_ADC_MIN = -8_388_608
TD10_ADC_MAX = 8_388_607
DEFAULT_TD10_BASE_SOURCE_ID = "ifet-td10-headset"


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
        self.resolve_timeout_sec = float(resolve_timeout_sec)
        self.pull_timeout_sec = float(pull_timeout_sec)
        self.max_chunk_samples = int(max_chunk_samples)
        self.metadata = self._metadata(float(fallback_sfreq), stream_name="")
        self._pylsl: Any = None
        self._inlet: Any = None
        self._sample_index = 0

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
                "lsl_timestamp_clock": "LSL local_clock",
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
        except Exception:
            self._pylsl = None
            raise

        self._inlet = inlet
        self.metadata = self._metadata(sfreq, stream_name=str(info.name()))
        self._sample_index = 0

    def stop(self) -> None:
        inlet, self._inlet = self._inlet, None
        self._pylsl = None
        if inlet is not None:
            try:
                inlet.close_stream()
            except Exception:
                pass

    def read_chunk(self) -> EEGChunk:
        if self._inlet is None:
            raise RuntimeError("TD10 LSL stream is not started")

        samples, timestamps = self._inlet.pull_chunk(
            timeout=self.pull_timeout_sec,
            max_samples=self.max_chunk_samples,
        )
        if len(samples) == 0:
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

        sequence = self._sample_index
        self._sample_index += sample_major.shape[0]
        return EEGChunk(
            metadata=self.metadata,
            data=np.asarray(sample_major.T, dtype=np.float32),
            timestamps=lsl_timestamps,
            sequence=sequence,
        )

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
