import os
import subprocess
import sys


def test_desktop_simulation_records_two_independent_runs(tmp_path):
    script = r'''
import json, sys, time
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton
from neuroscope_eeg.desktop.app import NeuroScopeWindow, _application_font, _application_stylesheet
from neuroscope_eeg.paradigms.base import PARADIGMS
from neuroscope_eeg.core.models import ConnectionState

app = QApplication([])
app.setFont(_application_font(app))
app.setStyleSheet(_application_stylesheet())
window = NeuroScopeWindow()
assert sum(b.text() == '重试 EDF 交付与报告' for b in window.findChildren(QPushButton)) == 1
def unexpected(*args, **kwargs):
    raise AssertionError(str(args))
QMessageBox.critical = unexpected
QMessageBox.warning = unexpected
QMessageBox.information = unexpected
window.recording_root.setText(sys.argv[1])
window.participant_id.setText("00000001")
window.paradigm_code.setText("MI-20261027")
window.unique_name.setText("integration-mi")
window.paradigm_select.setCurrentText("运动想象")
window.protocol_preset.setCurrentText("完整采集")
assert window.paradigm_select.count() == len(PARADIGMS) == 10
window._start_session()
deadline=time.monotonic()+5
while window.controller.samples_received < 10 and time.monotonic()<deadline:
    app.processEvents(); time.sleep(.01)
assert window.controller.state is ConnectionState.RUNNING
paths=[]
for attempt in range(2):
    window._start_stimulus()
    assert window._session_recorder is not None
    assert not window.paradigm_select.isEnabled()
    until=time.monotonic()+.3
    while time.monotonic()<until:
        app.processEvents(); time.sleep(.01)
    paths.append(window._session_recorder.session_dir)
    window._stop_stimulus()
    app.processEvents()
    assert window._session_recorder is None
    info=json.loads((paths[-1]/"run.json").read_text(encoding="utf-8"))
    assert info["paradigm_code"] == info["unique_name"] == "MI-20261030"
    config=json.loads((paths[-1]/"config.json").read_text(encoding="utf-8"))
    assert config["experiment_metadata"]["unique_name"] == "MI-20261030"
    assert info["samples"] > 0
    assert info["recording_status"] == "aborted"
    assert (paths[-1]/"analysis/local_quality.json").exists()
assert paths[0] != paths[1]
deadline = time.monotonic() + 75
while (window._report_process is not None or window._report_queue) and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.02)
assert window._report_process is None and not window._report_queue, window.report_status.text()
for path in paths:
    reports = list(Path(sys.argv[1]).glob("Reports/*/" + path.name + "/*/*.docx"))
    assert len(reports) == 1, window.report_status.text()
    packages = list(Path(sys.argv[1]).glob("data/*/" + path.name))
    assert len(packages) == 1, window.delivery_status.text()
    assert len(list(packages[0].rglob("*.edf"))) == 1
    assert not list(Path(sys.argv[1]).glob("data/**/*.json.tmp"))
    assert not list(Path(sys.argv[1]).glob("Reports/**/*.csv"))
    assessment = json.loads((path / "analysis" / reports[0].parent.name / "assessment.json").read_text(encoding="utf-8"))
    assert assessment["run"]["recording_status"] == "aborted"
    assert assessment["task"]["status"] == "pending"
    assert assessment["task"]["collection_only"] is True
    assert not assessment["task"]["trials"]  # Aborted on the instructions page, no invented trials.
assert window._latest_report.name in window.report_status.text()
assert str(window._latest_report.parent) in window.report_status.text()
window.resize(1100, 700)
window.navigation.setCurrentRow(3)
window.show()
for _ in range(5):
    app.processEvents()
window.grab().save(str(Path(sys.argv[1]) / 'report-display.png'))
assert window.report_status.width() < 550, (window.size().toTuple(), window.report_status.size().toTuple())
assert window.report_status.height() >= window.report_status.heightForWidth(window.report_status.width())
window.close()
app.processEvents()
'''
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8"}
    environment.pop("QT_PLUGIN_PATH", None)
    environment.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=environment,
                            capture_output=True, text=True, encoding="utf-8", timeout=100, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
