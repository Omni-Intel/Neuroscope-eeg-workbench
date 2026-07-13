import time

import numpy as np

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata
from neuroscope_eeg.core.session import SessionController


class _StreamingSource:
    def __init__(self) -> None:
        self.metadata = SourceMetadata.eeg("test", "brainco", 10.0, ("C3", "C4"))
        self.sequence = 0

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def read_chunk(self) -> EEGChunk:
        time.sleep(0.005)
        sequence = self.sequence
        self.sequence += 2
        return EEGChunk(
            self.metadata,
            np.ones((2, 2), dtype=np.float32),
            np.arange(sequence, sequence + 2, dtype=float) / 10.0,
            sequence,
        )


def test_session_tracks_received_chunks_samples_and_freshness() -> None:
    controller = SessionController(_StreamingSource())
    controller.start()
    deadline = time.monotonic() + 1.0
    while controller.samples_received < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    controller.stop()

    assert controller.chunks_received >= 1
    assert controller.samples_received >= 2
    assert controller.last_data_age_sec() is not None
