from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from neuroscope_eeg.core.models import EEGEvent, SourceMetadata
from neuroscope_eeg.decoders.baseline import BASELINE_DECODERS


@dataclass(frozen=True, slots=True)
class ParadigmResult:
    paradigm: str
    status: str
    headline: str
    metrics: dict[str, float | str]
    decoder_name: str
    source: str
    confidence: float
    detail: str
    missing: tuple[str, ...] = ()


class Paradigm:
    def __init__(self, key: str, label: str) -> None:
        self.key = key
        self.label = label

    def analyze(
        self,
        metadata: SourceMetadata,
        data: np.ndarray,
        events: tuple[EEGEvent, ...] = (),
    ) -> ParadigmResult:
        decoder = BASELINE_DECODERS[self.label]
        decoded = decoder.decode(metadata, data, events[-1] if events else None)
        status = "estimated" if decoded.value != "尚未解码" else "not_decoded"
        return ParadigmResult(
            paradigm=self.key,
            status=status,
            headline=decoded.value,
            metrics=decoded.metrics,
            decoder_name=decoder.name,
            source=decoded.source,
            confidence=decoded.confidence,
            detail=decoded.detail,
            missing=decoded.missing,
        )


PARADIGMS: dict[str, Paradigm] = {
    "SSVEP": Paradigm("ssvep", "SSVEP"),
    "运动想象": Paradigm("motor_imagery", "运动想象"),
    "视觉图像识别": Paradigm("visual_awareness", "视觉图像识别"),
    "注意力": Paradigm("attention", "注意力"),
    "情绪分类": Paradigm("emotion", "情绪分类"),
}
