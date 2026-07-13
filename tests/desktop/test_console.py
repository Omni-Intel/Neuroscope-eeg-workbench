import os
import subprocess
import sys

import pytest


@pytest.mark.skipif(sys.platform == "darwin", reason="Qt platform plugins are flaky in repeated macOS test subprocesses")
def test_console_creates_curves_once_and_defaults_to_30_fps() -> None:
    script = """
import numpy as np
from PySide6.QtWidgets import QApplication
from neuroscope_eeg.desktop.app import MAX_VISIBLE_CHANNELS, NeuroScopeWindow

app = QApplication([])
window = NeuroScopeWindow()
curve_ids = [id(curve) for curve in window.wave_curves]
names = tuple(f"C{i}" for i in range(32))
window._apply_wave_data(np.ones((32, 100), dtype=np.float32), names, 250.0)
window._apply_wave_data(np.zeros((32, 100), dtype=np.float32), names, 250.0)
assert window.target_fps.currentData() == 30
assert len(window.wave_curves) == MAX_VISIBLE_CHANNELS == 32
assert [id(curve) for curve in window.wave_curves] == curve_ids
window.close()
app.processEvents()
"""
    environment = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    environment.pop("QT_PLUGIN_PATH", None)
    environment.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr
