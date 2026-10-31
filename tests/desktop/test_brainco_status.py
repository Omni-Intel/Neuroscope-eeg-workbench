import os
import subprocess
import sys


def test_brainco_status_distinguishes_ack_and_receipt_in_real_ui():
    script = '''
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication
from neuroscope_eeg.desktop.app import NeuroScopeWindow
from neuroscope_eeg.acquisition.devices import DemoSource
from neuroscope_eeg.core.session import SessionController
app = QApplication([])
window = NeuroScopeWindow()
backend = SimpleNamespace(metadata=SimpleNamespace(sfreq=250, n_channels=32),
    trigger_sync_status={"state": "unconfirmed", "error": "ack timeout"})
source = DemoSource(backend, "brainco")
window.controller = SessionController(source)
window._update_status()
assert "未获确认" in window.data_value.text()
assert window.data_value.toolTip() == "ack timeout"
source._received_trigger_events = 2
backend.trigger_sync_status = {"state": "acknowledged", "error": ""}
window._update_status()
assert "已确认开启上报" in window.data_value.text()
assert "已接收 2 条" in window.data_value.text()
assert "物理同步未验证" in window.data_value.text()
assert window.data_value.toolTip() == ""
window.controller = None
window.close()
'''
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    env.pop("QT_PLUGIN_PATH", None)
    env.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    result = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
