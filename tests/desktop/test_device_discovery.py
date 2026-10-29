import os
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock


def test_company_discovery_only_enumerates_candidates(monkeypatch):
    from neuroscope_eeg.desktop.device_discovery import discover_omni
    discover = Mock(return_value=[SimpleNamespace(endpoint="ble://key", name="Board", device_type="stm32")])
    connect = Mock(side_effect=AssertionError("scan must not connect"))
    monkeypatch.setitem(sys.modules, "omnibci", SimpleNamespace(Board=SimpleNamespace(discover=discover, connect=connect)))
    assert discover_omni("ble", "stm32")[0]["endpoint"] == "ble://key"
    discover.assert_called_once_with(transport="ble", device_type="stm32", timeout=6)
    connect.assert_not_called()


def test_discovery_ui_selection_and_lifecycle():
    script = '''
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QComboBox, QCheckBox, QDialogButtonBox
from neuroscope_eeg.desktop.app import NeuroScopeWindow
from neuroscope_eeg.desktop import device_discovery as discovery
app = QApplication([])
w = NeuroScopeWindow(); w.show()
w.source_select.setCurrentText("公司 OmniBCI")
assert w.omni_scan_button.isVisible() and not w.emotiv_scan_button.isVisible()
received = []
def scan():
    time.sleep(.03)
    return ["candidate"]
w._start_device_scan(scan, received.extend)
assert not w.source_select.isEnabled() and not w.start_button.isEnabled()
w._set_controls_enabled(True)
assert not w.source_select.isEnabled()
deadline = time.monotonic() + 3
while w._scan_worker is not None and time.monotonic() < deadline:
    app.processEvents(); time.sleep(.005)
assert received == ["candidate"] and w.source_select.isEnabled()
discovery.QInputDialog.getItem = lambda *a: (a[3][1], True)
w._select_omni([{"endpoint":"serial://COM1", "name":"one", "type":"esp32"},
                {"endpoint":"serial://COM8", "name":"two", "type":"esp32"}])
assert w.omni_endpoint.text() == "serial://COM8" and w.controller is None
w.source_select.setCurrentText("EMOTIV 外部录制")
assert w.emotiv_scan_button.isVisible() and not w.omni_scan_button.isVisible()
ports = [{"port": f"COM{i}", "description":"pair", "identity":(str(i), None), "blocked":False} for i in (11,12)]
discovery.marker_ports = lambda: ports
def select():
    d = app.activeModalWidget()
    a, b = d.findChildren(QComboBox)
    buttons = d.findChild(QDialogButtonBox)
    assert not buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    a.setCurrentIndex(1); b.setCurrentIndex(1)
    confirmed = d.findChild(QCheckBox); confirmed.setChecked(True)
    assert not buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    b.setCurrentIndex(2)
    assert not confirmed.isChecked()
    confirmed.setChecked(True)
    assert buttons.button(QDialogButtonBox.StandardButton.Ok).isEnabled()
    d.accept()
QTimer.singleShot(0, select)
w._select_emotiv_ports(ports)
assert w.trigger_port.text() == "COM11" and w.emotiv_receive_port.text() == "COM12"
assert not w.emotiv_recording_confirmed.isChecked()
w.close(); app.processEvents()
'''
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    environment.pop("QT_PLUGIN_PATH", None)
    environment.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    result = subprocess.run([sys.executable, "-c", script], check=False, env=environment,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
