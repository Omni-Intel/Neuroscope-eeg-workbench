"""Background discovery with explicit selection; scanning never starts EEG."""
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
)

from neuroscope_eeg.desktop.workbench_actions import FileWorker


def discover_omni(transport, device_type):
    from omnibci import Board
    return [{"endpoint": d.endpoint, "name": d.name, "type": d.device_type}
            for d in Board.discover(transport=transport, device_type=device_type, timeout=6)]


def marker_ports():
    from serial.tools.list_ports import comports
    result = []
    for p in sorted(comports(), key=lambda p: p.device):
        details = " ".join(str(getattr(p, k, "") or "") for k in ("description", "hwid", "product")).lower()
        blocked = (p.vid, p.pid) == (0x1915, 0xC00A) or "nrf52 connectivity" in details
        result.append({"port": p.device, "description": p.description or "未知设备",
                       "identity": (p.hwid, p.serial_number), "blocked": blocked})
    return result


class DeviceDiscoveryActions:
    def _start_device_scan(self, operation, finished):
        if self.controller is not None:
            QMessageBox.information(self, "请先断开连接", "扫描和修改连接参数前，请在实验准备页断开连接。")
            return
        if self._scan_worker is not None or (self._file_worker is not None and self._file_worker.isRunning()):
            QMessageBox.information(self, "正在处理", "请等待当前扫描或文件操作完成。")
            return
        worker = FileWorker(operation, self)
        self._scan_worker = worker
        outcome = {}
        worker.succeeded.connect(lambda value: outcome.update(result=value))
        worker.failed.connect(lambda error: outcome.update(error=error))
        def done():
            self._scan_worker = None
            self.save_connection_button.setEnabled(True)
            self._set_controls_enabled(True)
            self.start_button.setEnabled(True)
            self.discovery_status.setText("扫描完成；选择地址后需点击“连接并检查数据”。")
            worker.deleteLater()
            if "error" in outcome:
                self.discovery_status.setText("扫描失败，可检查连接条件或手动填写地址。")
                QMessageBox.warning(self, "扫描失败", outcome["error"])
            else:
                finished(outcome.get("result", []))
        worker.finished.connect(done)
        self._set_controls_enabled(False)
        self.start_button.setEnabled(False)
        self.save_connection_button.setEnabled(False)
        self.discovery_status.setText("正在扫描，请稍候…")
        worker.start()

    def _scan_omni(self):
        transport = self.omni_transport.currentData()
        device_type = self.omni_type.currentText()
        self._start_device_scan(lambda: discover_omni(transport, device_type), self._select_omni)

    def _select_omni(self, candidates):
        if not candidates:
            self.discovery_status.setText("未找到候选；请检查 USB / 蓝牙，或手动填写 SDK 地址。")
            return
        labels = [f"{i + 1}. {d['name']}  |  {d['endpoint']}  |  {d['type']}" for i, d in enumerate(candidates)]
        label, accepted = QInputDialog.getItem(self, "选择公司设备候选",
            "扫描结果不代表已验证设备身份；选择后点击“连接并检查数据”。", labels, 0, False)
        if accepted:
            self.omni_endpoint.setText(candidates[labels.index(label)]["endpoint"])
            self.discovery_status.setText("已填写所选地址，尚未连接。")

    def _scan_emotiv_ports(self):
        self._start_device_scan(marker_ports, self._select_emotiv_ports)

    def _select_emotiv_ports(self, ports):
        if not ports:
            self.discovery_status.setText("未发现串口；请先创建虚拟串口对或连接标记线。")
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("选择 EMOTIV Marker 配对串口")
        form = QFormLayout(dialog)
        note = QLabel("这里只列出串口，不能识别配对关系或连接头戴设备。\n请核对虚拟串口工具与 EmotivPRO 的设置。")
        note.setWordWrap(True)
        form.addRow(note)
        send, receive = QComboBox(), QComboBox()
        for combo in (send, receive):
            combo.addItem("请选择（不自动选择）", None)
            for row in ports:
                combo.addItem(f"{row['port']} — {row['description']}" + ("（不支持此 Marker 协议）" if row['blocked'] else ""), row)
                if row["blocked"]:
                    combo.model().item(combo.count() - 1).setEnabled(False)
            combo.setMinimumWidth(360)
        form.addRow("本程序发送口", send)
        form.addRow("EmotivPRO 接收口", receive)
        confirmed = QCheckBox("已核对两端配对关系，并将在 EmotivPRO 设置所选接收口")
        form.addRow(confirmed)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        form.addRow(buttons)
        def validate():
            a, b = send.currentData(), receive.currentData()
            buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(
                confirmed.isChecked() and a and b and not a["blocked"] and not b["blocked"] and a["port"] != b["port"]))
        def changed():
            confirmed.setChecked(False)
            validate()
        send.currentIndexChanged.connect(changed)
        receive.currentIndexChanged.connect(changed)
        confirmed.toggled.connect(validate)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        validate()
        if dialog.exec() == QDialog.DialogCode.Accepted:
            selected = (send.currentData(), receive.currentData())
            fresh = {p["port"]: p for p in marker_ports()}
            if any(p["port"] not in fresh or fresh[p["port"]]["identity"] != p["identity"] or fresh[p["port"]]["blocked"] for p in selected):
                QMessageBox.warning(self, "端口已变化", "请重新扫描并选择串口。")
                return
            self.trigger_port.setText(selected[0]["port"])
            self.emotiv_receive_port.setText(selected[1]["port"])
            self.emotiv_recording_confirmed.setChecked(False)
            self.discovery_status.setText("已填写配对串口；请在 EmotivPRO 开始录制后勾选确认。")
