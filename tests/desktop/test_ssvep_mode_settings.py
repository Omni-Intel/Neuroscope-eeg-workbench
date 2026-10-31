import os
import subprocess
import sys


def test_ui_mode_migration_save_reload_and_real_painter(tmp_path):
    script = r'''
import json, sys
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout
from PySide6.QtCore import QRect
from PySide6.QtGui import QImage, QPainter
from neuroscope_eeg.desktop.protocol_settings import ProtocolSettings
from neuroscope_eeg.desktop.ssvep_presentation import FREQUENCIES, paint_single_target, target_layout, display_metadata
from neuroscope_eeg.protocol_config import AssessmentProtocol

app = QApplication([])
root = Path(sys.argv[1])
saved = {'SSVEP': replace(AssessmentProtocol.defaults('SSVEP'), ssvep_mode='simultaneous_eight_v3').to_dict()}
(root/'protocol-settings.json').write_text(json.dumps(saved), encoding='utf-8')
class Panel(QWidget, ProtocolSettings):
    def __init__(self):
        super().__init__()
        self._settings_path = root/'settings.json'
        self._add_protocol_settings(QVBoxLayout(self))
first = Panel()
assert first.ssvep_mode_select.currentData() == 'sequential_eight_v5'
assert '每次只闪当前目标' in first.protocol_hint.text()
first.ssvep_mode_select.setCurrentIndex(1)
first._save_protocol_settings()
second = Panel()
assert second.ssvep_mode_select.currentData() == 'simultaneous_eight_v3'
assert second._protocol_values['SSVEP']['version'] == 'guided-assessment-v3'
second.ssvep_mode_select.setCurrentIndex(0)
second._save_protocol_settings()
third = Panel()
assert third.ssvep_mode_select.currentData() == 'sequential_eight_v5'
assert third._protocol_values['SSVEP']['version'] == 'guided-assessment-v5'
plan = AssessmentProtocol.defaults('SSVEP')
window = SimpleNamespace(_guided=SimpleNamespace(plan=plan, step=SimpleNamespace(phase='flicker')),
    width=lambda: 1200, height=lambda: 800, rect=lambda: QRect(0,0,1200,800),
    _ssvep_target_index=4, frame_index=0, _ssvep_flicker_frame=0, refresh_hz=75,
    ssvep_frequencies=FREQUENCIES, devicePixelRatioF=lambda: 1)
for sequential in (True, False):
    window._guided.plan = plan if sequential else replace(plan, ssvep_mode='simultaneous_eight_v3')
    canvas = QImage(1200,800,QImage.Format.Format_RGB32)
    painter = QPainter(canvas)
    paint_single_target(window,painter)
    painter.end()
    assert canvas.pixelColor(600,400).red() > 200
    assert canvas.pixelColor(605,400).red() > 200
    assert canvas.pixelColor(600,405).red() > 200
    assert canvas.pixelColor(605,405).red() < 30
    boxes, _ = target_layout(1200,800,0,plan.target_size_cm)
    for i,(x,y,w,h) in enumerate(boxes):
        assert canvas.pixelColor(x+w//2,y+h//2).red() == (255 if not sequential or i==4 else 30)
    canvas.save(str(root/('single.png' if sequential else 'simultaneous.png')))
    meta = display_metadata(window, window._guided.plan, SimpleNamespace(name=lambda: 'fixture'))
    assert meta['active_targets_per_trial'] == (1 if sequential else 8)
    assert meta['mode'] == ('sequential_eight' if sequential else 'simultaneous_eight')
'''
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}
    env.pop('QT_PLUGIN_PATH', None)
    env.pop('QT_QPA_PLATFORM_PLUGIN_PATH', None)
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], env=env,
                            capture_output=True, text=True, timeout=40)
    assert result.returncode == 0, result.stderr
