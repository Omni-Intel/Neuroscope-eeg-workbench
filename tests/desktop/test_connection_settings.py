import os
import subprocess
import sys


def run_desktop(script):
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    environment.pop("QT_PLUGIN_PATH", None)
    environment.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    result = subprocess.run([sys.executable, "-c", script], check=False, env=environment,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr


def test_connection_preferences_are_per_device_and_do_not_restore_confirmation(tmp_path):
    run_desktop(f"""
import json
from pathlib import Path
from PySide6.QtWidgets import QApplication
from neuroscope_eeg.desktop.app import NeuroScopeWindow

app = QApplication([])
path = Path({str(tmp_path / "connections.json")!r})
w = NeuroScopeWindow(settings_path=path)
w.participant_id.setText("87654321")
w.source_select.setCurrentText("博睿康 Neuracle")
w.neuracle_host.setText("192.168.2.99")
w.neuracle_port.setValue(9988)
w.channels.setValue(16)
w.sfreq.setValue(500)
w.source_select.setCurrentText("强脑 BrainCo")
assert w.controller is None  # Selecting a device does not start discovery or connect.
w.brainco_auto.setChecked(False)
w.brainco_ip.setText("192.168.2.33")
w.brainco_port.setValue(7788)
w.source_select.setCurrentText("EMOTIV 外部录制")
w.trigger_port.setText("COM7")
w.emotiv_receive_port.setText("COM8")
w.emotiv_recording_confirmed.setChecked(True)
w._save_connection_settings()
saved = path.read_text(encoding="utf-8")
assert "87654321" not in saved
assert "emotiv_recording_confirmed" not in saved
w.close()
w = NeuroScopeWindow(settings_path=path)
assert w.source_select.currentText() == "EMOTIV 外部录制"
assert "EMOTIV 外部录制" in w.experiment_context.text()
assert w.trigger_port.text() == "COM7" and w.emotiv_receive_port.text() == "COM8"
assert w.controller is None and not w.emotiv_recording_confirmed.isChecked()
assert not w.stimulus_start_button.isEnabled()
w.source_select.setCurrentText("博睿康 Neuracle")
assert w.neuracle_host.text() == "192.168.2.99" and w.neuracle_port.value() == 9988
assert w.channels.value() == 16 and w.sfreq.value() == 500
w.source_select.setCurrentText("强脑 BrainCo")
assert not w.brainco_auto.isChecked() and w.brainco_ip.isEnabled()
assert w.brainco_ip.text() == "192.168.2.33" and w.brainco_port.value() == 7788
w.close()
path.write_text("invalid json", encoding="utf-8")
w = NeuroScopeWindow(settings_path=path)
assert "配置未恢复" in w.settings_status.text()
assert w.controller is None
w.close()
""")


def test_connection_display_requires_samples_and_marks_external_confirmation(tmp_path):
    run_desktop(f"""
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from neuroscope_eeg.desktop.app import NeuroScopeWindow
from neuroscope_eeg.core.models import ConnectionState

app = QApplication([])
w = NeuroScopeWindow(settings_path=Path({str(tmp_path / "absent.json")!r}))
metadata = SimpleNamespace(n_channels=8, sfreq=250, source_type="neuracle")
c = SimpleNamespace(error=None, state=ConnectionState.CONNECTING, samples_received=0,
    source=SimpleNamespace(metadata=metadata), last_data_age_sec=lambda: None)
w.controller = c
w._refresh_connection_state()
assert w.state_value.text() == "正在连接" and not w.stimulus_start_button.isEnabled()
c.state = ConnectionState.RUNNING
w._refresh_connection_state()
assert w.state_value.text() == "等待数据" and not w.stimulus_start_button.isEnabled()
c.samples_received = 100
c.last_data_age_sec = lambda: .1
w._refresh_connection_state()
assert w.state_value.text() == "已接收数据" and w.stimulus_start_button.isEnabled()
assert "100" in w.connection_detail.text()
c.last_data_age_sec = lambda: 3
w._refresh_connection_state()
assert w.state_value.text() == "数据暂未更新" and not w.stimulus_start_button.isEnabled()
c.error = "connection lost"
w._refresh_connection_state()
assert w.state_value.text() == "连接 / 数据异常" and not w.stimulus_start_button.isEnabled()
w.controller = None
w.source_select.setCurrentText("EMOTIV 外部录制")
c.error = None
c.samples_received = 0
w.controller = c
w._refresh_connection_state()
assert w.state_value.text() == "外部录制待人工确认" and not w.stimulus_start_button.isEnabled()
w.emotiv_recording_confirmed.setChecked(True)
w._refresh_connection_state()
assert w.state_value.text() == "外部录制已人工确认" and w.stimulus_start_button.isEnabled()
assert "没有本地 EEG 收样验证" in w.connection_detail.text()
w.controller = None
w.close()
""")
