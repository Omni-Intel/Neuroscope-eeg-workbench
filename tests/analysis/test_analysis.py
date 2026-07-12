import numpy as np

from neuroscope_eeg.analysis.quality import signal_quality
from neuroscope_eeg.analysis.spectrum import power_spectrum, ssvep_snr


def test_ssvep_snr_finds_synthetic_target() -> None:
    sfreq = 250.0
    t = np.arange(int(sfreq * 4)) / sfreq
    data = np.sin(2.0 * np.pi * 12.0 * t)[None, :].astype(np.float32)
    freqs, psd = power_spectrum(data, sfreq)
    scores = ssvep_snr(freqs, psd, (8.0, 12.0, 15.0))
    assert max(scores, key=scores.get) == 12.0


def test_signal_quality_flags_flat_channel() -> None:
    data = np.vstack([np.zeros(1000), np.random.default_rng(1).normal(0, 4, 1000)]).astype(np.float32)
    report = signal_quality(data, ("C3", "C4"))
    assert report.overall == "check"
    assert report.flat_channels == ("C3",)
