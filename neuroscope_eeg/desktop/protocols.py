from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


def frame_locked_frequencies(refresh_hz: float) -> tuple[float, ...]:
    """Return four frequencies whose cycles use an integer number of display frames."""
    refresh = max(30.0, float(refresh_hz))
    if refresh >= 150.0:
        frames_per_cycle = (20, 16, 10, 8)
    elif refresh >= 100.0:
        frames_per_cycle = (15, 12, 10, 8)
    else:
        frames_per_cycle = (8, 6, 5, 4)
    return tuple(round(refresh / frames, 3) for frames in frames_per_cycle)


@dataclass(frozen=True, slots=True)
class StimulusEvent:
    monotonic_time: float
    wall_time: float
    paradigm: str
    phase: str
    label: str
    payload: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["payload"] = dict(self.payload)
        return result

