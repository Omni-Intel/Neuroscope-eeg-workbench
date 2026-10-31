"""Optional user-supplied acquisition facts, without requiring hand-written JSON."""
import shutil
import uuid

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QMessageBox

from neuroscope_eeg.acquisition.devices import read_profile
from neuroscope_eeg.io.native_recording import write_json


def edit_profile(window):
    if window.controller is not None:
        QMessageBox.information(window, '请先断开连接', '修改采集信息前请先结束实验并断开连接。')
        return
    try:
        profile = read_profile(window.profile_path.text())
    except (ValueError, OSError) as exc:
        QMessageBox.warning(window, '配置无法读取', str(exc))
        return
    dialog = QDialog(window)
    dialog.setWindowTitle('Omni 采集信息')
    form = QFormLayout(dialog)
    note = QLabel('连接后自动读取设备类型、通道数、250 Hz、μV、增益及采集模式。\n'
                  'EDF 使用核实后的 SDK 标称量程；未填写的信息记为未记录，不阻止数据导出。\n'
                  '电极位置和分析确认仍由独立分析配置提供，不从 CH 编号推断。')
    note.setWordWrap(True)
    form.addRow(note)
    reference = QLineEdit('' if profile.get('eeg_reference', 'n/a') == 'n/a' else profile['eeg_reference'])
    reference.setPlaceholderText('可选：填写实际参考接法；不知道可留空')
    mains = QComboBox()
    mains.addItems(['未记录', '50 Hz', '60 Hz'])
    mains.setCurrentIndex({50: 1, 60: 2}.get(profile.get('power_line_frequency'), 0))
    form.addRow('参考接法', reference)
    form.addRow('环境工频', mains)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
    form.addRow(buttons)
    buttons.accepted.connect(dialog.accept)
    buttons.rejected.connect(dialog.reject)
    if dialog.exec() != QDialog.DialogCode.Accepted:
        return
    profile.update(eeg_reference=reference.text().strip() or 'n/a',
                   power_line_frequency=['n/a', 50, 60][mains.currentIndex()])
    # Changing acquisition facts invalidates any previous global analysis confirmation.
    profile['confirmed'] = False
    path = window._settings_path.parent / ('omni-' + window.omni_type.currentText() + '-profile.json')
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix('.' + uuid.uuid4().hex + '.backup.json'))
    write_json(path, profile)
    window.profile_path.setText(str(path))
    window._save_connection_settings()
