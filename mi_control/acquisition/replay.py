from __future__ import annotations

from pathlib import Path

import numpy as np

from mi_control.core.models import EEGChunk, SourceMetadata


class NPZReplaySource:
    def __init__(self, path: Path, packet_samples: int = 32) -> None:
        loaded = np.load(path, allow_pickle=False)
        self.data = np.asarray(loaded["data"], dtype=np.float32)
        self.timestamps = np.asarray(loaded["timestamps"], dtype=np.float64)
        channel_names = tuple(str(x) for x in loaded["channel_names"].tolist())
        sfreq = float(loaded["sfreq"])
        self.metadata = SourceMetadata.eeg(path.stem, "npz_replay", sfreq, channel_names)
        if self.data.ndim != 2 or self.data.shape[0] != self.metadata.n_channels:
            raise ValueError("NPZ data must have shape (channels, samples)")
        if self.timestamps.shape != (self.data.shape[1],):
            raise ValueError("NPZ timestamps must match sample count")
        self.packet_samples = max(1, int(packet_samples))
        self._cursor = 0
        self._started = False

    def start(self) -> None:
        self._cursor = 0
        self._started = True

    def stop(self) -> None:
        self._started = False

    def read_chunk(self) -> EEGChunk:
        if not self._started:
            raise RuntimeError("source is not started")
        if self._cursor >= self.data.shape[1]:
            self._cursor = 0
        end = min(self._cursor + self.packet_samples, self.data.shape[1])
        start = self._cursor
        self._cursor = end
        return EEGChunk(
            metadata=self.metadata,
            data=self.data[:, start:end],
            timestamps=self.timestamps[start:end],
            sequence=start,
        )


def save_replay_npz(
    path: Path,
    metadata: SourceMetadata,
    data: np.ndarray,
    timestamps: np.ndarray,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        data=np.asarray(data, dtype=np.float32),
        timestamps=np.asarray(timestamps, dtype=np.float64),
        channel_names=np.asarray(metadata.channel_names),
        sfreq=np.asarray(metadata.sfreq),
    )
