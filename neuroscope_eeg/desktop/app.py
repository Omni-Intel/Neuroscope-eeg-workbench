from __future__ import annotations

import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QCloseEvent, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from neuroscope_eeg.acquisition.legacy import build_brainco_source, build_neuracle_source
from neuroscope_eeg.acquisition.replay import NPZReplaySource
from neuroscope_eeg.acquisition.simulated import SimulatedSource
from neuroscope_eeg.analysis.quality import QualityReport, signal_quality
from neuroscope_eeg.analysis.spectrum import power_spectrum
from neuroscope_eeg.core.models import ConnectionState, EEGEvent
from neuroscope_eeg.core.session import SessionController
from neuroscope_eeg.desktop.performance import FpsTracker, fps_level, timer_interval_ms
from neuroscope_eeg.desktop.protocols import StimulusEvent, frame_locked_frequencies
from neuroscope_eeg.desktop.stimulus import StimulusWindow
from neuroscope_eeg.paradigms.base import PARADIGMS, ParadigmResult
from neuroscope_eeg.preprocessing.basic import brainco_display_preprocess, robust_channel_scale


MAX_VISIBLE_CHANNELS = 32
WAVE_WINDOW_SEC = 4.0
SOURCE_OPTIONS = ("模拟", "NPZ 回放", "博睿康 Neuracle", "强脑 BrainCo")
PLOT_COLORS = ("#38bdf8", "#f59e0b", "#34d399", "#fb7185", "#a78bfa", "#22d3ee")


class NeuroScopeWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("NeuroScope｜多范式脑电可视化工作台")
        self.resize(1500, 920)
        self.controller: SessionController | None = None
        self._analysis_data: np.ndarray | None = None
        self._fps = FpsTracker()
        self._run_started_at: float | None = None
        self.stimulus_window = StimulusWindow()
        self.stimulus_window.event_emitted.connect(self._on_stimulus_event)
        self.stimulus_window.stopped.connect(self._stimulus_stopped)
        self.stimulus_events: list[StimulusEvent] = []
        self._last_decoder_value = ""
        self._ssvep_checked_trials: set[int] = set()
        self._ssvep_trial_hits = 0
        self._wave_layout_key: tuple[tuple[str, ...], float] | None = None

        self._build_ui()
        self._build_timers()
        self._source_changed()
        self._paradigm_changed()
        self._update_status()

    def _build_ui(self) -> None:
        root = QWidget()
        layout = QHBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)
        layout.addWidget(self._build_controls(), 0)
        layout.addWidget(self._build_workspace(), 1)
        self.setCentralWidget(root)

    def _build_controls(self) -> QWidget:
        panel = QWidget()
        panel.setFixedWidth(300)
        layout = QVBoxLayout(panel)
        title = QLabel("NeuroScope")
        title.setObjectName("appTitle")
        subtitle = QLabel("多范式脑电可视化工作台")
        subtitle.setObjectName("muted")
        layout.addWidget(title)
        layout.addWidget(subtitle)

        general = QGroupBox("采集设置")
        form = QFormLayout(general)
        self.source_select = QComboBox()
        self.source_select.addItems(SOURCE_OPTIONS)
        self.source_select.currentTextChanged.connect(self._source_changed)
        self.paradigm_select = QComboBox()
        self.paradigm_select.addItems(PARADIGMS.keys())
        self.paradigm_select.currentTextChanged.connect(self._paradigm_changed)
        self.sfreq = QSpinBox()
        self.sfreq.setRange(1, 5000)
        self.sfreq.setValue(250)
        self.channels = QSpinBox()
        self.channels.setRange(1, 64)
        self.channels.setValue(32)
        self.target_fps = QComboBox()
        for fps in (20, 30, 60):
            self.target_fps.addItem(f"{fps} FPS", fps)
        self.target_fps.setCurrentIndex(1)
        self.target_fps.currentIndexChanged.connect(self._refresh_rate_changed)
        form.addRow("数据源", self.source_select)
        form.addRow("任务范式", self.paradigm_select)
        form.addRow("采样率 Hz", self.sfreq)
        form.addRow("通道数", self.channels)
        form.addRow("画面刷新", self.target_fps)
        layout.addWidget(general)

        self.replay_group = QGroupBox("NPZ 回放")
        replay_layout = QHBoxLayout(self.replay_group)
        self.replay_path = QLineEdit()
        replay_browse = QPushButton("选择")
        replay_browse.clicked.connect(self._browse_replay)
        replay_layout.addWidget(self.replay_path)
        replay_layout.addWidget(replay_browse)
        layout.addWidget(self.replay_group)

        self.device_group = QGroupBox("真机公共设置")
        device_form = QFormLayout(self.device_group)
        self.oi_mi_path = QLineEdit()
        self.oi_mi_path.setPlaceholderText("采集电脑上的 oi-mi 目录")
        device_form.addRow("oi-mi 路径", self.oi_mi_path)
        layout.addWidget(self.device_group)

        self.neuracle_group = QGroupBox("博睿康 Neuracle")
        neuracle_form = QFormLayout(self.neuracle_group)
        self.neuracle_host = QLineEdit("127.0.0.1")
        self.neuracle_port = QSpinBox()
        self.neuracle_port.setRange(1, 65535)
        self.neuracle_port.setValue(8712)
        neuracle_form.addRow("JellyFish IP", self.neuracle_host)
        neuracle_form.addRow("端口", self.neuracle_port)
        layout.addWidget(self.neuracle_group)

        self.brainco_group = QGroupBox("强脑 BrainCo")
        brainco_form = QFormLayout(self.brainco_group)
        self.brainco_auto = QCheckBox("自动发现（推荐）")
        self.brainco_auto.setChecked(True)
        self.brainco_auto.toggled.connect(self._brainco_auto_changed)
        self.brainco_ip = QLineEdit()
        self.brainco_ip.setPlaceholderText("自动发现时留空")
        self.brainco_port = QSpinBox()
        self.brainco_port.setRange(0, 65535)
        brainco_form.addRow(self.brainco_auto)
        brainco_form.addRow("设备 IP", self.brainco_ip)
        brainco_form.addRow("端口", self.brainco_port)
        layout.addWidget(self.brainco_group)

        paradigm = QGroupBox("范式参数")
        paradigm_form = QFormLayout(paradigm)
        self.paradigm_form = paradigm_form
        self.ssvep_targets = QLineEdit("随第二屏刷新率自动生成")
        self.ssvep_targets.setReadOnly(True)
        self.image_category = QLineEdit("内置字母 / 数字 / 图形")
        self.image_category.setReadOnly(True)
        self.mi_protocol = QLabel("左手 / 右手 / 静息｜2s 注视 + 1s 提示 + 4s 想象 + 2s 休息")
        self.mi_protocol.setWordWrap(True)
        self.visual_protocol = QLabel("RSVP 4 项/秒｜看到 ★ 按空格｜目标概率 20%")
        self.visual_protocol.setWordWrap(True)
        self.attention_protocol = QLabel("8s 静息 + 30s 连续心算｜输入答案后回车")
        self.attention_protocol.setWordWrap(True)
        self.emotion_protocol = QLabel("正向 / 负向 / 中性文字情境｜按 1–9 评价强度")
        self.emotion_protocol.setWordWrap(True)
        paradigm_form.addRow("SSVEP 频率", self.ssvep_targets)
        paradigm_form.addRow("图像类别", self.image_category)
        paradigm_form.addRow("运动想象", self.mi_protocol)
        paradigm_form.addRow("视觉任务", self.visual_protocol)
        paradigm_form.addRow("注意力任务", self.attention_protocol)
        paradigm_form.addRow("情绪任务", self.emotion_protocol)
        self.paradigm_group = paradigm
        layout.addWidget(paradigm)

        stimulus = QGroupBox("第二屏刺激（软件同步）")
        stimulus_layout = QVBoxLayout(stimulus)
        self.display_select = QComboBox()
        self._populate_displays()
        stimulus_buttons = QHBoxLayout()
        self.stimulus_start_button = QPushButton("开始刺激")
        self.stimulus_start_button.clicked.connect(self._start_stimulus)
        self.stimulus_stop_button = QPushButton("停止刺激")
        self.stimulus_stop_button.clicked.connect(self._stop_stimulus)
        stimulus_buttons.addWidget(self.stimulus_start_button)
        stimulus_buttons.addWidget(self.stimulus_stop_button)
        self.stimulus_status = QLabel("未开始")
        self.stimulus_status.setWordWrap(True)
        self.stimulus_status.setObjectName("muted")
        self.export_events_button = QPushButton("导出事件 CSV")
        self.export_events_button.clicked.connect(self._export_events)
        stimulus_layout.addWidget(self.display_select)
        stimulus_layout.addLayout(stimulus_buttons)
        stimulus_layout.addWidget(self.stimulus_status)
        stimulus_layout.addWidget(self.export_events_button)
        layout.addWidget(stimulus)

        buttons = QHBoxLayout()
        self.start_button = QPushButton("启动")
        self.start_button.setObjectName("primaryButton")
        self.start_button.clicked.connect(self._start_session)
        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self._stop_session)
        buttons.addWidget(self.start_button)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)
        layout.addStretch(1)
        return panel

    def _build_workspace(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        status = QGridLayout()
        self.state_value = self._status_card(status, 0, "状态", "idle")
        self.source_value = self._status_card(status, 1, "数据源", "模拟")
        self.rate_value = self._status_card(status, 2, "采样率", "250 Hz")
        self.fps_value = self._status_card(status, 3, "刷新率", "目标 30 / 实际 0 FPS")
        self.data_value = self._status_card(status, 4, "数据新鲜度", "尚未接收")
        layout.addLayout(status)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_live_tab(), "实时监控")
        self.tabs.addTab(self._build_spectrum_tab(), "频谱")
        self.tabs.addTab(self._build_quality_tab(), "信号质量")
        self.tabs.addTab(self._build_paradigm_tab(), "范式分析")
        self.tabs.addTab(self._build_record_tab(), "记录")
        layout.addWidget(self.tabs, 1)
        return panel

    def _status_card(self, layout: QGridLayout, column: int, label: str, value: str) -> QLabel:
        card = QGroupBox(label)
        card_layout = QVBoxLayout(card)
        result = QLabel(value)
        result.setObjectName("statusValue")
        card_layout.addWidget(result)
        layout.addWidget(card, 0, column)
        return result

    def _new_plot(self, title: str, y_label: str = "") -> pg.PlotWidget:
        plot = pg.PlotWidget(title=title)
        plot.showGrid(x=True, y=True, alpha=0.18)
        if y_label:
            plot.setLabel("left", y_label)
        return plot

    def _build_live_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.wave_plot = self._new_plot("实时 EEG（最近 4 秒）")
        self.wave_plot.setLabel("bottom", "距当前时间", units="s")
        self.wave_plot.setMouseEnabled(x=True, y=False)
        self.wave_plot.setDownsampling(auto=True, mode="peak")
        self.wave_plot.setClipToView(True)
        self.wave_curves: list[pg.PlotDataItem] = []
        for index in range(MAX_VISIBLE_CHANNELS):
            curve = self.wave_plot.plot(pen=pg.mkPen(PLOT_COLORS[index % len(PLOT_COLORS)], width=1))
            curve.setDownsampling(auto=True, method="peak")
            curve.setClipToView(True)
            self.wave_curves.append(curve)
        self.live_hint = QLabel("启动后显示波形。强脑采用逐通道独立缩放；博睿康保持原显示方式。")
        self.live_hint.setObjectName("muted")
        layout.addWidget(self.wave_plot, 1)
        layout.addWidget(self.live_hint)
        return tab

    def _build_spectrum_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.spectrum_plot = self._new_plot("平均功率频谱", "功率 dB")
        self.spectrum_plot.setLabel("bottom", "频率", units="Hz")
        self.spectrum_curve = self.spectrum_plot.plot(pen=pg.mkPen("#38bdf8", width=2))
        layout.addWidget(self.spectrum_plot)
        return tab

    def _build_quality_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.quality_summary = QLabel("等待数据")
        self.quality_summary.setObjectName("statusValue")
        self.quality_plot = self._new_plot("各通道 RMS", "RMS μV")
        self.quality_bars = pg.BarGraphItem(x=np.arange(MAX_VISIBLE_CHANNELS), height=np.zeros(MAX_VISIBLE_CHANNELS), width=0.7, brush="#14b8a6")
        self.quality_plot.addItem(self.quality_bars)
        layout.addWidget(self.quality_summary)
        layout.addWidget(self.quality_plot, 1)
        return tab

    def _build_paradigm_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.decoder_name = QLabel("Decoder：等待数据")
        self.decoder_name.setObjectName("muted")
        self.decoder_result = QLabel("尚未解码")
        self.decoder_result.setObjectName("resultValue")
        self.decoder_detail = QLabel("未标定，仅供快速观察；正式分类需要使用带标签数据校准。")
        self.decoder_detail.setWordWrap(True)
        self.decoder_metrics = QTableWidget(0, 2)
        self.decoder_metrics.setHorizontalHeaderLabels(("指标", "值"))
        self.decoder_metrics.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.decoder_name)
        layout.addWidget(self.decoder_result)
        layout.addWidget(self.decoder_detail)
        layout.addWidget(self.decoder_metrics, 1)
        return tab

    def _build_record_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        self.record_table = QTableWidget(0, 2)
        self.record_table.setHorizontalHeaderLabels(("项目", "当前值"))
        self.record_table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.record_table)
        return tab

    def _build_timers(self) -> None:
        self.wave_timer = QTimer(self)
        self.wave_timer.timeout.connect(self._refresh_waveform)
        self.wave_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.status_timer = QTimer(self)
        self.status_timer.timeout.connect(self._update_status)
        self.analysis_timer = QTimer(self)
        self.analysis_timer.timeout.connect(self._refresh_analysis)
        self.decoder_timer = QTimer(self)
        self.decoder_timer.timeout.connect(self._refresh_decoder)

    def _source_changed(self) -> None:
        source = self.source_select.currentText()
        is_replay = source == "NPZ 回放"
        is_neuracle = source == "博睿康 Neuracle"
        is_brainco = source == "强脑 BrainCo"
        self.channels.setMaximum(32 if is_brainco else 64)
        self.replay_group.setVisible(is_replay)
        self.device_group.setVisible(is_neuracle or is_brainco)
        self.neuracle_group.setVisible(is_neuracle)
        self.brainco_group.setVisible(is_brainco)
        if is_neuracle:
            self.sfreq.setValue(1000)
            self.channels.setValue(64)
        elif is_brainco:
            self.sfreq.setValue(250)
            self.channels.setValue(32)
        self._brainco_auto_changed()

    def _paradigm_changed(self) -> None:
        if not hasattr(self, "paradigm_form"):
            return
        paradigm = self.paradigm_select.currentText()
        rows = {
            self.ssvep_targets: paradigm == "SSVEP",
            self.image_category: paradigm == "视觉图像识别",
            self.mi_protocol: paradigm == "运动想象",
            self.visual_protocol: paradigm == "视觉图像识别",
            self.attention_protocol: paradigm == "注意力",
            self.emotion_protocol: paradigm == "情绪分类",
        }
        for widget, visible in rows.items():
            self.paradigm_form.setRowVisible(widget, visible)
        if self.stimulus_window.timer.isActive():
            self._stop_stimulus()

    def _populate_displays(self) -> None:
        self.display_select.clear()
        screens = QApplication.screens()
        for index, screen in enumerate(screens):
            geometry = screen.geometry()
            self.display_select.addItem(
                f"显示器 {index + 1}｜{geometry.width()}×{geometry.height()}｜{screen.refreshRate():g} Hz", index
            )
        if len(screens) > 1:
            self.display_select.setCurrentIndex(1)

    def _selected_screen(self):
        screens = QApplication.screens()
        index = int(self.display_select.currentData() or 0)
        return screens[min(index, len(screens) - 1)]

    def _start_stimulus(self) -> None:
        if self.controller is None or self.controller.state is not ConnectionState.RUNNING:
            QMessageBox.information(self, "请先启动采集", "请先启动模拟源或真机采集，再开始第二屏刺激。")
            return
        self.stimulus_events.clear()
        self._ssvep_checked_trials.clear()
        self._ssvep_trial_hits = 0
        screen = self._selected_screen()
        self.stimulus_window.start_protocol(self.paradigm_select.currentText(), screen)
        if self.paradigm_select.currentText() == "SSVEP":
            self.ssvep_targets.setText(", ".join(f"{value:g}" for value in self.stimulus_window.ssvep_frequencies))
        self.stimulus_status.setText(
            f"运行中｜{self.display_select.currentText()}｜软件时间戳同步｜Esc 可退出刺激"
        )

    def _stop_stimulus(self) -> None:
        self.stimulus_window.stop_protocol()

    def _stimulus_stopped(self) -> None:
        summary = self.stimulus_window.summary()
        hit_rate = summary["behavior_hit_rate"]
        hit_rate_text = "—" if hit_rate is None else f"{hit_rate:.0%}"
        self.stimulus_status.setText(
            f"已停止｜试次 {summary['trials']}｜行为命中率 {hit_rate_text}｜"
            f"估计丢帧 {summary['missed_frames_estimate']}"
        )

    def _on_stimulus_event(self, event: StimulusEvent) -> None:
        self.stimulus_events.append(event)
        if event.paradigm == "SSVEP" and event.phase == "rest":
            trial = int(event.payload.get("trial", -1))
            target = event.payload.get("target_frequency")
            if trial >= 0 and trial not in self._ssvep_checked_trials and target is not None:
                self._ssvep_checked_trials.add(trial)
                self._ssvep_trial_hits += int(self._last_decoder_value == f"{float(target):g} Hz")
        self.stimulus_status.setText(f"{event.paradigm}｜{event.phase}｜{event.label}｜软件同步")

    def _export_events(self) -> None:
        if not self.stimulus_events:
            QMessageBox.information(self, "没有事件", "请先运行至少一个刺激试次。")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出刺激事件", "neuroscope-events.csv", "CSV 文件 (*.csv)")
        if not path:
            return
        with Path(path).open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=(
                    "monotonic_time",
                    "wall_time",
                    "eeg_session_sec",
                    "paradigm",
                    "phase",
                    "label",
                    "payload",
                ),
            )
            writer.writeheader()
            for event in self.stimulus_events:
                row = event.as_dict()
                row["eeg_session_sec"] = (
                    event.monotonic_time - self.controller.started_at
                    if self.controller is not None and self.controller.started_at is not None
                    else ""
                )
                row["payload"] = json.dumps(row["payload"], ensure_ascii=False)
                writer.writerow(row)

    def _brainco_auto_changed(self) -> None:
        manual = not self.brainco_auto.isChecked()
        self.brainco_ip.setEnabled(manual)
        self.brainco_port.setEnabled(manual)

    def _refresh_rate_changed(self) -> None:
        if self.wave_timer.isActive():
            self.wave_timer.setInterval(timer_interval_ms(int(self.target_fps.currentData())))
            self._fps.reset()
            self._run_started_at = time.monotonic()

    def _browse_replay(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择 NPZ 回放文件", "", "NPZ 文件 (*.npz)")
        if path:
            self.replay_path.setText(path)

    def _build_source(self):
        label = self.source_select.currentText()
        sfreq = float(self.sfreq.value())
        n_channels = int(self.channels.value())
        if label == "NPZ 回放":
            if not self.replay_path.text().strip():
                raise ValueError("请先选择 NPZ 回放文件")
            return NPZReplaySource(Path(self.replay_path.text()).expanduser())
        if label == "博睿康 Neuracle":
            return build_neuracle_source(
                self.oi_mi_path.text(), self.neuracle_host.text(), self.neuracle_port.value(), sfreq, n_channels
            )
        if label == "强脑 BrainCo":
            return build_brainco_source(
                self.oi_mi_path.text(),
                sfreq,
                min(n_channels, 32),
                self.brainco_ip.text(),
                self.brainco_port.value(),
                self.brainco_auto.isChecked(),
            )
        names = SimulatedSource().metadata.channel_names[:n_channels]
        return SimulatedSource(sfreq=sfreq, channel_names=names, packet_sec=0.02)

    def _start_session(self) -> None:
        self._stop_session()
        try:
            self.controller = SessionController(self._build_source())
            self.controller.start()
        except Exception as exc:  # noqa: BLE001
            self.controller = None
            QMessageBox.critical(self, "无法启动", str(exc))
            return
        self._analysis_data = None
        self._wave_layout_key = None
        self._fps.reset()
        self._run_started_at = time.monotonic()
        self.wave_timer.start(timer_interval_ms(int(self.target_fps.currentData())))
        self.status_timer.start(100)
        self.analysis_timer.start(250)
        self.decoder_timer.start(500)
        self.start_button.setEnabled(False)
        self._set_controls_enabled(False)

    def _stop_session(self) -> None:
        self._stop_stimulus()
        self.wave_timer.stop()
        self.status_timer.stop()
        self.analysis_timer.stop()
        self.decoder_timer.stop()
        if self.controller is not None:
            self.controller.stop()
        self.controller = None
        self._analysis_data = None
        self.start_button.setEnabled(True)
        self._set_controls_enabled(True)
        self._update_status()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.source_select,
            self.sfreq,
            self.channels,
            self.replay_path,
            self.oi_mi_path,
            self.neuracle_host,
            self.neuracle_port,
            self.brainco_auto,
            self.brainco_ip,
            self.brainco_port,
        ):
            widget.setEnabled(enabled)
        if enabled:
            self._brainco_auto_changed()

    def _is_brainco(self) -> bool:
        return self.controller is not None and self.controller.source.metadata.source_type == "brainco"

    def _latest_data(self) -> tuple[np.ndarray, tuple[str, ...], float] | None:
        if self.controller is None:
            return None
        snapshot = self.controller.buffer.latest_available(WAVE_WINDOW_SEC)
        if snapshot is None:
            return None
        data = snapshot[0]
        metadata = self.controller.source.metadata
        return data, metadata.channel_names, metadata.sfreq

    def _refresh_waveform(self) -> None:
        latest = self._latest_data()
        if latest is None:
            return
        data, names, sfreq = latest
        display = brainco_display_preprocess(data, sfreq) if self._is_brainco() else data
        self._analysis_data = display
        if self.tabs.currentIndex() == 0:
            self._apply_wave_data(display, names, sfreq, independent_scale=self._is_brainco())
        self._fps.tick()

    def _apply_wave_data(
        self,
        data: np.ndarray,
        names: tuple[str, ...],
        sfreq: float,
        independent_scale: bool = False,
    ) -> None:
        values = np.nan_to_num(np.asarray(data, dtype=np.float32))
        n_show = min(MAX_VISIBLE_CHANNELS, values.shape[0])
        shown = values[:n_show]
        centered = shown - np.mean(shown, axis=1, keepdims=True)
        if independent_scale:
            plotted = robust_channel_scale(centered)
        else:
            scale = max(float(np.percentile(np.abs(centered), 95)), 1.0)
            plotted = centered / scale
        x = np.arange(shown.shape[1], dtype=np.float32) / sfreq - shown.shape[1] / sfreq
        offsets = np.arange(n_show, dtype=np.float32)[::-1] * 3.0
        for index, curve in enumerate(self.wave_curves):
            if index < n_show:
                curve.setData(x, plotted[index] + offsets[index], connect="finite")
                curve.show()
            else:
                curve.hide()
        layout_key = (names[:n_show], sfreq)
        if layout_key != self._wave_layout_key:
            ticks = [(float(offsets[index]), names[index]) for index in range(n_show)]
            self.wave_plot.getAxis("left").setTicks([ticks])
            self.wave_plot.setXRange(-WAVE_WINDOW_SEC, 0.0, padding=0.0)
            self.wave_plot.setYRange(-2.0, max(3.0, n_show * 3.0), padding=0.01)
            self._wave_layout_key = layout_key

    def _refresh_analysis(self) -> None:
        if self.controller is None or self._analysis_data is None or self._analysis_data.shape[1] < 8:
            return
        active_tab = self.tabs.currentIndex()
        if active_tab not in (1, 2):
            return
        metadata = self.controller.source.metadata
        if active_tab == 1:
            freqs, psd = power_spectrum(self._analysis_data, metadata.sfreq)
            spectrum_db = 10.0 * np.log10(np.mean(psd, axis=0) + 1e-12)
            self.spectrum_curve.setData(freqs, spectrum_db)
        else:
            quality = signal_quality(self._analysis_data, metadata.channel_names)
            self._show_quality(quality, metadata.channel_names)

    def _show_quality(self, quality: QualityReport, names: tuple[str, ...]) -> None:
        rms = quality.rms_uv[:MAX_VISIBLE_CHANNELS]
        x = np.arange(len(rms))
        self.quality_bars.setOpts(x=x, height=rms, width=0.7)
        self.quality_plot.getAxis("bottom").setTicks([[(float(i), names[i]) for i in range(len(rms))]])
        self.quality_summary.setText(
            f"整体质量：{quality.overall}　平直 {len(quality.flat_channels)}　"
            f"噪声 {len(quality.noisy_channels)}　疑似削顶 {len(quality.clipped_channels)}"
        )

    def _event(self) -> EEGEvent:
        if self.stimulus_events:
            targets = self.stimulus_window.ssvep_frequencies
        else:
            targets = frame_locked_frequencies(self._selected_screen().refreshRate())
        latest = self.stimulus_events[-1] if self.stimulus_events else None
        payload = {
            "image_category": "未设置",
            "target_present": False,
            "seen_reported": False,
            "ssvep_targets": targets,
            "software_sync": True,
        }
        if latest is not None:
            payload.update(latest.payload)
            payload["stimulus_phase"] = latest.phase
            payload["stimulus_label"] = latest.label
        return EEGEvent(
            timestamp=latest.wall_time if latest is not None else time.time(),
            name="stimulus_event" if latest is not None else "continuous_observation",
            code=latest.label if latest is not None else self.paradigm_select.currentText(),
            payload=payload,
        )

    def _refresh_decoder(self) -> None:
        if self.controller is None or self._analysis_data is None:
            return
        if self.tabs.currentIndex() != 3 and not self.stimulus_window.timer.isActive():
            return
        analysis_data = self._analysis_data
        if self.stimulus_events and self.stimulus_window.timer.isActive():
            latest = self.stimulus_events[-1]
            allowed = {
                "SSVEP": {"flicker"},
                "运动想象": {"imagery"},
                "视觉图像识别": {"stimulus", "response"},
                "注意力": {"mental_math", "problem", "response"},
                "情绪分类": {"emotion_imagery", "emotion", "rating"},
            }
            if latest.phase not in allowed[self.paradigm_select.currentText()]:
                self.decoder_result.setText("等待有效刺激阶段")
                self.decoder_detail.setText(f"当前阶段：{latest.phase}｜{latest.label}")
                return
            if latest.paradigm != "视觉图像识别":
                phase_samples = max(
                    32,
                    round((time.monotonic() - latest.monotonic_time) * self.controller.source.metadata.sfreq),
                )
                analysis_data = analysis_data[:, -min(phase_samples, analysis_data.shape[1]) :]
        try:
            event = self._event()
            result = PARADIGMS[self.paradigm_select.currentText()].analyze(
                self.controller.source.metadata, analysis_data, (event,)
            )
        except Exception as exc:  # noqa: BLE001
            self.decoder_detail.setText(str(exc))
            return
        self._show_decoder(result)
        self._show_record(event)

    def _show_decoder(self, result: ParadigmResult) -> None:
        self._last_decoder_value = result.headline
        if self.paradigm_select.currentText() == "SSVEP":
            indicator = f"候选分离度：{result.confidence:.0%}（非准确率）"
        else:
            indicator = "未标定快速趋势（不提供准确率）"
        self.decoder_name.setText(f"Decoder：{result.decoder_name}　来源：{result.source}　{indicator}")
        self.decoder_result.setText(result.headline)
        detail = result.detail
        if result.missing:
            detail += "\n" + "；".join(result.missing)
        self.decoder_detail.setText(detail + "\n未标定，仅供快速观察；只有带真实标签的试次评估才能计算准确率。")
        self.decoder_metrics.setRowCount(len(result.metrics))
        for row, (name, value) in enumerate(result.metrics.items()):
            self.decoder_metrics.setItem(row, 0, QTableWidgetItem(name))
            shown = f"{value:.4g}" if isinstance(value, float) else str(value)
            self.decoder_metrics.setItem(row, 1, QTableWidgetItem(shown))

    def _show_record(self, event: EEGEvent) -> None:
        if self.controller is None:
            return
        ssvep_rate = (
            f"{self._ssvep_trial_hits / len(self._ssvep_checked_trials):.0%}"
            if self._ssvep_checked_trials
            else "—"
        )
        values = (
            ("数据源", self.controller.source.metadata.source_id),
            ("累计样本", str(self.controller.samples_received)),
            ("数据块", str(self.controller.chunks_received)),
            ("同步方式", "软件时间戳（无硬件 Trigger）"),
            ("刺激阶段", str(event.payload.get("stimulus_phase", "连续观察"))),
            ("刺激标签", str(event.payload.get("stimulus_label", event.code))),
            ("图像类别", str(event.payload.get("image_category", "未设置"))),
            ("目标实际出现", "是" if event.payload.get("target_present") else "否"),
            ("已记录刺激事件", str(len(self.stimulus_events))),
            ("SSVEP 本会话试次匹配率", ssvep_rate),
        )
        self.record_table.setRowCount(len(values))
        for row, (name, value) in enumerate(values):
            self.record_table.setItem(row, 0, QTableWidgetItem(name))
            self.record_table.setItem(row, 1, QTableWidgetItem(value))

    def _update_status(self) -> None:
        target = int(self.target_fps.currentData())
        if self.controller is None:
            self.state_value.setText("idle")
            self.source_value.setText(self.source_select.currentText())
            self.rate_value.setText(f"{self.sfreq.value()} Hz")
            self.fps_value.setText(f"目标 {target} / 实际 0 FPS")
            self.data_value.setText("尚未接收")
            return
        metadata = self.controller.source.metadata
        self.state_value.setText(self.controller.state.value)
        self.source_value.setText(metadata.source_type)
        self.rate_value.setText(f"{metadata.sfreq:g} Hz")
        actual = self._fps.fps
        self.fps_value.setText(f"目标 {target} / 实际 {actual:.1f} FPS")
        age = self.controller.last_data_age_sec()
        buffered = self.controller.buffer.sample_count()
        self.data_value.setText("尚未收到" if age is None else f"{age:.2f}s 前｜缓冲 {buffered}")
        warmed_up = self._run_started_at is not None and time.monotonic() - self._run_started_at > 1.5
        level = fps_level(actual, target) if warmed_up else "good"
        colors = {"good": "#22c55e", "warning": "#f59e0b", "critical": "#ef4444"}
        self.fps_value.setStyleSheet(f"color: {colors[level]};")
        if self.controller.error:
            self.state_value.setText(f"error: {self.controller.error}")
            self.state_value.setStyleSheet("color: #ef4444;")
        elif self.controller.state is ConnectionState.RUNNING:
            self.state_value.setStyleSheet("color: #22c55e;")

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self._stop_session()
        event.accept()


def _application_font(app: QApplication) -> QFont:
    available = set(QFontDatabase.families())
    for family in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "PingFang SC", "Noto Sans CJK SC"):
        if family in available:
            return QFont(family, 10)
    font = app.font()
    font.setPointSize(10)
    return font


def main() -> int:
    pg.setConfigOptions(antialias=False, background="#0f172a", foreground="#cbd5e1")
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("NeuroScope")
    app.setFont(_application_font(app))
    app.setStyleSheet(
        """
        QWidget { background: #0b1220; color: #e2e8f0; }
        QGroupBox { border: 1px solid #334155; border-radius: 7px; margin-top: 9px; padding-top: 8px; }
        QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #94a3b8; }
        QLineEdit, QSpinBox, QComboBox, QTableWidget { background: #111c2f; border: 1px solid #334155; border-radius: 4px; padding: 5px; }
        QPushButton { background: #1e293b; border: 1px solid #475569; border-radius: 5px; padding: 7px 12px; }
        QPushButton:hover { background: #334155; }
        QPushButton#primaryButton { background: #2563eb; border-color: #3b82f6; }
        QLabel#appTitle { font-size: 24px; font-weight: 700; color: #f8fafc; }
        QLabel#statusValue { font-size: 17px; font-weight: 600; }
        QLabel#resultValue { font-size: 30px; font-weight: 700; color: #38bdf8; padding: 12px 0; }
        QLabel#muted { color: #94a3b8; }
        QTabBar::tab { background: #111c2f; padding: 9px 16px; }
        QTabBar::tab:selected { background: #1e3a5f; color: #7dd3fc; }
        """
    )
    window = NeuroScopeWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
