import time

from neuroscope_eeg.desktop.performance import FpsTracker, fps_level, timer_interval_ms


def test_timer_intervals_for_supported_refresh_rates() -> None:
    assert timer_interval_ms(20) == 50
    assert timer_interval_ms(30) == 33
    assert timer_interval_ms(60) == 17


def test_fps_level_uses_target_ratios() -> None:
    assert fps_level(30.0, 30) == "good"
    assert fps_level(20.0, 30) == "warning"
    assert fps_level(10.0, 30) == "critical"


def test_fps_tracker_reports_recent_frame_rate() -> None:
    tracker = FpsTracker(window_sec=0.2)
    now = time.monotonic()
    for index in range(6):
        tracker.tick(now + index * 0.02)
    assert 45.0 <= tracker.fps <= 55.0
