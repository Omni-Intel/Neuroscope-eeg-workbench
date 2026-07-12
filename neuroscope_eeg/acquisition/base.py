from __future__ import annotations

from typing import Protocol

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata


class EEGSource(Protocol):
    metadata: SourceMetadata

    def start(self) -> None: ...

    def stop(self) -> None: ...

    def read_chunk(self) -> EEGChunk: ...
