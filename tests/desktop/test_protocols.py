from neuroscope_eeg.desktop.protocols import StimulusEvent, frame_locked_frequencies


def test_160_hz_screen_uses_exact_frame_locked_frequencies() -> None:
    assert frame_locked_frequencies(160.0) == (8.0, 10.0, 16.0, 20.0)


def test_60_hz_screen_uses_representable_frequencies() -> None:
    assert frame_locked_frequencies(60.0) == (7.5, 10.0, 12.0, 15.0)


def test_stimulus_event_serializes_payload() -> None:
    event = StimulusEvent(1.0, 2.0, "SSVEP", "start", "SSVEP", {"frequency": 10.0})
    assert event.as_dict()["payload"] == {"frequency": 10.0}
