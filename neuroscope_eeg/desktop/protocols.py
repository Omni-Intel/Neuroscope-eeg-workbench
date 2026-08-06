from __future__ import annotations

from dataclasses import asdict, dataclass, field
import random
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


def generate_oddball_sequence(
    trials: int,
    *,
    deviant_probability: float = 0.2,
    seed: int = 17,
) -> tuple[str, ...]:
    if trials <= 0:
        raise ValueError("trials must be positive")
    if not 0.0 < deviant_probability < 0.5:
        raise ValueError("deviant_probability must be between 0 and 0.5")
    deviant_count = max(1, int(round(trials * deviant_probability)))
    if deviant_count * 2 > trials + 1:
        raise ValueError("too many deviants to keep them non-adjacent")

    rng = random.Random(seed)
    compressed = sorted(rng.sample(range(trials - deviant_count + 1), deviant_count))
    deviant_positions = {position + offset for offset, position in enumerate(compressed)}
    return tuple("deviant" if index in deviant_positions else "standard" for index in range(trials))


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
