from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from scipy.signal import butter, sosfiltfilt

from neuroscope_eeg.analysis.spectrum import band_power, power_spectrum
from neuroscope_eeg.core.models import EEGEvent, SourceMetadata
from neuroscope_eeg.decoders.base import DecoderResult


def _indices(names: tuple[str, ...], wanted: tuple[str, ...]) -> list[int]:
    lookup = {name.upper(): index for index, name in enumerate(names)}
    return [lookup[name.upper()] for name in wanted if name.upper() in lookup]


def _region_indices(names: tuple[str, ...], prefixes: tuple[str, ...]) -> list[int]:
    return [index for index, name in enumerate(names) if name.upper().startswith(prefixes)]


def _band_db(metadata: SourceMetadata, data: np.ndarray) -> dict[str, np.ndarray]:
    freqs, psd = power_spectrum(data, metadata.sfreq)
    return band_power(freqs, psd)


def _canonical_correlation(x: np.ndarray, y: np.ndarray) -> float:
    x = x.T - np.mean(x, axis=1)
    y = y.T - np.mean(y, axis=1)
    if x.shape[0] < 4:
        return 0.0
    scale = max(1, x.shape[0] - 1)
    cxx = x.T @ x / scale + np.eye(x.shape[1]) * 1e-6
    cyy = y.T @ y / scale + np.eye(y.shape[1]) * 1e-6
    cxy = x.T @ y / scale

    def inv_sqrt(matrix: np.ndarray) -> np.ndarray:
        values, vectors = np.linalg.eigh(matrix)
        return (vectors * (1.0 / np.sqrt(np.maximum(values, 1e-9)))) @ vectors.T

    whitened = inv_sqrt(cxx) @ cxy @ inv_sqrt(cyy)
    return float(np.clip(np.linalg.svd(whitened, compute_uv=False)[0], 0.0, 1.0))


def _filtered(data: np.ndarray, sfreq: float, low_hz: float, high_hz: float) -> np.ndarray:
    nyquist = sfreq / 2.0
    high_hz = min(high_hz, nyquist * 0.95)
    if low_hz >= high_hz or data.shape[1] < 32:
        return data
    sos = butter(4, (low_hz / nyquist, high_hz / nyquist), btype="bandpass", output="sos")
    return sosfiltfilt(sos, data, axis=1)


class SSVEPBaselineDecoder:
    name = "滤波组谐波 CCA"

    def decode(
        self,
        metadata: SourceMetadata,
        data: np.ndarray,
        event: EEGEvent | None = None,
    ) -> DecoderResult:
        targets = (8.0, 10.0, 12.0, 15.0)
        if event and event.payload.get("ssvep_targets"):
            targets = tuple(float(value) for value in event.payload["ssvep_targets"])
        posterior = _region_indices(metadata.channel_names, ("O", "PO"))
        missing: tuple[str, ...] = ()
        if not posterior:
            posterior = list(range(max(0, metadata.n_channels - min(8, metadata.n_channels)), metadata.n_channels))
            missing = ("未识别到枕区通道，暂用末尾通道",)
        selected = np.asarray(data[posterior], dtype=float)
        t = np.arange(selected.shape[1]) / metadata.sfreq
        scores: dict[float, float] = {}
        filter_lows = (6.0, 14.0, 22.0)
        for target in targets:
            refs = []
            for harmonic in range(1, 4):
                frequency = target * harmonic
                if frequency >= metadata.sfreq / 2.0:
                    break
                refs.extend((np.sin(2 * np.pi * frequency * t), np.cos(2 * np.pi * frequency * t)))
            reference = np.asarray(refs)
            sub_scores = []
            for index, low_hz in enumerate(filter_lows):
                filtered = _filtered(selected, metadata.sfreq, low_hz, 45.0)
                sub_scores.append(_canonical_correlation(filtered, reference) ** 2 / ((index + 1) ** 1.25))
            scores[target] = float(np.sum(sub_scores))
        ordered = sorted(scores.items(), key=lambda item: item[1], reverse=True)
        best_frequency, best_score = ordered[0]
        second_score = ordered[1][1] if len(ordered) > 1 else 0.0
        confidence = np.clip((best_score - second_score) / max(best_score, 1e-9), 0.0, 1.0)
        metrics = {f"{frequency:g} Hz 得分": score for frequency, score in scores.items()}
        return DecoderResult(
            value=f"{best_frequency:g} Hz",
            confidence=float(confidence),
            detail="无需训练；候选频率越完整，结果越可靠。",
            metrics=metrics,
            missing=missing,
        )


class MotorImageryBaselineDecoder:
    name = "感觉运动区 µ/β 侧化"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        left = _indices(metadata.channel_names, ("C3",))
        right = _indices(metadata.channel_names, ("C4",))
        if not left or not right:
            return DecoderResult(
                value="尚未解码",
                confidence=0.0,
                detail="需要左右感觉运动区成对通道。",
                missing=("C3", "C4"),
            )
        bands = _band_db(metadata, data)
        left_power = float(np.mean(bands["alpha"][left] + bands["beta"][left])) / 2.0
        right_power = float(np.mean(bands["alpha"][right] + bands["beta"][right])) / 2.0
        lateralization = left_power - right_power
        if abs(lateralization) < 0.6:
            value = "静息 / 不确定"
        else:
            value = "左手想象趋势" if lateralization > 0 else "右手想象趋势"
        return DecoderResult(
            value=value,
            confidence=float(min(0.65, np.tanh(abs(lateralization) / 4.0))),
            detail="未做个人标定，仅用于观察左右侧化趋势。",
            metrics={"C3 µ/β dB": left_power, "C4 µ/β dB": right_power, "侧化指数 dB": lateralization},
        )


class VisualBaselineDecoder:
    name = "枕区视觉响应"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        posterior = _region_indices(metadata.channel_names, ("O", "PO"))
        if not posterior:
            return DecoderResult(
                value="尚未解码",
                confidence=0.0,
                detail="图像类别保留为实验记录；需要枕区通道估计视觉响应。",
                missing=("O1/O2/Oz 或 PO 区通道",),
            )
        bands = _band_db(metadata, data)
        posterior_alpha = float(np.mean(bands["alpha"][posterior]))
        global_alpha = float(np.mean(bands["alpha"]))
        contrast = posterior_alpha - global_alpha
        if contrast >= 3.0:
            value = "视觉响应较强"
        elif contrast >= 0.0:
            value = "视觉响应一般"
        else:
            value = "视觉响应较弱"
        metrics: dict[str, float | str] = {
            "枕区 alpha dB": posterior_alpha,
            "枕区相对响应 dB": contrast,
            "图像类别预测": "尚未解码",
            "目标觉察预测": "需要事件时间对齐",
        }
        return DecoderResult(
            value=value,
            confidence=float(min(0.55, 0.15 + abs(contrast) / 12.0)),
            detail="当前只估计视觉响应；图像类别、目标出现和看见报告属于实验记录。",
            metrics=metrics,
        )


class AttentionBaselineDecoder:
    name = "频段注意力趋势"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        bands = _band_db(metadata, data)
        frontal = _region_indices(metadata.channel_names, ("FP", "F", "FC")) or list(range(metadata.n_channels))
        theta = float(np.mean(10 ** (bands["theta"][frontal] / 10.0)))
        alpha = float(np.mean(10 ** (bands["alpha"][frontal] / 10.0)))
        beta = float(np.mean(10 ** (bands["beta"][frontal] / 10.0)))
        activation = beta / max(theta + alpha, 1e-12)
        score = float(np.clip(50.0 + 28.0 * np.tanh(np.log(max(activation, 1e-12) / 0.55)), 0.0, 100.0))
        return DecoderResult(
            value=f"{score:.0f} / 100",
            confidence=0.45,
            detail="未做个人基线时只适合观察同一会话内的变化。",
            metrics={"注意力趋势分": score, "beta/(theta+alpha)": activation},
        )


class EmotionBaselineDecoder:
    name = "额叶效价 / 唤醒趋势"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        left = _indices(metadata.channel_names, ("F3",))
        right = _indices(metadata.channel_names, ("F4",))
        if not left or not right:
            return DecoderResult(
                value="尚未解码",
                confidence=0.0,
                detail="效价趋势需要左右额区成对通道。",
                missing=("F3", "F4"),
            )
        bands = _band_db(metadata, data)
        asymmetry = float(np.mean(bands["alpha"][right]) - np.mean(bands["alpha"][left]))
        frontal = left + right
        beta_alpha = float(
            np.mean(10 ** (bands["beta"][frontal] / 10.0))
            / max(float(np.mean(10 ** (bands["alpha"][frontal] / 10.0))), 1e-12)
        )
        valence = "正向倾向" if asymmetry >= 0 else "负向倾向"
        arousal = "较高唤醒" if beta_alpha >= 0.6 else "较低唤醒"
        return DecoderResult(
            value=f"{valence} · {arousal}",
            confidence=float(min(0.5, 0.2 + abs(asymmetry) / 12.0)),
            detail="科研趋势，不用于心理或医疗诊断。",
            metrics={"额叶 alpha 不对称 dB": asymmetry, "beta/alpha": beta_alpha},
        )


BASELINE_DECODERS: Mapping[str, object] = {
    "SSVEP": SSVEPBaselineDecoder(),
    "运动想象": MotorImageryBaselineDecoder(),
    "视觉图像识别": VisualBaselineDecoder(),
    "注意力": AttentionBaselineDecoder(),
    "情绪分类": EmotionBaselineDecoder(),
}
