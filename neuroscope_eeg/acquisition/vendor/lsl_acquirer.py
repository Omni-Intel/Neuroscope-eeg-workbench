"""Generic LSL EEG acquisition backend used by the BCIGo desktop client."""

from __future__ import annotations

import logging
import math
import time
from typing import Any

import numpy as np

from neuroscope_eeg.acquisition.vendor.base import AbstractAcquirer, AcquirerMetadata, EEGChunk

LOGGER = logging.getLogger(__name__)


class LSLAcquirer(AbstractAcquirer):
    """Receive a regular-rate EEG stream from an external LSL publisher."""

    def __init__(
        self,
        sfreq: float = 250.0,
        n_channels: int = 32,
        buffer_sec: float = 60.0,
        stream_name: str = "",
        stream_type: str = "EEG",
        source_id: str = "",
        resolve_timeout_sec: float = 15.0,
        ready_timeout_sec: float = 10.0,
        backend_name: str = "lsl",
    ) -> None:
        if sfreq <= 0:
            raise ValueError("LSL EEG sample rate must be positive.")
        if n_channels <= 0:
            raise ValueError("LSL EEG channel count must be positive.")
        self.metadata = AcquirerMetadata(
            name=str(backend_name).strip() or "lsl",
            sfreq=float(sfreq),
            n_channels=int(n_channels),
        )
        self._buffer_sec = max(float(buffer_sec), 1.0)
        self._stream_name = str(stream_name).strip()
        self._stream_type = str(stream_type).strip() or "EEG"
        self._source_id = str(source_id).strip()
        self._resolve_timeout_sec = max(float(resolve_timeout_sec), 0.1)
        self._ready_timeout_sec = max(float(ready_timeout_sec), 0.1)
        self._inlet: Any = None
        self._stream_info: Any = None
        self._rolling_data = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        self._rolling_timestamps = np.empty((0,), dtype=np.float64)
        self._pending_data = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        self._pending_timestamps = np.empty((0,), dtype=np.float64)
        self._capacity = max(int(self.metadata.sfreq * self._buffer_sec), 1)

    @property
    def stream_identity(self) -> dict[str, Any]:
        info = self._stream_info
        if info is None:
            return {
                "name": self._stream_name,
                "type": self._stream_type,
                "source_id": self._source_id,
            }
        return {
            "name": info.name(),
            "type": info.type(),
            "source_id": info.source_id(),
            "channels": int(info.channel_count()),
            "sfreq": float(info.nominal_srate()),
        }

    def start_stream(self) -> None:
        from pylsl import StreamInlet

        if self._inlet is not None:
            self.stop_stream()
        info = self._resolve_stream()
        detected_channels = int(info.channel_count())
        detected_sfreq = float(info.nominal_srate())
        if detected_channels < self.metadata.n_channels:
            raise RuntimeError(
                f"BCIGo LSL stream has {detected_channels} channels; "
                f"the experiment requires {self.metadata.n_channels}."
            )
        if detected_sfreq <= 0:
            raise RuntimeError("BCIGo LSL EEG stream reports an irregular/invalid sample rate.")
        if abs(detected_sfreq - self.metadata.sfreq) > 0.01:
            raise RuntimeError(
                f"BCIGo LSL sample rate is {detected_sfreq:g} Hz, but config.yaml expects "
                f"{self.metadata.sfreq:g} Hz. Make both settings identical before recording."
            )

        self._stream_info = info
        self._rolling_data = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        self._rolling_timestamps = np.empty((0,), dtype=np.float64)
        self._pending_data = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        self._pending_timestamps = np.empty((0,), dtype=np.float64)
        # pylsl 1.18 expects max_buflen to be an integer number of seconds.
        self._inlet = StreamInlet(
            info,
            max_buflen=max(int(math.ceil(self._buffer_sec)), 1),
            recover=True,
        )
        try:
            self._inlet.open_stream(timeout=self._ready_timeout_sec)
            deadline = time.monotonic() + self._ready_timeout_sec
            while time.monotonic() < deadline:
                if self._pull_into_buffers(timeout_sec=0.25) > 0:
                    LOGGER.info("Connected to BCIGo LSL EEG stream: %s", self.stream_identity)
                    return
            raise RuntimeError(
                "Connected to the BCIGo LSL stream metadata, but no EEG samples arrived. "
                "Start real-time forwarding in BCIGo before the experiment preflight."
            )
        except Exception:
            self.stop_stream()
            raise

    def stop_stream(self) -> None:
        inlet = self._inlet
        self._inlet = None
        self._stream_info = None
        if inlet is not None:
            try:
                inlet.close_stream()
            except Exception:
                pass
        self._rolling_data = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        self._rolling_timestamps = np.empty((0,), dtype=np.float64)
        self._pending_data = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        self._pending_timestamps = np.empty((0,), dtype=np.float64)

    def get_chunk(self, window_sec: float) -> EEGChunk:
        self._require_started()
        required = max(int(float(window_sec) * self.metadata.sfreq), 1)
        deadline = time.monotonic() + max(float(window_sec), 0.1) + self._ready_timeout_sec
        while self._rolling_data.shape[1] < required and time.monotonic() < deadline:
            self._pull_into_buffers(timeout_sec=0.1)
        if self._rolling_data.shape[1] < required:
            raise RuntimeError(
                f"Not enough BCIGo LSL samples: have {self._rolling_data.shape[1]}, need {required}."
            )
        return self._rolling_data[:, -required:].copy(), self._rolling_timestamps[-required:].copy()

    def get_new_samples(self) -> EEGChunk:
        self._require_started()
        while self._pull_into_buffers(timeout_sec=0.0) > 0:
            pass
        data = self._pending_data
        timestamps = self._pending_timestamps
        self._pending_data = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        self._pending_timestamps = np.empty((0,), dtype=np.float64)
        return data, timestamps

    def _resolve_stream(self) -> Any:
        from pylsl import resolve_streams

        deadline = time.monotonic() + self._resolve_timeout_sec
        last_seen: list[dict[str, Any]] = []
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            streams = resolve_streams(wait_time=min(max(remaining, 0.05), 1.0))
            last_seen = [self._describe_stream(item) for item in streams]
            matches = [item for item in streams if self._matches_stream(item)]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                identities = [self._describe_stream(item) for item in matches]
                raise RuntimeError(
                    "Multiple BCIGo LSL EEG streams match the current settings. "
                    f"Set device.brainco_lsl_stream_name and brainco_lsl_source_id: {identities}"
                )
        criteria = {
            "name": self._stream_name or "<any>",
            "type": self._stream_type or "<any>",
            "source_id": self._source_id or "<any>",
        }
        raise RuntimeError(
            f"No matching BCIGo LSL EEG stream found. criteria={criteria}; visible_streams={last_seen}"
        )

    def _matches_stream(self, info: Any) -> bool:
        if self._stream_name and info.name() != self._stream_name:
            return False
        if self._stream_type and info.type().casefold() != self._stream_type.casefold():
            return False
        if self._source_id and info.source_id() != self._source_id:
            return False
        return int(info.channel_count()) >= self.metadata.n_channels

    @staticmethod
    def _describe_stream(info: Any) -> dict[str, Any]:
        return {
            "name": info.name(),
            "type": info.type(),
            "source_id": info.source_id(),
            "channels": int(info.channel_count()),
            "sfreq": float(info.nominal_srate()),
        }

    def _pull_into_buffers(self, *, timeout_sec: float) -> int:
        self._require_started()
        max_samples = max(int(self.metadata.sfreq), 32)
        samples, timestamps = self._inlet.pull_chunk(timeout=timeout_sec, max_samples=max_samples)
        if not timestamps:
            return 0
        array = np.asarray(samples, dtype=np.float32)
        if array.ndim != 2 or array.shape[0] != len(timestamps):
            raise RuntimeError(f"Unexpected BCIGo LSL chunk shape: {array.shape}")
        if array.shape[1] < self.metadata.n_channels:
            raise RuntimeError(f"BCIGo LSL chunk has too few channels: {array.shape}")
        data = np.ascontiguousarray(array[:, : self.metadata.n_channels].T)
        ts = np.asarray(timestamps, dtype=np.float64)
        self._rolling_data = np.concatenate((self._rolling_data, data), axis=1)[:, -self._capacity :]
        self._rolling_timestamps = np.concatenate((self._rolling_timestamps, ts))[-self._capacity :]
        self._pending_data = np.concatenate((self._pending_data, data), axis=1)
        self._pending_timestamps = np.concatenate((self._pending_timestamps, ts))
        return int(data.shape[1])

    def _require_started(self) -> None:
        if self._inlet is None:
            raise RuntimeError("BCIGo LSL stream is not started")
