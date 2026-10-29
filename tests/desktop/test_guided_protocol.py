from collections import Counter
from dataclasses import replace
import os
import subprocess
import sys

import pytest

from neuroscope_eeg.protocol_config import AssessmentProtocol
from neuroscope_eeg.desktop.guided_protocol import GuidedFlow, protocol_steps


@pytest.mark.parametrize("paradigm", ["SSVEP", "运动想象"])
def test_balanced_blocks_baselines_and_wait_gates(paradigm):
    default = AssessmentProtocol.defaults(paradigm)
    plan = replace(default, total_trials=default.conditions * 5, block_trials=default.conditions * 2)
    steps = protocol_steps(plan)
    formal = [s for s in steps if s.phase == "rest" and not s.payload["is_practice"]]
    assert len(formal) == plan.total_trials
    for block, count in [(1, 2), (2, 2), (3, 1)]:
        assert Counter(s.payload["condition_index"] for s in formal if s.payload["block"] == block) == dict.fromkeys(range(plan.conditions), count)
    assert Counter(s.phase for s in steps)["baseline_eyes_open"] == 1
    assert Counter(s.phase for s in steps)["baseline_eyes_closed"] == 1
    assert len([s for s in steps if s.phase == "rest" and s.payload["is_practice"]]) == plan.conditions * plan.practice_per_condition
    assert sum(s.duration or 0 for s in steps) == plan.minimum_duration_sec
    flow = GuidedFlow(plan)
    assert not flow.ready(1000000)  # No unseen screen may be timed out.
    flow.acknowledge_frame(0)
    assert not flow.ready(1000000)  # Instructions always require a key.
    while flow.step.phase != "block_rest":
        flow.advance()
    assert not flow.ready(1000000)
    flow.acknowledge_frame(50)
    assert not flow.ready(109.9)
    assert flow.ready(110)
    flow.advance()
    flow.acknowledge_frame(110)
    assert flow.step.phase == "block_ready" and not flow.ready(1000000)


@pytest.mark.parametrize("changes", [{"total_trials": 7}, {"block_trials": 5}, {"task_sec": 2},
                                     {"fixation_sec": 0}, {"eyes_closed_sec": 0}, {"cue_sec": float("nan")}])
def test_invalid_plans_rejected(changes):
    with pytest.raises(ValueError):
        replace(AssessmentProtocol.defaults("SSVEP"), **changes).validate()


def test_fullscreen_guided_events_settings_and_restart(tmp_path):
    script = r'''
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sys
from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QKeyEvent
from PySide6.QtWidgets import QApplication
from neuroscope_eeg.desktop.app import NeuroScopeWindow
from neuroscope_eeg.desktop.stimulus import StimulusWindow
from neuroscope_eeg.protocol_config import AssessmentProtocol
app = QApplication([])
audio = SimpleNamespace(play_tone=Mock(), stop=lambda: None, close=lambda: None)
window = StimulusWindow(audio_player=audio)
with patch('time.monotonic', return_value=10.), patch('time.perf_counter', return_value=100.125):
    for paradigm in ('SSVEP', '运动想象'):
        window.paradigm = paradigm
        assert window._presentation_time() == 100.125
events = []
window.event_emitted.connect(events.append)
now = [100.]
def press(auto=False):
    window.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier, ' ', auto))
def release():
    window.keyReleaseEvent(QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier))
with patch('time.monotonic', side_effect=lambda: now[0]), patch('time.perf_counter', side_effect=lambda: now[0]):
    for paradigm in ('SSVEP', '运动想象'):
        events.clear()
        base = AssessmentProtocol.defaults(paradigm)
        plan = replace(base, total_trials=base.conditions*3, block_trials=base.conditions*2)
        window.start_protocol(paradigm, app.primaryScreen(), assessment_protocol=plan)
        assert window._guided.step.phase == 'instructions'
        first = True
        while window.timer.isActive():
            flow = window._guided
            index = flow.index
            now[0] += 500
            window._tick()
            assert flow.index == index  # Unpresented phase cannot be skipped.
            window._on_frame_swapped()
            if not window.timer.isActive(): break
            if flow.step.phase == 'baseline_eyes_closed':
                painter = Mock()
                assert window._paint_guided_screen(painter)
                texts = [str(call.args[-1]) for call in painter.drawText.call_args_list]
                assert any(f'{int(plan.eyes_closed_sec)} 秒' in text for text in texts)
                now[0] += 1
                painter.reset_mock()
                window._paint_guided_screen(painter)
                assert any(f'{int(plan.eyes_closed_sec)-1} 秒' in str(call.args[-1])
                           for call in painter.drawText.call_args_list)
            now[0] += .3
            if flow.step.duration is None:
                press()
                next_index = flow.index
                window._on_frame_swapped()
                now[0] += .3
                press(True); press()
                assert flow.index == next_index  # Holding Space never advances twice.
                release()
                if first:
                    window.grab().save(str(Path(sys.argv[1]) / 'guidance.png'))
                    first = False
                # The next iteration must begin with an unacknowledged step.
                if flow.presented_at is not None:
                    if flow.step.duration is None:
                        press(); release()
                    else:
                        now[0] += flow.step.duration
                        window._tick()
            else:
                press(); release()
                assert flow.index == index
                now[0] += flow.step.duration
                window._tick()
        assert window._guided_ended and window.stop_reason == 'completed'
        assert window.summary()['completed_formal_trials'] == plan.total_trials
        assert len([e for e in events if e.phase == 'trial_complete' and not e.payload['is_practice']]) == plan.total_trials
        assert len([e for e in events if e.phase == 'trial_complete' and e.payload['is_practice']]) == plan.conditions*plan.practice_per_condition
        assert len([e for e in events if e.phase == 'baseline_eyes_open']) == 1
        assert len([e for e in events if e.phase == 'baseline_eyes_closed_end']) == 1
        assert all(e.hook_type == 'frame_swapped' for e in events if e.phase in {'flicker','cue','imagery','trial_complete','baseline_eyes_closed'})
        assert events[-1].phase == 'stop'
        assert events[-1].payload['display_timing']['clock'] == 'perf_counter'
        assert events[-1].payload['display_timing']['physical_onset_verified'] is False
        if paradigm == 'SSVEP':
            formal = [e for e in events if e.phase == 'flicker' and not e.payload['is_practice']]
            assert [e.payload['target_frequency'] for e in formal] == sorted(window.ssvep_frequencies) * 3
            start = next(e for e in events if e.phase == 'start').payload
            assert start['ssvep_condition_sequence'] == [0,1,2,3] * 3
            assert start['ssvep_display']['mode'] == 'single_target'
            assert start['ssvep_display']['target_size_cm_estimated'] is None
            for trial in formal:
                phases = [e.phase for e in events if e.payload.get('trial') == trial.payload['trial']]
                assert phases == ['fixation','cue','prep','flicker','rest','trial_complete']
        audio.play_tone.assert_not_called()
        assert not any(e.phase == 'baseline_audio_cue' for e in events)
        now[0] += 1
        press(); release()
        assert not window.isVisible()
    window.start_protocol('SSVEP', app.primaryScreen(), assessment_protocol=AssessmentProtocol.defaults('SSVEP'))
    window._on_frame_swapped()
    window.stop_protocol('escape')
    assert window.summary()['completed_formal_trials'] == 0 and events[-1].payload['stop_reason'] == 'escape'
window.close()
settings = Path(sys.argv[1]) / 'device-connections.json'
control = NeuroScopeWindow(settings_path=settings)
control.protocol_fields['total_trials'].setValue(12)
control.protocol_fields['task_sec'].setValue(6)
control.paradigm_select.setCurrentText('运动想象')
assert control.protocol_fields['total_trials'].value() == 90
control.protocol_fields['total_trials'].setValue(9)
control._save_protocol_settings()
control.close()
control = NeuroScopeWindow(settings_path=settings)
assert control.protocol_fields['total_trials'].value() == 12
assert control.protocol_fields['task_sec'].value() == 6
control.paradigm_select.setCurrentText('运动想象')
assert control.protocol_fields['total_trials'].value() == 9
assert not control._protocol_tabs.isTabVisible(3)
control._reset_protocol()
assert control.protocol_fields['total_trials'].value() == 90
control.paradigm_select.setCurrentText('SSVEP')
assert control.protocol_fields['total_trials'].value() == 12
assert control._protocol_tabs.isTabVisible(3)
control.navigation.setCurrentRow(1)
control.resize(1100, 700); control.show(); app.processEvents()
control.grab().save(str(Path(sys.argv[1]) / 'settings.png'))
control.close()
'''
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen", "PYTHONIOENCODING": "utf-8", "PYTHONFAULTHANDLER": "1"}
    env.pop("QT_PLUGIN_PATH", None)
    env.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path)], env=env,
                            capture_output=True, text=True, encoding="utf-8", timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
