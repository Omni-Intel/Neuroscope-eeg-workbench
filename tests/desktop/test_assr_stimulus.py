from neuroscope_eeg.desktop.protocols import PRESETS, generate_assr_sequence
from neuroscope_eeg.desktop.stimulus import StimulusWindow
from PySide6.QtWidgets import QApplication


class FakeAudioPlayer:
    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.stop_calls = 0

    def stop(self) -> None:
        self.stop_calls += 1

    def close(self) -> None:
        return None

    def play_tone(self, frequency_hz, duration_sec, **kwargs) -> None:
        self.calls.append({"frequency_hz": frequency_hz, "duration_sec": duration_sec, **kwargs})


def test_assr_stimulus_uses_planned_timing_routing_and_event_payload() -> None:
    app = QApplication.instance() or QApplication([])
    audio = FakeAudioPlayer()
    window = StimulusWindow(audio_player=audio)
    window.paradigm = "听觉 ASSR"
    window.preset = PRESETS["快速演示"]
    window.preset_label = "快速演示"
    window._assr_sequence = generate_assr_sequence(window.preset.assr_cycles)
    events = []
    window.event_emitted.connect(events.append)

    window._update_assr(0.0)
    assert events[-1].phase == "baseline"
    assert events[-1].payload["trial_index"] == 0
    assert events[-1].payload["condition"] == window._assr_sequence[0]
    assert events[-1].payload["ear"] in {"both", "right", "left"}

    window._update_assr(5.0)
    assert audio.calls[-1]["frequency_hz"] == 1000.0
    assert audio.calls[-1]["duration_sec"] == 20.0
    assert audio.calls[-1]["modulation_hz"] == 40.0
    assert audio.calls[-1]["output_condition"] == window._assr_sequence[0]
    onset_event = audio.calls[-1]["onset_callback"].__closure__[0].cell_contents
    offset_event = audio.calls[-1]["completion_callback"].__closure__[0].cell_contents
    for event in (onset_event, offset_event):
        assert event.payload["condition"] == window._assr_sequence[0]
        assert event.payload["ear"] in {"both", "right", "left"}
        assert event.payload["trial_index"] == 0

    window._update_assr(25.0)
    assert events[-1].phase == "baseline"
    assert events[-1].payload["trial_index"] == 1
    window.close()
    assert app is not None
