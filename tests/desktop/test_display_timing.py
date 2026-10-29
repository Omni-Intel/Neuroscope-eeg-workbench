import pytest

from neuroscope_eeg.desktop.display_timing import DisplayTiming


def test_high_resolution_ticks_do_not_invent_120hz_gaps():
    monitor = DisplayTiming(120,8)
    for i in range(400):
        monitor.observe('timer',i*.008,('formal','flicker',1))
    row = next(r for r in monitor.snapshot()['rows'] if r['stream']=='timer' and r['scope']=='formal/flicker')
    assert row['mean_interval_ms'] == pytest.approx(8)
    assert row['long_intervals'] == row['estimated_skipped_slots'] == 0


def test_frame_evidence_is_separate_and_does_not_bridge_trials():
    monitor = DisplayTiming(120,8)
    for trial,start in ((1,0),(2,20)):
        for i in range(60):
            monitor.observe('timer', start+i/120,('formal','flicker',trial))
            monitor.observe('frame_swapped',start+i/60,('formal','flicker',trial))
    rows={r['stream']:r for r in monitor.snapshot()['rows'] if r['scope']=='formal/flicker'}
    assert rows['timer']['callback_rate_hz'] == pytest.approx(120)
    assert rows['frame_swapped']['callback_rate_hz'] == pytest.approx(60)
    assert rows['frame_swapped']['max_interval_ms'] == pytest.approx(1000/60)
    assert rows['frame_swapped']['long_intervals'] == 118
    assert monitor.snapshot()['physical_onset_verified'] is False
