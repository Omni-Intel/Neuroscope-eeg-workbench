from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HardwareWrite:
    code: int
    frame_hex: str
    requested_at: float
    write_completed_at: float


@dataclass(frozen=True, slots=True)
class ClockBridgeSample:
    monotonic_before: float
    lsl_time: float
    monotonic_after: float

    @property
    def monotonic_midpoint(self) -> float:
        return (self.monotonic_before + self.monotonic_after) / 2.0

    @property
    def lsl_minus_monotonic(self) -> float:
        return self.lsl_time - self.monotonic_midpoint

    @property
    def uncertainty_ms(self) -> float:
        return max(0.0, self.monotonic_after - self.monotonic_before) * 1000.0


@dataclass(frozen=True, slots=True)
class HardwareTriggerSample:
    code: int
    sample_index: int
    channel_name: str


@dataclass(frozen=True, slots=True)
class HardwareTriggerBatch:
    samples: tuple[HardwareTriggerSample, ...]

    @property
    def is_empty(self) -> bool:
        return not self.samples


@dataclass(frozen=True, slots=True)
class TriggerRequest:
    paradigm: str
    phase: str
    label: str
    payload: dict[str, Any] = field(default_factory=dict)
    wall_time: float = 0.0
    intent_time: float = 0.0
    onset_hook_time: float = 0.0
    hook_type: str = "software"


@dataclass(frozen=True, slots=True)
class TriggerDispatch:
    event_id: str
    sequence: int
    session_id: str
    paradigm: str
    phase: str
    label: str
    payload: dict[str, Any]
    wall_time: float
    intent_time: float
    onset_hook_time: float
    hook_type: str
    timing_mode: str
    timing_status: str
    hardware_code: int | None = None
    hardware_symbol: str = ""
    hardware_requested: bool = False
    hardware_frame_hex: str = ""
    hardware_dispatch_time: float | None = None
    hardware_write_complete_time: float | None = None
    hardware_error: str = ""
    lsl_timestamp: float | None = None
    lsl_error: str = ""
    clock_bridge: ClockBridgeSample | None = None

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["payload"] = dict(self.payload)
        return result
