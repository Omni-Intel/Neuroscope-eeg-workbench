import numpy as np

from neuroscope_eeg.desktop.audio import synthesize_tone
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
def test_oddball_sequence_is_repeatable_balanced_and_never_adjacent() -> None:
    first = generate_oddball_sequence(200, seed=17)
    second = generate_oddball_sequence(200, seed=17)

    assert first == second
    assert first.count("deviant") == 40
    assert all(left != "deviant" or right != "deviant" for left, right in zip(first, first[1:]))
