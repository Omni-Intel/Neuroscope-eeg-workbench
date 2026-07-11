from __future__ import annotations

from pathlib import Path

import numpy as np

from mi_control.core.models import EEGChunk, SourceMetadata
from realtime_eeg_viewer import BrainCoSource as LegacyBrainCoSource
from realtime_eeg_viewer import NeuracleSource as LegacyNeuracleSource


class LegacyRealtimeSource:
    def __init__(self, legacy_source) -> None:
        self.legacy_source = legacy_source
        self.metadata = SourceMetadata.eeg(
            source_id=legacy_source.metadata.name,
            source_type=legacy_source.metadata.name,
            sfreq=float(legacy_source.metadata.sfreq),
            channel_names=tuple(legacy_source.metadata.channel_names),
        )
        self._sample = 0

    def start(self) -> None:
        self.legacy_source.start()
        self.metadata = SourceMetadata.eeg(
            source_id=self.legacy_source.metadata.name,
            source_type=self.legacy_source.metadata.name,
            sfreq=float(self.legacy_source.metadata.sfreq),
            channel_names=tuple(self.legacy_source.metadata.channel_names),
        )
        self._sample = 0

    def stop(self) -> None:
        self.legacy_source.stop()

    def read_chunk(self) -> EEGChunk:
        data = np.asarray(self.legacy_source.get_new_samples(), dtype=np.float32)
        if data.ndim != 2:
            raise RuntimeError(f"expected channel-major EEG data, got shape {data.shape}")
        if data.shape[0] != self.metadata.n_channels:
            data = data[: self.metadata.n_channels]
        timestamps = (np.arange(data.shape[1], dtype=np.float64) + self._sample) / self.metadata.sfreq
        sequence = self._sample
        self._sample += data.shape[1]
        return EEGChunk(metadata=self.metadata, data=data, timestamps=timestamps, sequence=sequence)


def build_neuracle_source(
    oi_mi_path: str,
    host: str,
    port: int,
    sfreq: float,
    n_channels: int,
    buffer_sec: float = 30.0,
    ready_timeout_sec: float = 15.0,
) -> LegacyRealtimeSource:
    return LegacyRealtimeSource(
        LegacyNeuracleSource(
            oi_mi_path=Path(oi_mi_path).expanduser(),
            host=host,
            port=port,
            sfreq=sfreq,
            n_channels=n_channels,
            buffer_sec=buffer_sec,
            ready_timeout_sec=ready_timeout_sec,
        )
    )


def build_brainco_source(
    oi_mi_path: str,
    sfreq: float,
    n_channels: int,
    brainco_addr: str = "",
    brainco_port: int = 0,
    auto_discover: bool = True,
) -> LegacyRealtimeSource:
    return LegacyRealtimeSource(
        LegacyBrainCoSource(
            oi_mi_path=Path(oi_mi_path).expanduser(),
            sfreq=sfreq,
            n_channels=n_channels,
            buffer_sec=30.0,
            brainco_addr=brainco_addr,
            brainco_port=brainco_port,
            auto_discover=auto_discover,
            scan_timeout_sec=6.0,
            ready_timeout_sec=20.0,
            start_retries=2,
            eeg_gain=6,
            signal_source="NORMAL",
            device_id="eeg-cap",
        )
    )
