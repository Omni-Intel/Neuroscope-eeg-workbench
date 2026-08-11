from __future__ import annotations

from collections.abc import Mapping

import numpy as np
from scipy.signal import butter, sosfiltfilt

from neuroscope_eeg.analysis.spectrum import band_power, power_spectrum, ssvep_snr
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
        filtered_bands = [_filtered(selected, metadata.sfreq, low_hz, 45.0) for low_hz in filter_lows]
        for target in targets:
            refs = []
            for harmonic in range(1, 4):
                frequency = target * harmonic
                if frequency >= metadata.sfreq / 2.0:
                    break
                refs.extend((np.sin(2 * np.pi * frequency * t), np.cos(2 * np.pi * frequency * t)))
            reference = np.asarray(refs)
            sub_scores = []
            for index, filtered in enumerate(filtered_bands):
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
            detail="候选分离度来自第一、第二 CCA 得分差，不是准确率；正式评估需使用带目标标签的试次。",
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
            detail="由 beta/(theta+alpha) 映射得到的会话内趋势分，不是注意力准确率。",
            metrics={"注意力趋势分": score, "beta/(theta+alpha)": activation},
        )


class EmotionBaselineDecoder:
    name = "Fp1/Fp2 alpha 偏侧趋势"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        left = _indices(metadata.channel_names, ("Fp1",))
        right = _indices(metadata.channel_names, ("Fp2",))
        if not left or not right:
            return DecoderResult(
                value="尚未解码",
                confidence=0.0,
                detail="情绪图片 alpha 偏侧趋势需要 Fp1/Fp2 成对通道。",
                metrics={"有效数据秒数": data.shape[1] / metadata.sfreq},
                missing=("Fp1", "Fp2"),
            )
        bands = _band_db(metadata, data)
        left_alpha_db = float(np.mean(bands["alpha"][left]))
        right_alpha_db = float(np.mean(bands["alpha"][right]))
        asymmetry = float(np.log(10.0) / 10.0 * (right_alpha_db - left_alpha_db))
        frontal = left + right
        beta_alpha = float(
            np.mean(10 ** (bands["beta"][frontal] / 10.0))
            / max(float(np.mean(10 ** (bands["alpha"][frontal] / 10.0))), 1e-12)
        )
        payload = event.payload if event is not None else {}
        fine_category = str(payload.get("fine_category_zh", payload.get("fine_category", "等待图片")))
        metrics: dict[str, float | str] = {
            "Fp1 alpha dB": left_alpha_db,
            "Fp2 alpha dB": right_alpha_db,
            "alpha 偏侧 ln(Fp2)-ln(Fp1)": asymmetry,
            "Fp1/Fp2 beta/alpha": beta_alpha,
            "当前图片类别": fine_category,
            "当前粗效价": str(payload.get("valence", "未设置")),
        }
        if "emotion_baseline_alpha_db" in payload:
            metrics["图片-基线 alpha dB"] = float(np.mean((left_alpha_db, right_alpha_db))) - float(
                payload["emotion_baseline_alpha_db"]
            )
        return DecoderResult(
            value=f"{fine_category}｜alpha 偏侧 {asymmetry:+.2f}",
            confidence=float(min(0.5, 0.2 + abs(asymmetry) / 12.0)),
            detail="公式为 ln(alpha_Fp2)-ln(alpha_Fp1)；只表示会话内伴随趋势，不是七类情绪分类结果。",
            metrics=metrics,
        )


class RestingStateBaselineDecoder:
    name = "前额睁闭眼频带趋势"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        frontal = _indices(metadata.channel_names, ("Fp1", "Fp2", "Fpz"))
        if not frontal:
            return DecoderResult(
                value="尚未解码",
                confidence=0.0,
                detail="前额睁闭眼趋势需要 Fp1/Fp2/Fpz 中至少一个通道。",
                metrics={"有效数据秒数": data.shape[1] / metadata.sfreq},
                missing=("Fp1/Fp2/Fpz",),
            )
        bands = _band_db(metadata, data)
        metrics: dict[str, float | str] = {"有效数据秒数": data.shape[1] / metadata.sfreq}
        for index in frontal:
            channel = metadata.channel_names[index]
            metrics[f"{channel} theta dB"] = float(bands["theta"][index])
            metrics[f"{channel} alpha dB"] = float(bands["alpha"][index])
            metrics[f"{channel} beta dB"] = float(bands["beta"][index])
        alpha_db = float(np.mean(bands["alpha"][frontal]))
        payload = event.payload if event is not None else {}
        eye_state = str(payload.get("eye_state", "等待阶段"))
        metrics["当前阶段"] = eye_state
        metrics["前额 alpha 平均 dB"] = alpha_db
        if "eyes_open_alpha_db" in payload:
            open_alpha = float(payload["eyes_open_alpha_db"])
            metrics["闭眼-睁眼 alpha dB"] = alpha_db - open_alpha
        return DecoderResult(
            value=f"{eye_state}｜前额 alpha {alpha_db:.1f} dB",
            confidence=0.45,
            detail="展示前额 alpha 的会话内睁闭眼相对趋势；经典闭眼 alpha 通常在枕区更强。",
            metrics=metrics,
        )


class NBackBaselineDecoder:
    name = "N-back 三负荷前额频带与行为"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        left = _indices(metadata.channel_names, ("Fp1",))
        right = _indices(metadata.channel_names, ("Fp2",))
        center = _indices(metadata.channel_names, ("Fpz",))
        frontal = left + right + center
        if not frontal:
            return DecoderResult(
                value="尚未解码",
                confidence=0.0,
                detail="N-back 前额频带趋势需要 Fp1/Fp2/Fpz 中至少一个通道。",
                metrics={"有效数据秒数": data.shape[1] / metadata.sfreq},
                missing=("Fp1/Fp2/Fpz",),
            )
        bands = _band_db(metadata, data)
        payload = event.payload if event is not None else {}
        metrics: dict[str, float | str] = {
            "前额 theta 平均 dB": float(np.mean(bands["theta"][frontal])),
            "正式试次": float(payload.get("trials", 0)),
            "总体正确率": float(payload.get("behavior_accuracy", 0.0) or 0.0),
            "平衡正确率": float(payload.get("balanced_accuracy", 0.0) or 0.0),
            "一致正确率": float(payload.get("match_accuracy", 0.0) or 0.0),
            "不一致正确率": float(payload.get("nonmatch_accuracy", 0.0) or 0.0),
            "遗漏": float(payload.get("omissions", 0)),
            "d-prime": float(payload.get("d_prime", 0.0) or 0.0),
            "一致中位反应时 ms": float(payload.get("match_median_response_time_ms", 0.0) or 0.0),
            "不一致中位反应时 ms": float(payload.get("nonmatch_median_response_time_ms", 0.0) or 0.0),
        }
        if "nback_baseline_theta_db" in payload:
            metrics["任务-基线 theta dB"] = float(metrics["前额 theta 平均 dB"]) - float(
                payload["nback_baseline_theta_db"]
            )
        for index in frontal:
            metrics[f"{metadata.channel_names[index]} theta dB"] = float(bands["theta"][index])
        if left and right:
            metrics["Fp1-Fp2 theta 偏侧 dB"] = float(bands["theta"][left[0]] - bands["theta"][right[0]])
        load_theta = [payload.get(f"nback_{level}_theta_db") for level in (0, 1, 2)]
        for level in (0, 1, 2):
            for band in ("theta", "alpha", "beta"):
                key = f"nback_{level}_{band}_db"
                if key in payload:
                    metrics[f"{level}-back {band} dB"] = float(payload[key])
            accuracy_key = f"nback_{level}_behavior_accuracy"
            if accuracy_key in payload:
                metrics[f"{level}-back 正确率"] = float(payload[accuracy_key] or 0.0)
        if all(value is not None for value in load_theta):
            metrics["1-back - 0-back theta dB"] = float(load_theta[1]) - float(load_theta[0])
            metrics["2-back - 0-back theta dB"] = float(load_theta[2]) - float(load_theta[0])
            value = "theta 0/1/2-back " + "/".join(f"{float(item):.1f}" for item in load_theta) + " dB"
            detail = "按 block 汇总 0/1/2-back 会话内前额频带趋势；不预设负荷效应必须严格单调。"
        else:
            value = f"前额 theta {metrics['前额 theta 平均 dB']:.1f} dB"
            detail = "正在积累分 block 的 0/1/2-back 负荷数据；固定 J/F 映射的偏侧结果仅作探索。"
        return DecoderResult(
            value=value,
            confidence=0.45,
            detail=detail,
            metrics=metrics,
        )


class StroopBaselineDecoder:
    name = "Stroop 前额 theta/beta 与行为"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        frontal = _indices(metadata.channel_names, ("Fp1", "Fp2", "Fpz"))
        if not frontal:
            return DecoderResult(
                value="尚未解码",
                confidence=0.0,
                detail="Stroop 前额频带趋势需要 Fp1/Fp2/Fpz 中至少一个通道。",
                metrics={"ERP 状态": "时序待校准"},
                missing=("Fp1/Fp2/Fpz",),
            )
        bands = _band_db(metadata, data)
        payload = event.payload if event is not None else {}
        timing_status = str(payload.get("timing_status", "software_sync_uncalibrated"))
        metrics: dict[str, float | str] = {
            "前额 theta 平均 dB": float(np.mean(bands["theta"][frontal])),
            "前额 beta 平均 dB": float(np.mean(bands["beta"][frontal])),
            "正式试次": float(payload.get("trials", 0)),
            "总体正确率": float(payload.get("behavior_accuracy", 0.0) or 0.0),
            "平衡正确率": float(payload.get("balanced_accuracy", 0.0) or 0.0),
            "Stroop 反应时干扰 ms": float(payload.get("stroop_interference_ms", 0.0) or 0.0),
            "Stroop 正确率代价": float(payload.get("stroop_accuracy_cost", 0.0) or 0.0),
            "一致条件正确率": float(payload.get("congruent_accuracy", 0.0) or 0.0),
            "不一致条件正确率": float(payload.get("incongruent_accuracy", 0.0) or 0.0),
            "一致中位反应时 ms": float(payload.get("congruent_median_response_time_ms", 0.0) or 0.0),
            "不一致中位反应时 ms": float(payload.get("incongruent_median_response_time_ms", 0.0) or 0.0),
            "ERP 状态": "已校准" if timing_status == "calibrated" else "时序待校准",
        }
        for index in frontal:
            metrics[f"{metadata.channel_names[index]} theta dB"] = float(bands["theta"][index])
        return DecoderResult(
            value=f"前额 θ/β {metrics['前额 theta 平均 dB']:.1f}/{metrics['前额 beta 平均 dB']:.1f} dB",
            confidence=0.45,
            detail="行为与连续频带趋势可立即展示；J/F 固定映射混入左右手效应，Fpz N2 类趋势需完成显示到 EEG 时序校准。",
            metrics=metrics,
        )


class AuditoryASSRBaselineDecoder:
    name = "40 Hz 听觉频率跟随"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        selected = _indices(metadata.channel_names, ("T3", "T4", "T7", "T8"))
        missing: tuple[str, ...] = ()
        if not selected:
            selected = list(range(metadata.n_channels))
            missing = ("未识别到 T3/T4 或 T7/T8，暂用全部可用通道",)
        duration_sec = data.shape[1] / metadata.sfreq
        if metadata.sfreq < 100.0 or duration_sec < 5.0:
            return DecoderResult(
                value="尚未解码",
                confidence=0.0,
                detail="40 Hz ASSR 需要至少 100 Hz 采样率和 5 秒有效刺激数据。",
                metrics={"有效数据秒数": duration_sec, "采样率 Hz": metadata.sfreq},
                missing=missing,
            )

        freqs, psd = power_spectrum(np.asarray(data[selected], dtype=np.float32), metadata.sfreq)
        ratio = ssvep_snr(freqs, psd, (40.0,))[40.0]
        snr_db = float(10.0 * np.log10(max(ratio, 1e-12)))
        center = int(np.argmin(np.abs(freqs - 40.0)))
        channel_power_db = 10.0 * np.log10(psd[:, center] + 1e-12)
        if snr_db >= 8.0:
            value = "40 Hz 频率跟随明显"
        elif snr_db >= 3.0:
            value = "40 Hz 频率跟随可见"
        else:
            value = "40 Hz 频率跟随尚不明显"

        metrics: dict[str, float | str] = {
            "40 Hz SNR dB": snr_db,
            "40 Hz 平均功率 dB": float(np.mean(channel_power_db)),
            "有效数据秒数": duration_sec,
        }
        for index, channel_index in enumerate(selected):
            metrics[f"{metadata.channel_names[channel_index]} 40 Hz dB"] = float(channel_power_db[index])
        return DecoderResult(
            value=value,
            confidence=float(np.clip((snr_db + 1.0) / 12.0, 0.0, 0.8)),
            detail="频谱信噪比用于观察听觉频率跟随趋势，不是听力或临床诊断。",
            metrics=metrics,
            missing=missing,
        )


class AuditoryOddballBaselineDecoder:
    name = "听觉偏差响应"

    def decode(self, metadata: SourceMetadata, data: np.ndarray, event: EEGEvent | None = None) -> DecoderResult:
        payload = event.payload if event is not None else {}
        trials = int(payload.get("trials", 0))
        targets = int(payload.get("targets", 0))
        hits = int(payload.get("hits", 0))
        false_alarms = int(payload.get("false_alarms", 0))
        non_targets = max(0, trials - targets)
        hit_rate = hits / targets if targets else 0.0
        false_alarm_rate = false_alarms / non_targets if non_targets else 0.0
        timing_status = str(payload.get("timing_status", "software_sync_uncalibrated"))
        metrics: dict[str, float | str] = {
            "已呈现试次": float(trials),
            "偏差音数量": float(targets),
            "行为命中率": float(hit_rate),
            "漏报": float(payload.get("misses", max(0, targets - hits))),
            "漏报率": float(payload.get("miss_rate", 1.0 - hit_rate if targets else 0.0)),
            "误报": float(false_alarms),
            "误报率": float(false_alarm_rate),
            "d-prime": float(payload.get("d_prime", 0.0) or 0.0),
            "正确命中中位反应时 ms": float(payload.get("median_response_time_ms", 0.0) or 0.0),
            "同步状态": "已校准" if timing_status == "calibrated" else "待真机校准",
        }
        missing_items: list[str] = []
        if not _indices(metadata.channel_names, ("Fpz",)):
            missing_items.append("Fpz")
        if not _indices(metadata.channel_names, ("T3", "T7")):
            missing_items.append("T3/T7")
        if not _indices(metadata.channel_names, ("T4", "T8")):
            missing_items.append("T4/T8")
        return DecoderResult(
            value="ERP 时序待校准",
            confidence=0.0,
            detail="当前为主动 Oddball：可探索 T3/T4 的 N1/MMN 类趋势与 Fpz 靶音晚期正波；软件事件标记已记录，需完成音频到 EEG 时序校准。",
            metrics=metrics,
            missing=tuple(missing_items),
        )


BASELINE_DECODERS: Mapping[str, object] = {
    "SSVEP": SSVEPBaselineDecoder(),
    "运动想象": MotorImageryBaselineDecoder(),
    "视觉图像识别": VisualBaselineDecoder(),
    "注意力": AttentionBaselineDecoder(),
    "静息睁眼/闭眼": RestingStateBaselineDecoder(),
    "N-back 工作记忆": NBackBaselineDecoder(),
    "Stroop 色词冲突": StroopBaselineDecoder(),
    "情绪分类": EmotionBaselineDecoder(),
    "情绪图片唤醒": EmotionBaselineDecoder(),
    "听觉 ASSR": AuditoryASSRBaselineDecoder(),
    "听觉 Oddball": AuditoryOddballBaselineDecoder(),
}
