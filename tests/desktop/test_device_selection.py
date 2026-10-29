"""Exercise the actual desktop selection paths without connecting hardware."""
import os
import subprocess
import sys


def test_device_routing_visibility_and_source_isolation():
    script = r'''
import numpy as np
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from neuroscope_eeg.desktop import app as desktop
from neuroscope_eeg.acquisition.simulated import SimulatedSource

app = QApplication([])
window = desktop.NeuroScopeWindow()
window.show()
app.processEvents()
assert isinstance(window._build_source(), SimulatedSource)
expected = {
    "博睿康 Neuracle": "neuracle", "强脑 BrainCo": "brainco",
    "公司 OmniBCI": "omnibci", "通用 LSL": "lsl",
    "EMOTIV 外部录制": "emotiv_external", desktop.TD10_SOURCE_LABEL: "td10_lsl",
}
with patch.object(desktop, "SimulatedSource", side_effect=AssertionError("simulator must not be called")):
    for label, kind in expected.items():
        window.source_select.setCurrentText(label)
        source = window._build_source()
        assert source.metadata.source_type == kind, label
        if kind == "brainco":
            assert source.backend.__class__.__module__.endswith("vendor.brainco_acquirer")
            assert source.backend._signal_source == "NORMAL"
        if kind == "emotiv_external":
            assert source.metadata.n_channels == 0
        for group, owner in [(window.neuracle_group, "博睿康 Neuracle"),
                             (window.brainco_group, "强脑 BrainCo"),
                             (window.td10_group, desktop.TD10_SOURCE_LABEL),
                             (window.replay_group, "NPZ 回放")]:
            assert group.isVisible() == (label == owner), (label, owner)
        for widget, owner in [(window.omni_endpoint, "公司 OmniBCI"),
                              (window.omni_type, "公司 OmniBCI"),
                              (window.impedance_button, "公司 OmniBCI"),
                              (window.lsl_source_id, "通用 LSL"),
                              (window.emotiv_receive_port, "EMOTIV 外部录制"),
                              (window.emotiv_recording_confirmed, "EMOTIV 外部录制"),
                              (window.emotiv_edf_button, "EMOTIV 外部录制")]:
            window.navigation.setCurrentRow(3 if widget is window.emotiv_edf_button else 0)
            assert widget.isVisible() == (label == owner), (label, owner)
        window.navigation.setCurrentRow(0)
        assert window.timing_mode.model().item(2).isEnabled() == (kind == "omnibci")
        if kind != "omnibci":
            window.timing_mode.setCurrentIndex(2)
            assert window.timing_mode.currentData() != "omni_hardware"
    window.source_select.addItem("unknown-device")
    window.source_select.setCurrentText("unknown-device")
    try:
        window._build_source()
    except ValueError:
        pass
    else:
        raise AssertionError("unknown source must fail closed")

window.source_select.setCurrentText("强脑 BrainCo")
assert not window.brainco_ip.isVisible()
window.brainco_auto.setChecked(False)
assert window.brainco_ip.isVisible() and window.brainco_ip.isEnabled()
window._set_controls_enabled(False)
assert not window.brainco_ip.isEnabled()
window._set_controls_enabled(True)
window.profile_path.setText("brainco-profile.json")
window._apply_wave_data(np.ones((2, 100)), ("C3", "C4"), 250.)
window.decoder_result.setText("old result")
window.source_select.setCurrentText("公司 OmniBCI")
assert window.profile_path.text() == ""
assert all(curve.getData()[0] is None or len(curve.getData()[0]) == 0 for curve in window.wave_curves)
assert window.decoder_result.text() == "尚未解码"
window._set_controls_enabled(False)
assert not window.impedance_button.isEnabled()
window._set_controls_enabled(True)
window.source_select.setCurrentText("强脑 BrainCo")
assert window.profile_path.text() == "brainco-profile.json"
window.source_select.setCurrentText("EMOTIV 外部录制")
assert not window.sfreq.isVisible() and not window.channels.isVisible()
window.emotiv_recording_confirmed.setChecked(True)
window.source_select.setCurrentText("模拟")
assert window.timing_mode.currentData() == "lsl_only"
window.source_select.setCurrentText("EMOTIV 外部录制")
assert not window.emotiv_recording_confirmed.isChecked()
window.source_select.setCurrentText("NPZ 回放")
assert window.replay_group.isVisible()
assert not window.sfreq.isVisible() and not window.channels.isVisible()
window.close()
app.processEvents()
'''
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    environment.pop("QT_PLUGIN_PATH", None)
    environment.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    result = subprocess.run([sys.executable, "-c", script], check=False, env=environment,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
