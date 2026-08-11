from __future__ import annotations

import threading
import time
from typing import Any, Protocol

from neuroscope_eeg.acquisition.base import EEGSource
from neuroscope_eeg.core.buffer import RollingBuffer
from neuroscope_eeg.core.models import ConnectionState, EEGChunk


class ChunkRecorder(Protocol):
    def submit(self, chunk: EEGChunk) -> None: ...


class SidecarSource(Protocol):
    def drain_sidecars(self) -> Any: ...


class SidecarRecorder(Protocol):
    def submit_sidecars(self, sidecars: Any) -> None: ...


class SessionController:
    def __init__(self, source: EEGSource, buffer_sec: float = 30.0) -> None:
        self.source = source
        self._buffer_sec = buffer_sec
        self.buffer = RollingBuffer(source.metadata, self._buffer_sec)
        self.state = ConnectionState.IDLE
        self.error: str | None = None
        self.started_at: float | None = None
        self.chunks_received = 0
        self.samples_received = 0
        self.last_data_at: float | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._recorder: ChunkRecorder | None = None
        self._recorder_lock = threading.Lock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.error = None
        self._stop.clear()
        self.state = ConnectionState.CONNECTING
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        try:
            self.source.start()
            if self.buffer.metadata != self.source.metadata:
                self.buffer = RollingBuffer(self.source.metadata, self._buffer_sec)
            self.started_at = time.monotonic()
            self.state = ConnectionState.RUNNING
            while not self._stop.is_set():
                chunk: EEGChunk = self.source.read_chunk()
                drain_sidecars = getattr(self.source, "drain_sidecars", None)
                sidecars = drain_sidecars() if callable(drain_sidecars) else None
                drain_hardware_triggers = getattr(self.source, "drain_hardware_triggers", None)
                hardware_triggers = (
                    tuple(drain_hardware_triggers()) if callable(drain_hardware_triggers) else ()
                )
                with self._recorder_lock:
                    if chunk.n_samples > 0:
                        if self._recorder is not None:
                            self._recorder.submit(chunk)
                    submit_sidecars = getattr(self._recorder, "submit_sidecars", None)
                    if sidecars is not None and callable(submit_sidecars):
                        submit_sidecars(sidecars)
                    submit_hardware_triggers = getattr(
                        self._recorder, "submit_hardware_triggers", None
                    )
                    if hardware_triggers and callable(submit_hardware_triggers):
                        submit_hardware_triggers(hardware_triggers)
                self.buffer.append(chunk)
                if chunk.n_samples > 0:
                    self.chunks_received += 1
                    self.samples_received += chunk.n_samples
                    self.last_data_at = time.monotonic()
                else:
                    time.sleep(0.002)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
            self.state = ConnectionState.ERROR
        finally:
            try:
                self.source.stop()
            finally:
                if self.state is not ConnectionState.ERROR:
                    self.state = ConnectionState.STOPPED

    def stop(self, timeout: float = 2.0) -> None:
        self.state = ConnectionState.STOPPING
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        if self.state is not ConnectionState.ERROR:
            self.state = ConnectionState.STOPPED

    def elapsed_sec(self) -> float:
        return 0.0 if self.started_at is None else time.monotonic() - self.started_at

    def last_data_age_sec(self) -> float | None:
        return None if self.last_data_at is None else max(0.0, time.monotonic() - self.last_data_at)

    def attach_recorder(self, recorder: ChunkRecorder) -> None:
        with self._recorder_lock:
            if self._recorder is not None:
                raise RuntimeError("a session recorder is already attached")
            self._recorder = recorder

    def detach_recorder(self, recorder: ChunkRecorder | None = None) -> None:
        with self._recorder_lock:
            if recorder is None or self._recorder is recorder:
                self._recorder = None
