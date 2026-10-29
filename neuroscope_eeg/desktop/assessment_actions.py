"""Finite-protocol controls and a single background report process queue."""
import codecs
import json
import sys
from collections import deque
from pathlib import Path

from PySide6.QtCore import QProcess, QProcessEnvironment, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QCheckBox, QFormLayout, QGroupBox, QLabel, QPushButton, QSizePolicy

from neuroscope_eeg.desktop.protocol_settings import ProtocolSettings


class AssessmentActions(ProtocolSettings):
    def _add_assessment_controls(self, layout, report_layout):
        self._report_queue = deque()
        self._report_process = None
        self._latest_report = None
        self._report_run = None
        self._report_buffer = ""
        self._report_parse_offset = 0
        self._current_report = None
        self._add_protocol_settings(layout)
        group = QGroupBox("自动评估与 Word 报告")
        actions = QFormLayout(group)
        self.report_status = QLabel("完整采集封存后自动生成；快速演示不保存报告。")
        self.report_status.setWordWrap(True)
        self.report_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.report_status.setTextFormat(Qt.TextFormat.PlainText)
        self.report_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        actions.addRow(self.report_status)
        self.delivery_status = QLabel("完整采集结束后自动导出 EDF；配置、对齐或外部 EDF 缺失时显示原因。")
        self.delivery_status.setWordWrap(True)
        self.delivery_status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.delivery_status.setTextFormat(Qt.TextFormat.PlainText)
        self.delivery_status.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        actions.addRow(self.delivery_status)
        self.export_estimated_timing = QCheckBox("自动导出允许软件估计事件时间（未校准）")
        self.export_estimated_timing.setChecked(True)
        self.export_estimated_timing.setToolTip("仅用于本程序收到的 EEG；不代表物理时序已验证。关闭后须补充对齐表。EMOTIV 始终需要对齐依据。设置在开始采集时保存。")
        actions.addRow(self.export_estimated_timing)
        retry = QPushButton("重试 EDF 交付与报告")
        retry.setToolTip("选择已保存的记录，检查 EDF 交付并重新生成报告；不导入新的 EDF。正常实验结束或关联 EDF 后会自动排队处理。")
        retry.clicked.connect(self._retry_report)
        actions.addRow(retry)
        open_report = QPushButton("打开最近 Word 报告")
        open_report.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._latest_report))) if self._latest_report else None)
        actions.addRow(open_report)
        open_directory = QPushButton("打开最近报告目录")
        open_directory.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._latest_report.parent))) if self._latest_report else None)
        actions.addRow(open_directory)
        report_layout.addWidget(group)

    def _retry_report(self):
        run = self._choose_run()
        if run:
            self._enqueue_report(run)

    def _enqueue_report(self, run):
        run = Path(run)
        if run not in self._report_queue:
            self._report_queue.append(run)
        self._start_next_report()

    def _start_next_report(self):
        if self._report_process is not None or not self._report_queue:
            return
        self._report_run = self._report_queue.popleft()
        self._report_buffer = ""
        self._report_parse_offset = 0
        self._current_report = None
        self._report_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self.delivery_status.setText("正在处理本次 EDF 交付…")
        process = QProcess(self)
        self._report_process = process
        process.setProgram(sys.executable)
        environment = QProcessEnvironment.systemEnvironment()
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
            environment.insert(name, "1")
        process.setProcessEnvironment(environment)
        process.setArguments(["-u", "-m", "neuroscope_eeg.io.postprocess", str(self._report_run)])
        process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        process.readyReadStandardOutput.connect(self._read_report_progress)
        process.finished.connect(self._report_finished)
        process.errorOccurred.connect(self._report_process_error)
        self.report_status.setText(f"正在后台评估：{self._report_run.name}")
        process.start()

    def _read_report_progress(self):
        self._report_buffer += self._report_decoder.decode(bytes(self._report_process.readAllStandardOutput()))
        pending = self._report_buffer[self._report_parse_offset:]
        for line in pending.splitlines(keepends=True):
            if not line.endswith("\n"):
                break
            self._report_parse_offset += len(line)
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("progress"):
                self.report_status.setText(message["progress"])
            if message.get("delivery"):
                result = message["delivery"]
                self.delivery_status.setText(result["message"] + ("\n位置：" + result["package"] if result.get("package") else ""))
            if message.get("report"):
                self._current_report = self._latest_report = Path(message["report"])

    def _report_process_error(self, error):
        if error == QProcess.ProcessError.FailedToStart:
            self._report_finished(-1)

    def _report_finished(self, code, *_):
        if self._report_process is None:
            return
        self._read_report_progress()
        if code == 0:
            if self._current_report:
                self.report_status.setText(f"评估完成\n报告：{self._latest_report.name}\n保存位置：{self._latest_report.parent}")
            else:
                self.report_status.setText(f"评估完成：{self._report_run.name}\n等待外部 EEG")
        else:
            self.report_status.setText(f"评估未完成，可重试：{self._report_run.name}\n{self._report_buffer[-500:]}")
        self._report_process.deleteLater()
        self._report_process = None
        self._report_run = None
        self._start_next_report()
