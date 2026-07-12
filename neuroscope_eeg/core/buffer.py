from __future__ import annotations

import threading
from collections import deque

import numpy as np

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata


class RollingBuffer:
    def __init__(self, metadata: SourceMetadata, duration_sec: float) -> None:
        if duration_sec <= 0:
            raise ValueError("duration_sec must be positive")
        self.metadata = metadata
        self.max_samples = max(1, int(round(metadata.sfreq * duration_sec)))
        self._chunks: deque[tuple[np.ndarray, np.ndarray]] = deque()
        self._n_samples = 0
        self._lock = threading.Lock()

    def append(self, chunk: EEGChunk) -> None:
        if chunk.metadata.n_channels != self.metadata.n_channels:
            raise ValueError("chunk channel count does not match buffer metadata")
        if chunk.n_samples == 0:
            return
        with self._lock:
            self._chunks.append((chunk.data, chunk.timestamps))
            self._n_samples += chunk.n_samples
            while self._n_samples > self.max_samples:
                extra = self._n_samples - self.max_samples
                data, timestamps = self._chunks[0]
                if data.shape[1] <= extra:
                    self._chunks.popleft()
                    self._n_samples -= data.shape[1]
                else:
                    self._chunks[0] = (data[:, extra:], timestamps[extra:])
                    self._n_samples -= extra

    def latest(self, duration_sec: float) -> tuple[np.ndarray, np.ndarray] | None:
        n_samples = max(1, int(round(duration_sec * self.metadata.sfreq)))
        with self._lock:
            if self._n_samples < n_samples:
                return None
            data = np.concatenate([item[0] for item in self._chunks], axis=1)
            timestamps = np.concatenate([item[1] for item in self._chunks])
        return data[:, -n_samples:], timestamps[-n_samples:]

    def snapshot(self) -> tuple[np.ndarray, np.ndarray]:
        with self._lock:
            if not self._chunks:
                return (
                    np.empty((self.metadata.n_channels, 0), dtype=np.float32),
                    np.empty((0,), dtype=np.float64),
                )
            data = np.concatenate([item[0] for item in self._chunks], axis=1)
            timestamps = np.concatenate([item[1] for item in self._chunks])
        return data, timestamps

    def sample_count(self) -> int:
        with self._lock:
            return self._n_samples
