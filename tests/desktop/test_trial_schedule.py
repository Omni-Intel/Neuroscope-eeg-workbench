from collections import Counter

import pytest

from neuroscope_eeg.desktop.trial_schedule import TrialSchedule


@pytest.mark.parametrize("conditions,per_condition,practice", [(4, 1, False), (4, 11, True), (3, 30, False), (3, 21, True)])
def test_balanced_finite_schedule_including_partial_block(conditions, per_condition, practice):
    schedule = TrialSchedule(conditions, per_condition, practice)
    unique = {}
    for t in range(int(schedule.duration)):
        position = schedule.position(t)
        if position["stage"] == "trial":
            unique[position["trial"]] = position
    formal = [p for p in unique.values() if not p["is_practice"]]
    assert Counter(p["condition_index"] for p in formal) == {i: per_condition for i in range(conditions)}
    assert len(unique)-len(formal) == conditions*practice
    assert schedule.position(schedule.duration)["stage"] == "complete"
    assert schedule.position(schedule.duration-.001)["stage"] == "trial"


def test_original_stage_timing_and_automatic_stop():
    from PySide6.QtWidgets import QApplication
    from neuroscope_eeg.desktop.stimulus import StimulusWindow
    app = QApplication.instance() or QApplication([])
    window = StimulusWindow()
    window.paradigm = "运动想象"
    window._schedule = TrialSchedule(3, 1, True)
    window.timer.start(100000)
    events = []
    window.event_emitted.connect(events.append)
    for trial in range(6):
        for offset, phase in [(0, "fixation"), (2, "cue"), (3, "imagery"), (7, "rest")]:
            window._update_motor_imagery(trial*9+offset)
            window._on_frame_swapped()
            assert events[-1].phase == phase
            assert events[-1].payload["is_practice"] == (trial < 3)
    window._update_motor_imagery(54)
    assert not window.timer.isActive()
    assert events[-1].phase == "stop"
    assert events[-1].payload["completed_formal_trials"] == 3
    assert window.stop_reason == "completed"
    window.close()
    assert app is not None
