from __future__ import annotations

import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np
import streamlit as st

from neuroscope_eeg.acquisition.replay import NPZReplaySource
from neuroscope_eeg.acquisition.legacy import build_brainco_source, build_neuracle_source
from neuroscope_eeg.acquisition.simulated import SimulatedSource
from neuroscope_eeg.analysis.quality import signal_quality
from neuroscope_eeg.analysis.spectrum import power_spectrum
from neuroscope_eeg.core.models import EEGEvent
from neuroscope_eeg.core.session import SessionController
from neuroscope_eeg.io.diagnostic_bundle import create_diagnostic_bundle
from neuroscope_eeg.paradigms.base import PARADIGMS
from neuroscope_eeg.preprocessing.basic import brainco_display_preprocess, robust_channel_scale


SOURCE_OPTIONS = ("模拟", "NPZ 回放", "博睿康 Neuracle", "强脑 BrainCo")
PARADIGM_OPTIONS = tuple(PARADIGMS.keys())

plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "PingFang SC", "DejaVu Sans"]
plt.rcParams["axes.unicode_minus"] = False


def _session_key(
    source_label: str,
    sfreq: float,
    n_channels: int,
    replay_path: str,
    oi_mi_path: str,
    host: str,
    port: int,
    brainco_addr: str,
    brainco_port: int,
    brainco_auto: bool,
) -> str:
    return "|".join(
        str(item)
        for item in (
            source_label,
            sfreq,
            n_channels,
            replay_path,
            oi_mi_path,
            host,
            port,
            brainco_addr,
            brainco_port,
            brainco_auto,
        )
    )


def _build_source(
    source_label: str,
    sfreq: float,
    n_channels: int,
    replay_path: str,
    oi_mi_path: str,
    host: str,
    port: int,
    brainco_addr: str,
    brainco_port: int,
    brainco_auto: bool,
):
    if source_label == "NPZ 回放":
        if not replay_path.strip():
            raise ValueError("请先填写 NPZ 回放文件路径")
        return NPZReplaySource(Path(replay_path).expanduser())
    if source_label == "博睿康 Neuracle":
        return build_neuracle_source(oi_mi_path, host, port, sfreq, n_channels)
    if source_label == "强脑 BrainCo":
        return build_brainco_source(sfreq, min(n_channels, 32), brainco_addr, brainco_port, brainco_auto)
    channels = (
        ("Fp1", "Fp2", "Fpz", "T3", "T4")
        if n_channels == 5
        else tuple(SimulatedSource().metadata.channel_names[:n_channels])
    )
    return SimulatedSource(sfreq=sfreq, channel_names=channels)


def _stop_session() -> None:
    controller = st.session_state.get("controller")
    if controller is not None:
        controller.stop()
    st.session_state.controller = None
    st.session_state.session_key = ""


def _draw_timeseries(
    data: np.ndarray,
    names: tuple[str, ...],
    sfreq: float,
    *,
    independent_scale: bool = False,
) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(11, 4))
    n_show = min(12, data.shape[0])
    shown = data[:n_show]
    centered = shown - np.mean(shown, axis=1, keepdims=True)
    plotted = robust_channel_scale(centered) if independent_scale else centered
    scale = 1.0 if independent_scale else max(float(np.percentile(np.abs(centered), 95)), 1.0)
    t = np.arange(shown.shape[1]) / sfreq - shown.shape[1] / sfreq
    offsets = np.arange(n_show)[::-1] * 4.0
    for idx in range(n_show):
        ax.plot(t, plotted[idx] / scale + offsets[idx], lw=0.8)
    ax.set_yticks(offsets)
    ax.set_yticklabels(names[:n_show], fontsize=8)
    ax.set_xlabel("seconds from now")
    title = "实时 EEG（逐通道独立缩放）" if independent_scale else "实时 EEG"
    ax.set_title(title)
    ax.grid(alpha=0.2)
    return fig


def _draw_spectrum(data: np.ndarray, sfreq: float) -> plt.Figure:
    freqs, psd = power_spectrum(data, sfreq)
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.plot(freqs, 10.0 * np.log10(np.mean(psd, axis=0) + 1e-12), color="#2563eb")
    ax.set_xlabel("Hz")
    ax.set_ylabel("mean power dB")
    ax.set_title("频谱")
    ax.grid(alpha=0.2)
    return fig


def _draw_quality_bars(rms: np.ndarray, names: tuple[str, ...], *, brainco_filtered: bool = False) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.bar(names[: len(rms)], rms, color="#0f766e")
    ax.set_ylabel("RMS uV")
    title = "通道质量（BrainCo 去漂移及带通后）" if brainco_filtered else "通道质量"
    ax.set_title(title)
    ax.tick_params(axis="x", labelrotation=90, labelsize=7)
    ax.grid(axis="y", alpha=0.2)
    return fig


def _parse_frequencies(value: str) -> tuple[float, ...]:
    frequencies = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if not frequencies or any(frequency <= 0 for frequency in frequencies):
        raise ValueError("刺激频率必须是用逗号分隔的正数")
    return frequencies


def _event_from_sidebar(
    target_present: bool,
    seen_reported: bool,
    image_category: str,
    ssvep_targets: tuple[float, ...],
) -> EEGEvent:
    return EEGEvent(
        timestamp=time.time(),
        name="visual_trial",
        code=image_category,
        payload={
            "image_category": image_category,
            "target_present": target_present,
            "seen_reported": seen_reported,
            "ssvep_targets": ssvep_targets,
        },
    )


def main() -> None:
    st.set_page_config(page_title="NeuroScope｜多范式脑电可视化工作台", layout="wide")
    st.session_state.setdefault("controller", None)
    st.session_state.setdefault("session_key", "")

    with st.sidebar:
        st.title("NeuroScope")
        st.caption("多范式脑电可视化工作台")
        source_label = st.selectbox("数据源", SOURCE_OPTIONS, index=0)
        paradigm_label = st.selectbox("任务范式", PARADIGM_OPTIONS, index=0)
        default_sfreq = 1000.0 if source_label == "博睿康 Neuracle" else 250.0
        default_channels = 64 if source_label == "博睿康 Neuracle" else 32
        sfreq = st.number_input("采样率 Hz", min_value=1.0, max_value=5000.0, value=default_sfreq, step=50.0)
        n_channels = st.number_input("通道数", min_value=1, max_value=64, value=default_channels, step=1)
        replay_path = st.text_input("NPZ 回放文件", value="")
        oi_mi_path = ""
        host = "127.0.0.1"
        port = 8712
        brainco_addr = ""
        brainco_port = 0
        brainco_auto = True
        if source_label == "博睿康 Neuracle":
            oi_mi_path = st.text_input("oi-mi 路径", value="", help="填写采集电脑上的博睿康采集接口目录")
            host = st.text_input("JellyFish host", value="127.0.0.1")
            port = int(st.number_input("JellyFish port", min_value=1, max_value=65535, value=8712, step=1))
        if source_label == "强脑 BrainCo":
            brainco_auto = st.checkbox("自动发现 BrainCo", value=True)
            brainco_addr = st.text_input("BrainCo IP", value="")
            brainco_port = int(st.number_input("BrainCo port", min_value=0, max_value=65535, value=0, step=1))
        st.divider()
        ssvep_targets_text = "8,10,12,15"
        if paradigm_label == "SSVEP":
            ssvep_targets_text = st.text_input("刺激频率 Hz", value=ssvep_targets_text)
        image_category = "未设置"
        target_present = False
        seen_reported = False
        if paradigm_label == "视觉图像识别":
            st.caption("实验记录")
            image_category = st.text_input("受试者正在观看的图像类别", value="face")
            target_present = st.checkbox("目标实际出现", value=True)
            seen_reported = st.checkbox("受试者报告看见", value=False)
        st.divider()
        start = st.button("启动", type="primary", width="stretch")
        stop = st.button("停止", width="stretch")
        make_bundle = st.button("生成诊断包", width="stretch")

    if stop:
        _stop_session()
        st.rerun()

    if make_bundle:
        bundle = create_diagnostic_bundle(Path("diagnostics/neuroscope-diagnostic.zip"))
        st.sidebar.success(f"已生成 {bundle}")

    config_key = _session_key(
        source_label,
        sfreq,
        int(n_channels),
        replay_path,
        oi_mi_path,
        host,
        port,
        brainco_addr,
        brainco_port,
        brainco_auto,
    )
    if start:
        _stop_session()
        try:
            source = _build_source(
                source_label,
                float(sfreq),
                int(n_channels),
                replay_path,
                oi_mi_path,
                host,
                port,
                brainco_addr,
                brainco_port,
                brainco_auto,
            )
            controller = SessionController(source)
            controller.start()
            st.session_state.controller = controller
            st.session_state.session_key = config_key
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.sidebar.error(str(exc))

    controller: SessionController | None = st.session_state.get("controller")
    running = controller is not None
    if running and st.session_state.session_key != config_key:
        st.warning("左侧参数已改变。请先停止，再启动。")

    top = st.container()
    with top:
        cols = st.columns(5)
        cols[0].metric("状态", controller.state.value if controller else "idle")
        cols[1].metric("数据源", controller.source.metadata.source_type if controller else source_label)
        cols[2].metric("范式", paradigm_label)
        cols[3].metric("采样率", f"{controller.source.metadata.sfreq:g} Hz" if controller else f"{sfreq:g} Hz")
        cols[4].metric("运行时间", f"{controller.elapsed_sec():.1f}s" if controller else "0.0s")

    if controller and controller.error:
        st.error(controller.error)
        if controller.source.metadata.source_type == "brainco":
            return

    if not controller:
        st.info("先用模拟源确认页面正常；在采集电脑上可直接选择博睿康或强脑启动真机采集。")
        return

    snapshot = controller.buffer.latest(4.0)
    if snapshot is None:
        if controller.source.metadata.source_type == "brainco":
            expected_samples = int(round(4.0 * controller.source.metadata.sfreq))
            buffered_samples = controller.buffer.sample_count()
            st.info(f"正在接收 BrainCo 数据：已缓冲 {buffered_samples} / {expected_samples} 个样本")
            age = controller.last_data_age_sec()
            if age is None:
                st.caption("尚未收到第一个非空数据块。")
            else:
                st.caption(f"最近数据：{age:.1f} 秒前；累计接收：{controller.samples_received} 个样本")
        else:
            st.info("等待足够数据...")
        time.sleep(0.4 if controller.source.metadata.source_type == "brainco" else 0.5)
        st.rerun()
        return

    data, _timestamps = snapshot
    metadata = controller.source.metadata
    is_brainco = metadata.source_type == "brainco"
    analysis_data = brainco_display_preprocess(data, metadata.sfreq) if is_brainco else data
    try:
        ssvep_targets = _parse_frequencies(ssvep_targets_text)
    except ValueError as exc:
        st.error(str(exc))
        return
    event = _event_from_sidebar(target_present, seen_reported, image_category, ssvep_targets)
    quality = signal_quality(analysis_data, metadata.channel_names, int(round(4.0 * metadata.sfreq)))
    paradigm = PARADIGMS[paradigm_label]
    result = paradigm.analyze(metadata, analysis_data, (event,))

    tab_monitor, tab_quality, tab_paradigm, tab_record = st.tabs(("实时监控", "信号质量", "范式分析", "记录"))
    with tab_monitor:
        if is_brainco:
            live_cols = st.columns(3)
            live_cols[0].metric("累计样本", controller.samples_received)
            live_cols[1].metric("数据块", controller.chunks_received)
            age = controller.last_data_age_sec()
            live_cols[2].metric("最近数据", "尚未收到" if age is None else f"{age:.1f} 秒前")
            if age is not None and age > 2.0:
                st.warning("BrainCo 已超过 2 秒没有新数据，当前图形可能已经停止更新。")
            st.caption("BrainCo 显示已去漂移并限制在 1–45 Hz；每个通道独立缩放，幅度大小请以信号质量页为准。")
        st.pyplot(
            _draw_timeseries(analysis_data, metadata.channel_names, metadata.sfreq, independent_scale=is_brainco),
            width="stretch",
        )
        st.pyplot(_draw_spectrum(analysis_data, metadata.sfreq), width="stretch")
    with tab_quality:
        cols = st.columns(4)
        cols[0].metric("整体质量", quality.overall)
        cols[1].metric("平直通道", len(quality.flat_channels))
        cols[2].metric("噪声通道", len(quality.noisy_channels))
        cols[3].metric("疑似削顶", len(quality.clipped_channels))
        if is_brainco:
            st.caption("BrainCo 质量指标基于去漂移和 1–45 Hz 带通后的信号。")
        st.pyplot(
            _draw_quality_bars(quality.rms_uv, metadata.channel_names, brainco_filtered=is_brainco),
            width="stretch",
        )
        if quality.flat_channels or quality.noisy_channels or quality.clipped_channels:
            st.write(
                {
                    "flat": quality.flat_channels,
                    "noisy": quality.noisy_channels,
                    "clipped": quality.clipped_channels,
                }
            )
    with tab_paradigm:
        st.caption(f"Decoder：{result.decoder_name}")
        result_cols = st.columns(3)
        if quality.overall == "good":
            result_cols[0].metric("即时结果", result.headline)
            result_cols[1].metric("结果来源", result.source)
            result_cols[2].metric("基线置信度", f"{result.confidence:.0%}")
        else:
            result_cols[0].metric("即时结果", "信号质量不足")
            result_cols[1].metric("结果来源", "尚未解码")
            result_cols[2].metric("基线置信度", "0%")
        st.caption(result.detail)
        st.warning("未标定，仅供快速观察。正式分类需要在采集电脑上用带标签数据校准。")
        if result.missing:
            st.info("；".join(result.missing))
        metrics = result.metrics
        if metrics:
            metric_cols = st.columns(min(4, len(metrics)))
            for idx, (name, value) in enumerate(metrics.items()):
                metric_cols[idx % len(metric_cols)].metric(name, f"{value:.3g}" if isinstance(value, float) else str(value))
        if paradigm_label == "视觉图像识别":
            st.divider()
            st.subheader("实验记录（不是 Decoder 预测）")
            record_cols = st.columns(3)
            record_cols[0].metric("正在观看的图像类别", image_category)
            record_cols[1].metric("目标实际出现", "是" if target_present else "否")
            record_cols[2].metric("受试者报告看见", "是" if seen_reported else "否")
    with tab_record:
        st.write(
            {
                "source_id": metadata.source_id,
                "channels": metadata.channel_names,
                "visual_event": dict(event.payload),
                "samples_buffered": controller.buffer.sample_count(),
                "samples_received": controller.samples_received,
                "chunks_received": controller.chunks_received,
                "last_data_age_sec": controller.last_data_age_sec(),
            }
        )

    time.sleep(0.4 if is_brainco else 0.8)
    st.rerun()


if __name__ == "__main__":
    main()
