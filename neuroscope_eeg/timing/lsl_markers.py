from __future__ import annotations

import importlib
import json
import time
from typing import Any

from neuroscope_eeg.timing.models import ClockBridgeSample


class LSLMarkerError(RuntimeError):
    pass


class LSLMarkerTransport:
    def __init__(self, *, pylsl_module: Any = None) -> None:
        self._pylsl = pylsl_module
        self._outlet: Any = None
        self.source_id = ""
        self.last_clock_bridge: ClockBridgeSample | None = None

    def open(self, session_id: str) -> None:
        try:
            pylsl = self._pylsl or importlib.import_module("pylsl")
            self._pylsl = pylsl
            self.source_id = f"neuroscope:{session_id}:markers"
            info = pylsl.StreamInfo(
                "NeuroScope_Markers",
                "Markers",
                1,
                0.0,
                getattr(pylsl, "cf_string"),
                self.source_id,
            )
            self._outlet = pylsl.StreamOutlet(info)
            self.last_clock_bridge = self.sample_clock_bridge()
        except Exception as exc:
            self.close()
            raise LSLMarkerError(f"无法创建 NeuroScope LSL Marker: {exc}") from exc

    def sample_clock_bridge(self) -> ClockBridgeSample:
        if self._pylsl is None:
            raise LSLMarkerError("pylsl 尚未加载")
        before = time.monotonic()
        lsl_time = float(self._pylsl.local_clock())
        after = time.monotonic()
        sample = ClockBridgeSample(before, lsl_time, after)
        self.last_clock_bridge = sample
        return sample

    def push(self, payload: dict[str, Any]) -> float:
        if self._outlet is None or self._pylsl is None:
            raise LSLMarkerError("LSL Marker Outlet 尚未打开")
        timestamp = float(self._pylsl.local_clock())
        marker = {**payload, "lsl_timestamp": timestamp}
        text = json.dumps(marker, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        try:
            self._outlet.push_sample([text], timestamp=timestamp, pushthrough=True)
        except TypeError:
            self._outlet.push_sample([text], timestamp=timestamp)
        return timestamp

    def close(self) -> None:
        self._outlet = None
        self._pylsl = None
        self.source_id = ""
        self.last_clock_bridge = None
