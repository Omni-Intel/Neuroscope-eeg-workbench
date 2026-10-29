"""Run management widgets and actions, kept separate from waveform rendering."""
import json
import shutil
import uuid
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
)

from neuroscope_eeg.acquisition.devices import read_profile
from neuroscope_eeg.desktop.experiment_identity import ExperimentIdentity
from neuroscope_eeg.io.bids_export import validate_delivery
from neuroscope_eeg.io.external_recording import associate_external
from neuroscope_eeg.io.impedance import import_measurement
from neuroscope_eeg.io.native_recording import utc_now, write_json


class FileWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, operation, parent):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.succeeded.emit(self.operation())
        except Exception as exc:  # noqa: BLE001 - report worker failures to the GUI
            self.failed.emit(str(exc))


class WorkbenchActions(ExperimentIdentity):
    def _add_workbench_controls(self, layout, form, delivery_layout, profile_form):
        self._file_worker = None
        self._scan_worker = None
        self._last_recording_path = None
        self.paradigm_code = QLineEdit()
        self.paradigm_code.setPlaceholderText("平台已登记代码，如 RSVP-20260924")
        self.unique_name = QLineEdit()
        self.unique_name.setReadOnly(True)
        self.unique_name.setPlaceholderText("来自实验信息；模拟无配置时使用专用测试身份")
        form.addRow("范式代码", self.paradigm_code)
        form.addRow("实验唯一名称", self.unique_name)
        self.experiment_info_button = QPushButton("建立 / 编辑实验信息")
        self.experiment_info_button.clicked.connect(self._edit_experiment)
        form.addRow(self.experiment_info_button)
        self.profile_path = QLineEdit()
        self.profile_path.setPlaceholderText("可选：设备配置 JSON；导出前须确认")
        browse = QPushButton("选择设备配置")
        self.profile_browse = browse
        browse.clicked.connect(self._browse_profile)
        profile_form.addRow(self.profile_path)
        profile_form.addRow(browse)

        self.extra_device_group = QGroupBox("公司 SDK / LSL / EMOTIV")
        extra = QFormLayout(self.extra_device_group)
        self._extra_device_form = extra
        self.omni_endpoint = QLineEdit("serial://COM5")
        self.omni_type = QComboBox()
        self.omni_type.addItems(["esp32", "stm32"])
        self.omni_type.currentTextChanged.connect(lambda: self._source_changed())
        self.omni_transport = QComboBox()
        self.omni_transport.addItem("USB / 串口", "serial")
        self.omni_transport.addItem("蓝牙 BLE", "ble")
        self.omni_scan_button = QPushButton("扫描公司设备")
        self.omni_scan_button.clicked.connect(self._scan_omni)
        self.emotiv_scan_button = QPushButton("扫描并选择 Marker 配对串口")
        self.emotiv_scan_button.clicked.connect(self._scan_emotiv_ports)
        self.discovery_status = QLabel("扫描仅发现候选；设备连接以接收数据为准。")
        self.discovery_status.setWordWrap(True)
        self.lsl_source_id = QLineEdit()
        self.lsl_source_id.setPlaceholderText("LSL source_id；多流时必须指定")
        self.emotiv_receive_port = QLineEdit()
        self.emotiv_receive_port.setPlaceholderText("EmotivPRO 接收串口，与发送口不同")
        self.emotiv_recording_confirmed = QCheckBox("已在 EmotivPRO 开始本次录制\n并已设置 Marker 接收口")
        self.emotiv_recording_confirmed.setToolTip("人工确认；程序不接收实时 EEG，也无法验证 EmotivPRO 是否正在录制")
        extra.addRow("SDK 地址", self.omni_endpoint)
        extra.addRow("SDK 硬件", self.omni_type)
        extra.addRow("扫描方式", self.omni_transport)
        extra.addRow(self.omni_scan_button)
        impedance = QPushButton("公司设备：采集前测阻抗")
        self.impedance_button = impedance
        impedance.clicked.connect(self._measure_impedance)
        extra.addRow(impedance)
        extra.addRow("LSL 来源", self.lsl_source_id)
        extra.addRow("EMOTIV 接收口", self.emotiv_receive_port)
        extra.addRow(self.emotiv_scan_button)
        extra.addRow(self.emotiv_recording_confirmed)
        extra.addRow(self.discovery_status)
        layout.addWidget(self.extra_device_group)

        delivery = QGroupBox("记录与交付")
        actions = QFormLayout(delivery)
        self._delivery_form = actions
        note = QLabel("每次完整采集独立 UUID；可自由选择设备和范式。导出不会改写原始数据。")
        note.setWordWrap(True)
        actions.addRow(note)
        for label, callback in [("导入并关联 EMOTIV EDF（自动评估）", self._associate_edf),
                                ("运行 BIDS Validator", self._validate_delivery),
                                ("关联阻抗 / CQ / EQ 凭据", self._import_impedance),
                                ("导入已核对的事件对齐表", self._import_alignment),
                                ("为已有记录关联分析配置", self._associate_analysis_profile)]:
            button = QPushButton(label)
            if callback == self._associate_edf:
                self.emotiv_edf_button = button
                button.setToolTip("先选择本次实验记录，再导入 EmotivPRO 导出的 EDF；关联后自动排队评估，无需再次点击生成报告。")
            button.clicked.connect(callback)
            actions.addRow(button)
        delivery_layout.addWidget(delivery)

    def _measure_impedance(self):
        if self.controller is not None:
            QMessageBox.warning(self, "请先断开连接", "阻抗检测与脑电采集互斥；请先在实验准备页断开连接。")
            return
        if self.source_select.currentText() != "公司 OmniBCI":
            QMessageBox.information(self, "请选择公司设备", "此入口使用公司 OmniBCI SDK")
            return
        endpoint, device_type = self.omni_endpoint.text(), self.omni_type.currentText()
        try:
            profile = read_profile(self.profile_path.text())
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "设备配置不可用", str(exc))
            return
        root = Path(self.recording_root.text())
        def measure():
            from omnibci import Board
            with Board.connect(endpoint, device_type=device_type) as board:
                result = asdict(board.measure_impedance())
            names = profile.get("channel_names", [f"CH{i+1}" for i in range(len(result["values_kohm"]))])
            if len(names) != len(result["values_kohm"]):
                raise ValueError("设备配置电极数与阻抗物理通道数不一致")
            measurement = {"source_id": profile.get("device_id") or "omnibci", "measured_at": utc_now(),
                           "stage": "pre", "unit": "kOhm", "method": "OmniBCI SDK measure_impedance",
                           "endpoint": endpoint, "device_type": device_type, "sdk_result": result,
                           "channels": [{"channel": name, "value": value,
                                         "status": "clipped" if result.get("clipped_mask", 0) & (1 << i) else ("未测/无效" if value is None else "待硬件标定核验")}
                                        for i, (name, value) in enumerate(zip(names, result["values_kohm"]))]}
            directory = root / "Records" / "impedance_measurements"
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / (uuid.uuid4().hex + ".json")
            write_json(target, measurement)
            return target
        self._run_file_operation(measure, lambda result: f"SDK 阻抗已保存：{result}\n测量后设备已停止。请在实验准备页重新连接，确认波形稳定后到范式设置页开始实验。\n实验结束后使用“关联阻抗 / CQ / EQ 凭据”选择本文件及对应 UUID，核对时间与设备；不自动沿用旧测量。")

    def _import_impedance(self):
        run = self._choose_run()
        if run is None:
            return
        source, _ = QFileDialog.getOpenFileName(self, "选择本次测量 JSON / CSV（可附截图）", str(Path(self.recording_root.text()) / "Records" / "impedance_measurements"), "测量 (*.json *.csv)")
        if not source:
            return
        # Selecting a run is deliberate, but display timing to prevent silent stale-measurement reuse.
        text = Path(source).read_text(encoding="utf-8-sig")
        if QMessageBox.question(self, "核对测量归属", f"记录 UUID：{run.name}\n请核对设备、测量时间和采集前/后阶段。仅关联本次测量。\n{text[:1800]}") != QMessageBox.StandardButton.Yes:
            return
        def finished(path):
            self._enqueue_report(run)
            return f"已关联并排队重算报告：{path}"
        self._run_file_operation(lambda: import_measurement(run, source), finished)

    def _import_alignment(self):
        run = self._choose_run()
        if run is None:
            return
        source, _ = QFileDialog.getOpenFileName(self, "选择含本次 UUID、method、evidence 的 alignment.json", "", "JSON (*.json)")
        if not source:
            return
        def operation():
            value = json.loads(Path(source).read_text(encoding="utf-8-sig"))
            info = json.loads((run / "run.json").read_text(encoding="utf-8"))
            if value.get("session_id") != info["session_id"] or not value.get("method") or not value.get("evidence") or not isinstance(value.get("events"), list):
                raise ValueError("对齐表缺少本次 UUID、方法、依据或事件映射")
            target = run / "alignment.json"
            if target.exists():
                shutil.copy2(target, run / ("alignment-" + uuid.uuid4().hex + ".backup.json"))
            write_json(target, value)
            return target
        def finished(path):
            self._enqueue_report(run)
            return f"已保存对齐表，后台将校验事件范围：{path}"
        self._run_file_operation(operation, finished)

    def _associate_analysis_profile(self):
        run = self._choose_run()
        if run is None:
            return
        source, _ = QFileDialog.getOpenFileName(self, "选择与此记录对应、已核对的分析配置", "", "JSON (*.json)")
        if not source:
            return
        def operation():
            profile = read_profile(source)
            if profile.get("confirmed") is not True:
                raise ValueError("需明确 confirmed=true；确认电极、参考方式、单位、EDF 通道类型")
            info = json.loads((run / "run.json").read_text(encoding="utf-8"))
            device = json.loads((run / "device.json").read_text(encoding="utf-8"))
            profile.update(session_id=info["session_id"], source_id=device["source_id"])
            path = run / "analysis_profile.json"
            if path.exists():
                shutil.copy2(path, run / ("analysis-profile-" + uuid.uuid4().hex + ".backup.json"))
            write_json(path, profile)
            return path
        def finished(path):
            self._enqueue_report(run)
            return f"已关联分析配置：{path}；原始采样值与单位不改写。"
        self._run_file_operation(operation, finished)

    def _browse_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择已核对的设备配置", "", "JSON (*.json)")
        if path:
            self.profile_path.setText(path)

    def _choose_run(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择记录的 run.json",
                  str(self._last_recording_path or Path(self.recording_root.text()) / "Records"), "Run metadata (run.json)")
        return Path(path).parent if path else None

    def _run_file_operation(self, operation, message):
        if self._scan_worker is not None:
            QMessageBox.information(self, "正在扫描", "请等待扫描完成后再操作。")
            return
        if self._file_worker is not None and self._file_worker.isRunning():
            QMessageBox.information(self, "正在处理", "请等待当前文件操作完成")
            return
        worker = FileWorker(operation, self)
        worker.succeeded.connect(lambda result: QMessageBox.information(self, "处理完成", message(result)))
        worker.failed.connect(lambda error: QMessageBox.warning(self, "未完成", error))
        self._file_worker = worker
        worker.start()

    def _associate_edf(self):
        run = self._choose_run()
        if run is None:
            return
        edf, _ = QFileDialog.getOpenFileName(self, "选择 EmotivPRO 已导出的 EDF", "", "EDF (*.edf)")
        if not edf:
            return
        choice = QMessageBox.question(self, "核对外部记录",
            f"请确认此 EDF 对应所选记录的被试、设备和范式。\n记录：{run.name}\n文件：{edf}\n关联不代表事件已对齐。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No)
        if choice == QMessageBox.StandardButton.Yes:
            def finished(_):
                self._enqueue_report(run)
                return "EDF 已关联，已排队生成通用报告。任务指标需要已核对的设备配置与 alignment.json。"
            self._run_file_operation(lambda: associate_external(run, edf, operator_confirmed=True),
                finished)

    def _validate_delivery(self):
        path = QFileDialog.getExistingDirectory(self, "选择 recording-UUID 交付目录", self.recording_root.text())
        if path:
            self._run_file_operation(lambda: validate_delivery(path),
                lambda result: f"BIDS 校验通过；{len(result['warnings'])} 项建议，详见 Records 内 delivery/validation.json" if result["bids_validated"] else "校验未通过或输出不受支持；详见 Records 内 delivery/validation.json")

    def _lock_run_controls(self, locked):
        for widget in (self.experiment_info_button, self.paradigm_code, self.unique_name, self.paradigm_select,
                       self.protocol_preset, self.emotiv_recording_confirmed, self.emotiv_receive_port, self.export_estimated_timing):
            widget.setEnabled(not locked)
        editable_profile = not locked and self.controller is None
        self.profile_path.setEnabled(editable_profile)
        self.profile_browse.setEnabled(editable_profile)
