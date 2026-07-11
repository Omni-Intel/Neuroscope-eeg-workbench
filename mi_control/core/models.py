from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np


class ConnectionState(Enum):
    IDLE = "idle"
    CONNECTING = "connecting"
    RUNNING = "running"
    RECONNECTING = "reconnecting"
    STOPPING = "stopping"
    STOPPED = "stopped"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class SourceMetadata:
    source_id: str
    source_type: str
    sfreq: float
    channel_names: tuple[str, ...]
    channel_types: tuple[str, ...]
    channel_units: tuple[str, ...]
    extra: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sfreq <= 0:
            raise ValueError("sfreq must be positive")
        if not self.channel_names:
            raise ValueError("at least one channel is required")
        if len({len(self.channel_names), len(self.channel_types), len(self.channel_units)}) != 1:
            raise ValueError("channel fields must have equal length")
        object.__setattr__(self, "channel_names", tuple(str(x) for x in self.channel_names))
        object.__setattr__(self, "channel_types", tuple(str(x).lower() for x in self.channel_types))
        object.__setattr__(self, "channel_units", tuple(str(x) for x in self.channel_units))
        object.__setattr__(self, "extra", MappingProxyType(dict(self.extra)))

    @classmethod
    def eeg(
        cls,
        source_id: str,
        source_type: str,
        sfreq: float,
        channel_names: tuple[str, ...],
        unit: str = "uV",
    ) -> "SourceMetadata":
        return cls(
            source_id=source_id,
            source_type=source_type,
            sfreq=sfreq,
            channel_names=channel_names,
            channel_types=tuple("eeg" for _ in channel_names),
            channel_units=tuple(unit for _ in channel_names),
        )

    @property
    def n_channels(self) -> int:
        return len(self.channel_names)


@dataclass(frozen=True, slots=True)
class EEGChunk:
    metadata: SourceMetadata
    data: np.ndarray
    timestamps: np.ndarray
    sequence: int

    def __post_init__(self) -> None:
        data = np.asarray(self.data, dtype=np.float32)
        timestamps = np.asarray(self.timestamps, dtype=np.float64)
        if data.ndim != 2:
            raise ValueError("data must be channel-major with shape (channels, samples)")
        if data.shape[0] != self.metadata.n_channels:
            raise ValueError(f"expected {self.metadata.n_channels} channels, got {data.shape[0]}")
        if timestamps.ndim != 1 or timestamps.shape[0] != data.shape[1]:
            raise ValueError("timestamps must be 1D and match sample count")
        if self.sequence < 0:
            raise ValueError("sequence must be non-negative")
        object.__setattr__(self, "data", data)
        object.__setattr__(self, "timestamps", timestamps)

    @property
    def n_samples(self) -> int:
        return int(self.data.shape[1])


@dataclass(frozen=True, slots=True)
class EEGEvent:
    timestamp: float
    name: str
    code: int | str
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))
