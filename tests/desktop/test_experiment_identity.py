from test_connection_settings import run_desktop


def test_selected_experiment_populates_identity_without_changing_other_parameters(tmp_path):
    run_desktop(f'''
from pathlib import Path
from PySide6.QtWidgets import QApplication
from neuroscope_eeg.desktop.app import NeuroScopeWindow
app = QApplication([])
w = NeuroScopeWindow(settings_path=Path({str(tmp_path / "connections.json")!r}))
assert w.paradigm_select.count() == 10
for paradigm, code in (("SSVEP", "SSVEP-20261030"), ("运动想象", "MI-20261030")):
    w.paradigm_select.setCurrentText(paradigm)
    assert w.paradigm_code.text() == w.unique_name.text() == code
    assert w._metadata_path().is_file()
    w.protocol_fields["total_trials"].setValue(12)
    w.protocol_fields["task_sec"].setValue(6)
w.participant_id.setText("00000019")
w.recording_root.setText("D:/test-output")
w.paradigm_select.setCurrentText("情绪图片唤醒")
assert w.paradigm_code.text() == ""
w.paradigm_code.setText("EMO-20261020")
for paradigm, code in (("SSVEP", "SSVEP-20261030"), ("运动想象", "MI-20261030")):
    w.paradigm_select.setCurrentText(paradigm)
    assert w.paradigm_code.text() == w.unique_name.text() == code
    assert w.protocol_fields["total_trials"].value() == 12
    assert w.protocol_fields["task_sec"].value() == 6
w.paradigm_select.setCurrentText("情绪图片唤醒")
assert w.paradigm_code.text() == "EMO-20261020"
assert w.participant_id.text() == "00000019"
assert w.recording_root.text() == "D:/test-output"
assert w.controller is None
w.close()
''')
