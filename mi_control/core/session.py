from __future__ import annotations

import threading
import time

from mi_control.acquisition.base import EEGSource
from mi_control.core.buffer import RollingBuffer
from mi_control.core.models import ConnectionState, EEGChunk


class SessionController:
    def __init__(self, source: EEGSource, buffer_sec: float = 30.0) -> None:
        self.source = source
        self.buffer = RollingBuffer(source.metadata, buffer_sec)
        self.state = ConnectionState.IDLE
        self.error: str | None = None
        self.started_at: float | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

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
            self.started_at = time.monotonic()
            self.state = ConnectionState.RUNNING
            while not self._stop.is_set():
                chunk: EEGChunk = self.source.read_chunk()
                self.buffer.append(chunk)
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
