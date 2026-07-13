from __future__ import annotations

import time
from collections import deque


SUPPORTED_FPS = (20, 30, 60)


def timer_interval_ms(fps: int) -> int:
    if fps not in SUPPORTED_FPS:
        raise ValueError(f"unsupported refresh rate: {fps}")
    return round(1000 / fps)


def fps_level(actual_fps: float, target_fps: int) -> str:
    ratio = actual_fps / target_fps if target_fps > 0 else 0.0
    if ratio >= 0.8:
        return "good"
    if ratio >= 0.5:
        return "warning"
    return "critical"


class FpsTracker:
    def __init__(self, window_sec: float = 2.0) -> None:
        self.window_sec = window_sec
        self._frames: deque[float] = deque()

    def tick(self, now: float | None = None) -> None:
        timestamp = time.monotonic() if now is None else now
        self._frames.append(timestamp)
        cutoff = timestamp - self.window_sec
        while self._frames and self._frames[0] < cutoff:
            self._frames.popleft()

    @property
    def fps(self) -> float:
        if len(self._frames) < 2:
            return 0.0
        elapsed = self._frames[-1] - self._frames[0]
        return 0.0 if elapsed <= 0 else (len(self._frames) - 1) / elapsed

    def reset(self) -> None:
        self._frames.clear()

