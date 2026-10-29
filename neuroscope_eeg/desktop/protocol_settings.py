"""Per-paradigm settings; the running experiment receives an immutable snapshot."""
import json

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from neuroscope_eeg.protocol_config import AssessmentProtocol


class ProtocolSettings:
    def _add_protocol_settings(self, layout):
        self._trial_paradigm = "SSVEP"
        self._protocol_values = {p: AssessmentProtocol.defaults(p).to_dict() for p in ("SSVEP", "运动想象")}
        self._protocol_settings_path = self._settings_path.with_name("protocol-settings.json")
        load_message = "分别保存两种范式的设置；实验开始后锁定。"
        if self._protocol_settings_path.exists():
            try:
                saved = json.loads(self._protocol_settings_path.read_text(encoding="utf-8"))
                if not isinstance(saved, dict) or set(saved) - set(self._protocol_values):
                    raise ValueError("未知范式配置")
                for p in self._protocol_values:
                    if p in saved:
                        plan = AssessmentProtocol.from_dict(saved[p]).for_new_run()
                        if plan.paradigm != p:
                            raise ValueError("保存的范式不匹配")
                        self._protocol_values[p] = plan.to_dict()
                load_message = "已恢复实验设置；SSVEP 已升级为八目标同时闪烁；试次数向上取整至 8 的倍数，请核对。"
            except (OSError, ValueError, TypeError):
                load_message = "部分保存设置无法读取；相应范式使用默认值，请核对。"
        self.trial_group = QGroupBox("实验流程与参数")
        body = QVBoxLayout(self.trial_group)
        note = QLabel("指导 → 练习 → 独立静息基线 → 正式实验\n空格用于准备页与组间继续；刺激全屏呈现。")
        note.setWordWrap(True)
        body.addWidget(note)
        tabs = QTabWidget()
        body.addWidget(tabs)
        self.protocol_fields, self.protocol_defaults, self.protocol_rows = {}, {}, {}
        groups = (
            ("试次", [("total_trials", "正式总试次数", 3, 4000), ("block_trials", "每组试次数", 3, 4000),
                      ("practice_per_condition", "每条件练习次数", 0, 20)]),
            ("试次时长", [("fixation_sec", "准备／任务前基线", 1.5, 30), ("cue_sec", "条件提示", .5, 30),
                         ("prep_sec", "目标常亮定位", .5, 30),
                         ("task_sec", "闪烁／想象", 3, 60), ("rest_sec", "试次内休息", .5, 60),
                         ("block_rest_sec", "组间最短休息", 5, 600)]),
            ("静息基线", [("eyes_open_sec", "睁眼静息", 5, 600), ("close_prepare_sec", "闭眼准备", 3, 60),
                         ("eyes_closed_sec", "闭眼静息", 5, 600), ("open_recovery_sec", "睁眼恢复", 3, 60)]),
            ("刺激显示", [("screen_diagonal_in", "屏幕对角线（英寸）", 0, 100),
                         ("target_size_cm", "方块边长（厘米）", 2, 15),
                         ("viewing_distance_cm", "实测观看距离（厘米）", 0, 300)]),
        )
        for title, fields in groups:
            page = QWidget()
            form = QFormLayout(page)
            form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
            for name, label, minimum, maximum in fields:
                spin = QSpinBox() if name in {'total_trials','block_trials','practice_per_condition'} else QDoubleSpinBox()
                spin.setRange(minimum, maximum)
                if isinstance(spin, QDoubleSpinBox):
                    spin.setDecimals(1)
                    spin.setSingleStep(.5)
                    if name.endswith('_sec'):
                        spin.setSuffix(" 秒")
                    elif minimum == 0:
                        spin.setSpecialValueText('未测量')
                row = QWidget()
                line = QHBoxLayout(row)
                line.setContentsMargins(0, 0, 0, 0)
                line.addWidget(spin, 1)
                default = QLabel()
                default.setObjectName("muted")
                line.addWidget(default)
                form.addRow(label, row)
                self.protocol_fields[name] = spin
                self.protocol_defaults[name] = default
                self.protocol_rows[name] = (form, row)
            tabs.addTab(page, title)
        self._protocol_tabs = tabs
        self.protocol_hint = QLabel()
        self.protocol_hint.setWordWrap(True)
        body.addWidget(self.protocol_hint)
        buttons = QHBoxLayout()
        reset = QPushButton("恢复本范式默认值")
        reset.clicked.connect(self._reset_protocol)
        save = QPushButton("保存实验设置")
        save.clicked.connect(self._save_protocol_settings)
        buttons.addWidget(reset)
        buttons.addWidget(save)
        body.addLayout(buttons)
        self.protocol_settings_status = QLabel(load_message)
        self.protocol_settings_status.setWordWrap(True)
        self.protocol_settings_status.setObjectName("muted")
        body.addWidget(self.protocol_settings_status)
        layout.addWidget(self.trial_group)
        self._display_protocol()

    def _remember_protocol(self):
        self._protocol_values[self._trial_paradigm].update({k: w.value() for k, w in self.protocol_fields.items()})

    def _display_protocol(self):
        default = AssessmentProtocol.defaults(self._trial_paradigm)
        for name, widget in self.protocol_fields.items():
            widget.setValue(self._protocol_values[self._trial_paradigm].get(name, getattr(default, name)))
            self.protocol_defaults[name].setText(f"默认 {getattr(default, name):g}")
        for name in ("total_trials", "block_trials"):
            self.protocol_fields[name].setMinimum(default.conditions)
            self.protocol_fields[name].setSingleStep(default.conditions)
        form, row = self.protocol_rows["prep_sec"]
        form.setRowVisible(row, self._trial_paradigm == "SSVEP")
        self._protocol_tabs.setTabVisible(3, self._trial_paradigm == 'SSVEP')
        self.protocol_hint.setText(f"总试次和每组试次填写 {default.conditions} 的倍数，各条件等量；末组可少于设定值。\n"
                                   "组间倒计时结束后需按空格继续；练习设 0 可关闭。静息基线每次独立采集。"
                                   + ('\nSSVEP 每组由低频到高频循环。八个方块位于九宫格外围并同时闪烁，8–15 Hz，间隔 1 Hz；屏幕尺寸未测量时，靶点按屏幕短边 20% 呈现。厘米值仅在填写屏幕尺寸后生效，观看距离请实测填写。' if self._trial_paradigm == 'SSVEP' else ''))

    def _trial_paradigm_changed(self):
        if not hasattr(self, "trial_group"):
            return
        self._remember_protocol()
        paradigm = self.paradigm_select.currentText()
        self.trial_group.setVisible(paradigm in self._protocol_values)
        if paradigm in self._protocol_values:
            self._trial_paradigm = paradigm
            self._display_protocol()

    def _assessment_protocol(self):
        if self.paradigm_select.currentText() not in self._protocol_values:
            return None
        self._remember_protocol()
        return AssessmentProtocol.from_dict(self._protocol_values[self._trial_paradigm])

    def _reset_protocol(self):
        self._protocol_values[self._trial_paradigm] = AssessmentProtocol.defaults(self._trial_paradigm).to_dict()
        self._display_protocol()
        self.protocol_settings_status.setText("已恢复本范式默认值；点击保存后下次启动生效。")

    def _save_protocol_settings(self):
        self._remember_protocol()
        try:
            values = {p: AssessmentProtocol.from_dict(v).to_dict() for p, v in self._protocol_values.items()}
            self._protocol_settings_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._protocol_settings_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(values, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self._protocol_settings_path)
            self.protocol_settings_status.setText("两种范式的设置已分别保存。")
        except (OSError, ValueError) as exc:
            self.protocol_settings_status.setText(f"未保存：{exc}")
