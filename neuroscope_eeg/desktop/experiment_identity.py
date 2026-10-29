"""Local, per-paradigm metadata editor; never invent registered platform IDs."""
from pathlib import Path

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLineEdit, QMessageBox, QPlainTextEdit

from neuroscope_eeg.io.session_recorder import _PARADIGM_SLUGS
from neuroscope_eeg.project_metadata import load_metadata, save_metadata, validate_metadata


class ExperimentIdentity:
    def _metadata_path(self):
        return Path(__file__).resolve().parents[2] / "experiments" / _PARADIGM_SLUGS[self.paradigm_select.currentText()] / "metadata.toml"

    def _refresh_experiment_identity(self):
        if not hasattr(self, "unique_name"):
            return
        paradigm = self.paradigm_select.currentText()
        previous = getattr(self, "_identity_previous_paradigm", None)
        if not hasattr(self, "_identity_codes"):
            self._identity_codes = {}
        if previous is not None and previous != paradigm:
            self._identity_codes[previous] = self.paradigm_code.text()
        if previous != paradigm:
            # Do not carry the automatic MI/SSVEP code into another paradigm.
            self.paradigm_code.setText(self._identity_codes.get(paradigm, ""))
        self._identity_previous_paradigm = paradigm
        path = self._metadata_path()
        try:
            value = load_metadata(path) if path.exists() else None
            self.unique_name.setText(value["unique_name"] if value else "")
            if value and paradigm in {"SSVEP", "运动想象"}:
                # These two code/name pairs were explicitly chosen by the user.
                self.paradigm_code.setText(value["unique_name"])
        except (OSError, ValueError):
            self.unique_name.clear()

    def _edit_experiment(self):
        path = self._metadata_path()
        try:
            value = load_metadata(path) if path.exists() else {}
        except ValueError as exc:
            QMessageBox.warning(self, "实验信息无效", str(exc))
            return
        dialog = QDialog(self)
        dialog.setWindowTitle("建立 / 编辑本范式实验信息")
        form = QFormLayout(dialog)
        full_name = QLineEdit(value.get("full_name", self.paradigm_select.currentText()))
        unique = QLineEdit(value.get("unique_name", ""))
        unique.setPlaceholderText("如 SSVEP-20261022；使用实验建立日期，保存后保持稳定")
        description = QPlainTextEdit(value.get("description", ""))
        form.addRow("完整实验名称", full_name)
        form.addRow("固定唯一名称", unique)
        form.addRow("实验目的与任务简介", description)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(dialog.reject)
        def save():
            try:
                candidate = validate_metadata({"full_name": full_name.text().strip(), "unique_name": unique.text().strip(),
                                               "description": description.toPlainText().strip()})
                if value and candidate["unique_name"] != value["unique_name"]:
                    raise ValueError("既有实验唯一名称保持稳定；创建另一实验应使用独立配置，不能直接改写身份")
                # Prevent two paradigms silently sharing an identity.
                for other in path.parent.parent.glob("*/metadata.toml"):
                    if other != path and load_metadata(other)["unique_name"] == candidate["unique_name"]:
                        raise ValueError("该唯一名称已由另一范式使用")
                save_metadata(path, candidate)
                self.unique_name.setText(candidate["unique_name"])
                dialog.accept()
            except (OSError, ValueError) as exc:
                QMessageBox.warning(dialog, "未保存", str(exc))
        buttons.accepted.connect(save)
        form.addRow(buttons)
        dialog.resize(560, 340)
        dialog.exec()

    def _experiment_for_recording(self):
        path = self._metadata_path()
        if path.exists():
            value = load_metadata(path)
        elif self.controller.source.metadata.source_type in {"simulated", "simulator", "replay", "npz_replay"}:
            value = {"full_name": self.paradigm_select.currentText() + "模拟流程", "unique_name": "SIM" + chr(65 + list(_PARADIGM_SLUGS).index(self.paradigm_select.currentText())) + "-20261029",
                     "description": "本地软件流程验证；不是正式实验登记信息"}
        else:
            raise ValueError("请先点击“建立 / 编辑实验信息”，填写固定编号和简介；平台范式代码仍需单独核对")
        self.unique_name.setText(value["unique_name"])
        return value
