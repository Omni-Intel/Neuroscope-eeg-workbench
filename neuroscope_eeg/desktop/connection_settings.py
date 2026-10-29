"""Connection preferences contain no participant data or trusted connection state."""

import json

from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import QCheckBox, QComboBox, QLineEdit, QSpinBox

from neuroscope_eeg.core.models import ConnectionState


class ConnectionSettings:
    def _connection_fields(self, source):
        common = ["profile_path", "sfreq", "channels", "timing_mode", "trigger_port"]
        specific = {
            "模拟": [],
            "NPZ 回放": ["replay_path"],
            "博睿康 Neuracle": ["neuracle_host", "neuracle_port"],
            "强脑 BrainCo": ["brainco_auto", "brainco_ip", "brainco_port"],
            "公司 OmniBCI": ["omni_type", "omni_endpoint", "omni_transport"],
            "通用 LSL": ["lsl_source_id"],
            "test-头带": ["td10_source_id"],
            "EMOTIV 外部录制": ["emotiv_receive_port"],
        }
        return {name: getattr(self, name) for name in common + specific.get(source, [])}

    def _remember_connection(self, source):
        if not source:
            return
        values = {}
        for name, widget in self._connection_fields(source).items():
            if isinstance(widget, QCheckBox):
                value = widget.isChecked()
            elif isinstance(widget, QSpinBox):
                value = widget.value()
            elif isinstance(widget, QComboBox):
                value = widget.currentText()
            else:
                value = widget.text()
            values[name] = value
        self._connection_profiles[source] = values

    def _apply_connection(self, source):
        values = self._connection_profiles.get(source, {})
        fields = self._connection_fields(source)
        blockers = [QSignalBlocker(widget) for widget in fields.values()]
        for name, widget in fields.items():
            value = values.get(name)
            if isinstance(widget, QCheckBox) and type(value) is bool:
                widget.setChecked(value)
            elif isinstance(widget, QSpinBox) and type(value) is int and widget.minimum() <= value <= widget.maximum():
                widget.setValue(value)
            elif isinstance(widget, QComboBox) and isinstance(value, str):
                if widget.isEditable() or widget.findText(value) >= 0:
                    widget.setCurrentText(value)
            elif isinstance(widget, QLineEdit) and isinstance(value, str):
                widget.setText(value)
        del blockers
        if source == "公司 OmniBCI":
            self.sfreq.setValue(250)
            self.channels.setValue(32 if self.omni_type.currentText() == "stm32" else 8)
        elif source == "test-头带":
            self.sfreq.setValue(250)
            self.channels.setValue(4)
        self._timing_mode_changed()

    def _load_connection_settings(self):
        path = self._settings_path
        if not path.exists():
            return
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict) or value.get("version") != 1 or not isinstance(value.get("profiles"), dict):
                raise ValueError("不支持的配置结构")
            known = {self.source_select.itemText(i) for i in range(self.source_select.count())}
            if set(value) - {"version", "selected_source", "profiles"} or set(value["profiles"]) - known:
                raise ValueError("连接配置含未知字段或设备")
            for key, fields in value["profiles"].items():
                if not isinstance(fields, dict) or set(fields) - set(self._connection_fields(key)):
                    raise ValueError("连接配置含未知设备字段")
                for name, val in fields.items():
                    widget = self._connection_fields(key)[name]
                    valid = ((isinstance(widget, QCheckBox) and type(val) is bool)
                             or (isinstance(widget, QSpinBox) and type(val) is int and widget.minimum() <= val <= widget.maximum())
                             or (isinstance(widget, QLineEdit) and isinstance(val, str))
                             or (isinstance(widget, QComboBox) and isinstance(val, str) and (widget.isEditable() or widget.findText(val) >= 0
                                 or (name == "timing_mode" and val in {"NDE0001 硬件 + LSL（推荐）", "NDE0001 独立 TriggerBox + LSL", "EmotivPRO 配对串口 + LSL"}))))
                    if not valid:
                        raise ValueError("连接配置值无效：" + name)
            self._connection_profiles = {
                k: {name: v[name] for name in self._connection_fields(k) if name in v}
                for k, v in value["profiles"].items()
                if k in known and isinstance(v, dict)
            }
            source = value.get("selected_source")
            if source not in known:
                source = "模拟"
            blocker = QSignalBlocker(self.source_select)
            self.source_select.setCurrentText(source)
            del blocker
            self._selected_source = ""
            self.source_select.currentTextChanged.emit(source)
            self.settings_status.setText("已恢复连接配置；设备尚未连接，请重新检查。")
        except (OSError, ValueError, TypeError) as exc:
            self.settings_status.setText(f"配置未恢复，使用默认设置：{exc}")

    def _save_connection_settings(self):
        if self._scan_worker is not None:
            self.settings_status.setText("请等待扫描完成后保存。")
            return
        self._remember_connection(self.source_select.currentText())
        value = {
            "version": 1,
            "selected_source": self.source_select.currentText(),
            "profiles": self._connection_profiles,
        }
        path = self._settings_path
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
            self.settings_status.setText("连接配置已保存，下次打开自动恢复；不保存已连接或录制确认状态。")
        except OSError as exc:
            self.settings_status.setText(f"保存失败：{exc}")

    def _refresh_connection_state(self):
        c = self.controller
        external = self.source_select.currentText() == "EMOTIV 外部录制"
        ready = False
        color = "#94a3b8"
        if c is None:
            state, detail = "待连接", "连接后检查实际收样；检查阶段不保存正式实验数据。"
            if external:
                state, detail = "待准备外部录制", "EEG 连接与录制由 EmotivPRO 完成，本程序无法验证。"
        elif c.error:
            state, detail, color = "连接 / 数据异常", c.error, "#fb7185"
        elif external:
            state, detail = "外部录制待人工确认", "没有本地 EEG 收样验证；请确认 EmotivPRO 录制和 Marker 接收。"
            ready = c.state is ConnectionState.RUNNING and self.emotiv_recording_confirmed.isChecked()
            if ready:
                state, color = "外部录制已人工确认", "#f59e0b"
        elif c.state is ConnectionState.CONNECTING:
            state, detail = "正在连接", "正在发现或连接设备、核对元数据并等待样本…"
        elif c.state is ConnectionState.RUNNING:
            age = c.last_data_age_sec()
            if c.samples_received == 0 or age is None:
                state, detail = "等待数据", "接口已启动，尚未收到脑电样本。"
            elif age > 2:
                state, detail, color = "数据暂未更新", f"最后样本距今 {age:.1f} 秒，请检查设备。", "#f59e0b"
            else:
                state, color, ready = "已接收数据", "#22c55e", True
                detail = f"累计 {c.samples_received} 样本｜{c.source.metadata.n_channels} 通道｜{c.source.metadata.sfreq:g} Hz｜最近 {age:.2f} 秒前"
                if c.source.metadata.source_type == "brainco":
                    backend = c.source.backend
                    target = backend._cached_discovery_target or (backend._brainco_addr, backend._brainco_port)
                    detail += f"｜{target[0]}:{target[1]}"
        else:
            state, detail = "连接已停止", "请重新连接并检查数据。"
        self.state_value.setText(state)
        self.state_value.setStyleSheet(f"color: {color};")
        self.connection_detail.setText(detail)
        self.stimulus_start_button.setEnabled(ready and not self.stimulus_window.timer.isActive())
        self.stimulus_stop_button.setEnabled(self.stimulus_window.timer.isActive())
        self.stop_button.setEnabled(c is not None)
        self.save_connection_button.setEnabled(self._scan_worker is None)
