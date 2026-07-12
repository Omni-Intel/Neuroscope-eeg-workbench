from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class DecoderResult:
    value: str
    confidence: float
    source: str = "即时基线估计"
    detail: str = ""
    metrics: dict[str, float | str] = field(default_factory=dict)
    missing: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "confidence", min(1.0, max(0.0, float(self.confidence))))
