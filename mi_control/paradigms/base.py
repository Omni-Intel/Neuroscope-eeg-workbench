from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mi_control.analysis.spectrum import band_power, power_spectrum, ssvep_snr
from mi_control.core.models import EEGEvent, SourceMetadata


@dataclass(frozen=True, slots=True)
class ParadigmResult:
    paradigm: str
    status: str
    headline: str
    metrics: dict[str, float | str]


class Paradigm:
    label = "Generic"

    def analyze(
        self,
        metadata: SourceMetadata,
        data: np.ndarray,
        events: tuple[EEGEvent, ...] = (),
    ) -> ParadigmResult:
        raise NotImplementedError


def _mean_band_metrics(metadata: SourceMetadata, data: np.ndarray) -> dict[str, float]:
    freqs, psd = power_spectrum(data, metadata.sfreq)
    bands = band_power(freqs, psd)
    return {name: float(np.mean(values)) for name, values in bands.items()}


class SSVEPParadigm(Paradigm):
    label = "SSVEP"

    def __init__(self, targets: tuple[float, ...] = (8.0, 10.0, 12.0, 15.0)) -> None:
        self.targets = targets

    def analyze(
        self,
        metadata: SourceMetadata,
        data: np.ndarray,
        events: tuple[EEGEvent, ...] = (),
    ) -> ParadigmResult:
        freqs, psd = power_spectrum(data, metadata.sfreq)
        scores = ssvep_snr(freqs, psd, self.targets)
        best = max(scores, key=scores.get) if scores else 0.0
        metrics = {f"{freq:g} Hz SNR": float(score) for freq, score in scores.items()}
        return ParadigmResult("ssvep", "features", f"最强响应：{best:g} Hz", metrics)


class MotorImageryParadigm(Paradigm):
    label = "运动想象"

    def analyze(
        self,
        metadata: SourceMetadata,
        data: np.ndarray,
        events: tuple[EEGEvent, ...] = (),
    ) -> ParadigmResult:
        metrics = _mean_band_metrics(metadata, data)
        return ParadigmResult("motor_imagery", "features", "未加载验证模型：显示 mu/beta 特征", metrics)


class VisualAwarenessParadigm(Paradigm):
    label = "视觉图像识别"

    def analyze(
        self,
        metadata: SourceMetadata,
        data: np.ndarray,
        events: tuple[EEGEvent, ...] = (),
    ) -> ParadigmResult:
        metrics = _mean_band_metrics(metadata, data)
        latest = events[-1].payload if events else {}
        if latest:
            metrics["target_present"] = str(bool(latest.get("target_present", False)))
            metrics["seen_reported"] = str(bool(latest.get("seen_reported", False)))
            headline = "目标出现/主观看见已分开记录"
        else:
            headline = "未加载验证模型：显示图像任务 EEG 特征"
        return ParadigmResult("visual_awareness", "features", headline, metrics)


class AttentionParadigm(Paradigm):
    label = "注意力"

    def analyze(
        self,
        metadata: SourceMetadata,
        data: np.ndarray,
        events: tuple[EEGEvent, ...] = (),
    ) -> ParadigmResult:
        metrics = _mean_band_metrics(metadata, data)
        return ParadigmResult("attention", "features", "未加载验证模型：显示注意力相关频段特征", metrics)


class EmotionParadigm(Paradigm):
    label = "情绪分类"

    def analyze(
        self,
        metadata: SourceMetadata,
        data: np.ndarray,
        events: tuple[EEGEvent, ...] = (),
    ) -> ParadigmResult:
        metrics = _mean_band_metrics(metadata, data)
        return ParadigmResult("emotion", "features", "未加载验证模型：显示情绪分类候选特征", metrics)


PARADIGMS: dict[str, Paradigm] = {
    "SSVEP": SSVEPParadigm(),
    "运动想象": MotorImageryParadigm(),
    "视觉图像识别": VisualAwarenessParadigm(),
    "注意力": AttentionParadigm(),
    "情绪分类": EmotionParadigm(),
}
