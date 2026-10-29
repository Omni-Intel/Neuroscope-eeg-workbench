"""Abstract EEG acquisition interfaces shared by all devices."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TypeAlias

import numpy as np

EEGChunk: TypeAlias = tuple[np.ndarray, np.ndarray]


@dataclass(slots=True)
class AcquirerMetadata:
    """Static metadata exposed by an acquisition backend."""

    name: str
    sfreq: float
    n_channels: int
    eeg_channel_count: int | None = None
    trigger_channel_index: int | None = None
    trigger_channel_name: str | None = None


class AbstractAcquirer(ABC):
    """Unified interface for all EEG sources."""

    metadata: AcquirerMetadata

    @abstractmethod
    def start_stream(self) -> None:
        """Start the underlying device or stream connection."""

    @abstractmethod
    def stop_stream(self) -> None:
        """Stop the underlying device or stream connection."""

    @abstractmethod
    def get_chunk(self, window_sec: float) -> EEGChunk:
        """Return the latest EEG window and timestamps."""

    @abstractmethod
    def get_new_samples(self) -> EEGChunk:
        """Return newly arrived EEG samples since the previous incremental read."""
