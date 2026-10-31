import os
import subprocess
import sys

import numpy as np
import pytest

from neuroscope_eeg.desktop.ssvep_clock import SSVEPFrameClock
from neuroscope_eeg.desktop.ssvep_presentation import FREQUENCIES, target_levels


@pytest.mark.parametrize('refresh', [59.94, 60, 75, 119.88, 120, 144, 165])
def test_swap_monitor_counts_last_flicker_frame_without_false_gaps(refresh):
    clock = SSVEPFrameClock(refresh)
    count = round(refresh * 5)
    for i in range(count):
        clock.observe(100 + i / refresh, ('formal', 'flicker', 2), i)
    clock.observe(100 + count / refresh, ('formal', 'rest', 2), count)
    row, = clock.snapshot()['trials']
    assert row['frames'] == row['intervals'] == count
    assert row['observed_rate_hz'] == pytest.approx(refresh)
    assert row['abnormal_intervals'] == row['estimated_skipped_slots'] == 0
    assert row['complete']


def test_anomalies_do_not_latch_or_stop_monitoring_later_trials():
    clock = SSVEPFrameClock(75)
    clock.observe(0, ('formal', 'flicker', 1), 0)
    clock.observe(.1, ('formal', 'flicker', 1), 1)
    clock.observe(.1 + 1/75, ('formal', 'rest', 1), 2)
    clock.observe(20, ('formal', 'flicker', 2), 3)
    clock.observe(20 + 1/75, ('formal', 'rest', 2), 4)
    first, second = clock.snapshot()['trials']
    assert first['complete'] and first['abnormal_intervals'] == 1
    assert first['estimated_skipped_slots'] > 0
    assert second['complete'] and second['abnormal_intervals'] == 0
    assert clock.snapshot()['anomaly_action'] == 'record_only'
    assert not clock.snapshot()['physical_onset_verified']


def test_wrong_swap_cadence_is_visible_even_without_long_intervals():
    clock = SSVEPFrameClock(75)
    for i in range(121):
        clock.observe(i/60, ('formal', 'flicker', 1), i)
    row, = clock.snapshot()['trials']
    assert row['abnormal_intervals'] == 0
    assert row['rate_mismatch'] and row['observed_rate_hz'] == pytest.approx(60)


@pytest.mark.parametrize('actual,reported', [(59.94, 59.94), (75, 75), (120, 120), (144, 144), (60, 75)])
@pytest.mark.parametrize('sequential', [True, False])
def test_wall_time_waveform_preserves_frequencies_at_fractional_and_mismatched_rates(actual, reported, sequential):
    count = round(actual * 20)
    # Model one predicted presentation per completed swap, as in paintGL.
    seconds = np.maximum(0, np.arange(count) / actual - 1/actual + 1/reported)
    seconds[0] = 0
    for target, frequency in enumerate(FREQUENCIES):
        frames = np.array([target_levels('flicker', target, i, reported, sequential=sequential, elapsed_sec=t)
                           for i, t in enumerate(seconds)])
        if sequential:
            assert np.all(np.delete(frames, target, axis=1) == 30)
        signal = frames[:, target] - frames[:, target].mean()
        bins = np.fft.rfftfreq(count, 1/actual)
        assert abs(bins[np.argmax(abs(np.fft.rfft(signal)))] - frequency) <= actual/count


def test_window_scheduler_ignores_duplicate_swaps_recovers_and_never_aborts(tmp_path):
    script = r'''
from dataclasses import replace
from unittest.mock import patch
from PySide6.QtWidgets import QApplication
from neuroscope_eeg.desktop.stimulus import StimulusWindow
from neuroscope_eeg.protocol_config import AssessmentProtocol

app = QApplication([])
window = StimulusWindow()
events = []
window.event_emitted.connect(events.append)
now = [100.]
with patch('time.perf_counter', side_effect=lambda: now[0]):
    plan = replace(AssessmentProtocol.defaults('SSVEP'), task_sec=10)
    window.start_protocol('SSVEP', app.primaryScreen(), assessment_protocol=plan)
    window.refresh_hz = 75.
    from neuroscope_eeg.desktop.ssvep_clock import SSVEPFrameClock
    window._ssvep_clock = SSVEPFrameClock(75)
    assert window.format().swapInterval() == 1
    assert window.timer.interval() == 100
    flow = window._guided
    while flow.step.phase != 'flicker':
        flow.advance()
    window._pending_frame_events.clear()
    window._enter_guided_step()
    for frame in range(151):
        now[0] = 100 + max(0, frame-1)/75 + (.001 if frame else 0)
        window._prepare_painted_frame()
        assert window.frame_index == frame
        assert abs(window._ssvep_phase_sec - frame/75) < 1e-8
        now[0] = 100 + frame/75
        window._on_frame_swapped()
        assert window.frame_index == frame+1
        window._on_frame_swapped()  # Composition without a new paint.
        assert window.frame_index == frame+1
        window._tick()  # Watchdog never increments a stimulus frame.
        assert window.frame_index == frame+1
    now[0] += .4
    window._tick()
    assert window._ssvep_clock.recovery_requests == 1
    window._prepare_painted_frame()
    assert window._ssvep_phase_sec >= 2.399  # Catch up phase, not frame count.
    window._on_frame_swapped()
    assert window.timer.isActive() and not any(e.phase == 'stop' for e in events)
    assert window._ssvep_clock.snapshot()['trials'][0]['abnormal_intervals'] == 1
    # An event created after painting cannot be acknowledged by that old image.
    window._prepare_painted_frame()
    before = len(events)
    window._emit('cue', 'queued after paint', {'trial': 999})
    now[0] += 1/75
    window._on_frame_swapped()
    assert len(events) == before
    window._prepare_painted_frame()
    now[0] += 1/75
    window._on_frame_swapped()
    assert events[-1].label == 'queued after paint'
    assert events[-1].hook_type == 'frame_swapped'
    window.stop_protocol('manual_stop')
    assert events[-1].payload['stop_reason'] == 'manual_stop'
    assert events[-1].payload['display_timing']['ssvep_frame_clock']['anomaly_action'] == 'record_only'
window.close()
'''
    env = {**os.environ, 'QT_QPA_PLATFORM': 'offscreen'}
    env.pop('QT_PLUGIN_PATH', None)
    env.pop('QT_QPA_PLATFORM_PLUGIN_PATH', None)
    result = subprocess.run([sys.executable, '-c', script], env=env,
                            capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
