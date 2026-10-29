import os
import subprocess
import sys


def test_navigation_preserves_live_session_and_stimulus():
    script = '''
import time
from PySide6.QtWidgets import QApplication
from neuroscope_eeg.desktop.app import NeuroScopeWindow, _application_stylesheet

app = QApplication([])
app.setStyleSheet(_application_stylesheet())
window = NeuroScopeWindow()
window.resize(1100, 700)
window.show()
window.participant_id.setText("00000017")
window.protocol_fields["total_trials"].setValue(28)
window._start_session()
deadline = time.monotonic() + 3
while window.controller.samples_received == 0 and time.monotonic() < deadline:
    app.processEvents()
    time.sleep(.01)
controller = window.controller
assert controller.samples_received > 0
source = controller.source
curves = [id(curve) for curve in window.wave_curves]
window.stimulus_window.start_protocol("SSVEP", app.primaryScreen())
before = controller.samples_received
for index in (1, 2, 3, 4, 0, 2):
    window.navigation.setCurrentRow(index)
    app.processEvents()
    assert window.pages.currentIndex() == index
    assert window.paradigm_select.isVisible() == (index == 1)
    assert window.controller is controller and controller.source is source
    assert controller.worker_alive
    assert window.stimulus_window.isVisible()
    assert window.participant_id.text() == "00000017"
    assert window.protocol_fields["total_trials"].value() == 28
    assert "00000017" in window.experiment_context.text()
    assert [id(curve) for curve in window.wave_curves] == curves
    for button, page in ((window.start_button, 0), (window.stop_button, 0), (window.save_connection_button, 0),
                         (window.stimulus_start_button, 1), (window.stimulus_stop_button, 1)):
        assert button.isVisible() == (index == page)
        if index != page:
            continue
        rect = button.rect()
        assert window.rect().contains(button.mapTo(window, rect.topLeft()))
        assert window.rect().contains(button.mapTo(window, rect.bottomRight()))
    time.sleep(.03)
assert controller.samples_received > before
window.stimulus_window.stop_protocol()
window._stop_session()
window.close()
app.processEvents()
'''
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    environment.pop("QT_PLUGIN_PATH", None)
    environment.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    result = subprocess.run([sys.executable, "-c", script], check=False, env=environment,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
