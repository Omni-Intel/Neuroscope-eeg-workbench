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


class _MetadataChangingSource:
    def __init__(self) -> None:
        self.metadata = SourceMetadata.eeg("changing", "test", 100.0, ("C3", "C4", "Cz"))
        self.sequence = 0
        self.started = False

    def start(self) -> None:
        self.metadata = SourceMetadata.eeg("changing", "test", 100.0, ("C3", "C4"))
        self.started = True

    def stop(self) -> None:
        self.started = False

    def read_chunk(self) -> EEGChunk:
        if not self.started:
            raise RuntimeError("not started")
        time.sleep(0.001)
        sequence = self.sequence
        self.sequence += 10
        return EEGChunk(
            self.metadata,
            np.ones((2, 10), dtype=np.float32),
            np.arange(sequence, sequence + 10, dtype=float) / 100.0,
            sequence,
        )


def test_session_rebuilds_buffer_after_source_metadata_changes() -> None:
    controller = SessionController(_MetadataChangingSource(), buffer_sec=1.0)
    controller.start()
    deadline = time.monotonic() + 1.0
    while controller.samples_received == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    controller.stop()

    assert controller.error is None
    assert controller.buffer.metadata.channel_names == ("C3", "C4")
    assert controller.samples_received > 0


class _EmptySource:
    def __init__(self) -> None:
        self.metadata = SourceMetadata.eeg("empty", "test", 100.0, ("Cz",))
        self.read_count = 0

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def read_chunk(self) -> EEGChunk:
        self.read_count += 1
        return EEGChunk(
            self.metadata,
            np.empty((1, 0), dtype=np.float32),
            np.empty(0, dtype=float),
            self.read_count,
        )


def test_session_yields_when_source_has_no_new_samples() -> None:
    source = _EmptySource()
    controller = SessionController(source)
    controller.start()
    time.sleep(0.05)
    controller.stop()

    assert source.read_count < 100


class _CollectingRecorder:
    def __init__(self) -> None:
        self.chunks: list[EEGChunk] = []

    def submit(self, chunk: EEGChunk) -> None:
        self.chunks.append(chunk)


def test_session_recorder_hook_receives_full_chunks_before_display_selection() -> None:
    source = _StreamingSource()
    recorder = _CollectingRecorder()
    controller = SessionController(source)
    controller.attach_recorder(recorder)
    controller.start()
    deadline = time.monotonic() + 1.0
    while not recorder.chunks and time.monotonic() < deadline:
        time.sleep(0.01)
    controller.stop()

    assert recorder.chunks
    assert recorder.chunks[0].metadata.channel_names == ("C3", "C4")
    assert recorder.chunks[0].data.shape[0] == 2


class _SidecarSource(_StreamingSource):
    def __init__(self) -> None:
        super().__init__()
        self.sidecars = ["timing-1", "timing-2"]

    def drain_sidecars(self) -> str | None:
        return self.sidecars.pop(0) if self.sidecars else None


class _SidecarRecorder(_CollectingRecorder):
    def __init__(self) -> None:
        super().__init__()
        self.sidecars: list[str] = []

    def submit_sidecars(self, sidecars: str) -> None:
        self.sidecars.append(sidecars)


def test_session_forwards_optional_source_sidecars_once() -> None:
    source = _SidecarSource()
    recorder = _SidecarRecorder()
    controller = SessionController(source)
    controller.attach_recorder(recorder)
    controller.start()
    deadline = time.monotonic() + 1.0
    while len(recorder.sidecars) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    controller.stop()

    assert recorder.sidecars[:2] == ["timing-1", "timing-2"]
    assert source.sidecars == []


def test_session_drains_sidecars_without_recorder() -> None:
    source = _SidecarSource()
    controller = SessionController(source)
    controller.start()
    deadline = time.monotonic() + 1.0
    while source.sidecars and time.monotonic() < deadline:
        time.sleep(0.01)
    controller.stop()

    assert source.sidecars == []
