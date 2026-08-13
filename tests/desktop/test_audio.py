import numpy as np

import neuroscope_eeg.desktop.audio as audio_module
from neuroscope_eeg.desktop.audio import AudioPlayer, synthesize_tone
from neuroscope_eeg.desktop.protocols import generate_oddball_sequence


def test_assr_tone_contains_carrier_and_40_hz_sidebands() -> None:
    sample_rate = 48_000
    samples = synthesize_tone(1000.0, 1.0, sample_rate=sample_rate, modulation_hz=40.0)
    spectrum = np.abs(np.fft.rfft(samples))
    frequencies = np.fft.rfftfreq(samples.size, 1.0 / sample_rate)

    for expected in (960.0, 1000.0, 1040.0):
        index = int(np.argmin(np.abs(frequencies - expected)))
        assert spectrum[index] > np.median(spectrum) * 1000.0
    assert abs(float(samples[0])) < 1e-6
    assert abs(float(samples[-1])) < 1e-3


def test_audio_player_reports_first_output_buffer_once_and_reports_offset(monkeypatch) -> None:
    class FakeStream:
        def __init__(self, **kwargs) -> None:
            self.callback = kwargs["callback"]
            self.started = False
            self.closed = False

        def start(self) -> None:
            self.started = True

        def stop(self) -> None:
            self.started = False

        def close(self) -> None:
            self.closed = True

    class FakeSoundDevice:
        stream: FakeStream | None = None

        @staticmethod
        def query_devices(kind: str):
            assert kind == "output"
            return {"name": "fake"}

        @classmethod
        def OutputStream(cls, **kwargs):  # noqa: N802 - sounddevice API name
            cls.stream = FakeStream(**kwargs)
            return cls.stream

    monkeypatch.setattr(audio_module, "sd", FakeSoundDevice)
    onsets = []
    offsets = []
    player = AudioPlayer(sample_rate=1000)
    player.play_tone(
        100.0,
        0.006,
        onset_callback=onsets.append,
        completion_callback=offsets.append,
    )
    stream = FakeSoundDevice.stream
    assert stream is not None and stream.started
    first = np.zeros((4, 2), dtype=np.float32)
    stream.callback(first, 4, {"outputBufferDacTime": 20.0}, None)
    second = np.zeros((4, 2), dtype=np.float32)
    stream.callback(second, 4, {"outputBufferDacTime": 20.004}, None)
    assert len(onsets) == 1
    assert onsets[0].stage == "onset"
    assert onsets[0].output_dac_time == 20.0
    assert len(offsets) == 1
    assert offsets[0].stage == "offset"
    assert offsets[0].output_dac_time == 20.006
    assert np.any(first != 0.0) or np.any(second != 0.0)
    player.close()
    assert stream.closed


def test_audio_player_routes_each_assr_condition_to_expected_channels(monkeypatch) -> None:
    class FakeStream:
        def __init__(self, **kwargs) -> None:
            assert kwargs["channels"] == 2
            self.callback = kwargs["callback"]

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeSoundDevice:
        stream: FakeStream | None = None

        @staticmethod
        def query_devices(kind: str):
            assert kind == "output"
            return {"name": "fake"}

        @classmethod
        def OutputStream(cls, **kwargs):  # noqa: N802
            cls.stream = FakeStream(**kwargs)
            return cls.stream

    monkeypatch.setattr(audio_module, "sd", FakeSoundDevice)
    player = AudioPlayer(sample_rate=1000)
    expected_channels = {
        "left": (True, False),
        "right": (False, True),
        "binaural": (True, True),
    }
    for condition, expected in expected_channels.items():
        player.play_tone(100.0, 0.006, output_condition=condition)
        output = np.zeros((6, 2), dtype=np.float32)
        assert FakeSoundDevice.stream is not None
        FakeSoundDevice.stream.callback(output, 6, {}, None)
        actual = tuple(bool(np.any(output[:, channel])) for channel in range(2))
        assert actual == expected


def test_audio_player_defaults_to_binaural_for_other_auditory_paradigms(monkeypatch) -> None:
    class FakeStream:
        def __init__(self, **kwargs) -> None:
            self.callback = kwargs["callback"]

        def start(self) -> None:
            return None

        def stop(self) -> None:
            return None

        def close(self) -> None:
            return None

    class FakeSoundDevice:
        @staticmethod
        def query_devices(kind: str):
            return {"name": "fake"}

        @staticmethod
        def OutputStream(**kwargs):  # noqa: N802
            FakeSoundDevice.stream = FakeStream(**kwargs)
            return FakeSoundDevice.stream

    monkeypatch.setattr(audio_module, "sd", FakeSoundDevice)
    player = AudioPlayer(sample_rate=1000)
    player.play_tone(100.0, 0.006)
    output = np.zeros((6, 2), dtype=np.float32)
    FakeSoundDevice.stream.callback(output, 6, {}, None)
    assert np.array_equal(output[:, 0], output[:, 1])


def test_oddball_sequence_is_repeatable_balanced_and_never_adjacent() -> None:
    first = generate_oddball_sequence(200, seed=17)
    second = generate_oddball_sequence(200, seed=17)

    assert first == second
    assert first.count("deviant") == 40
    assert all(left != "deviant" or right != "deviant" for left, right in zip(first, first[1:]))
