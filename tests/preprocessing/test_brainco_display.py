import numpy as np
import pytest

from neuroscope_eeg.preprocessing.basic import brainco_display_preprocess, robust_channel_scale


def test_brainco_display_preprocess_removes_large_drift_without_changing_shape() -> None:
    sfreq = 250.0
    t = np.arange(int(sfreq * 4.0)) / sfreq
    data = np.vstack(
        (
            10_000.0 * t + 5.0 * np.sin(2 * np.pi * 10.0 * t),
            4.0 * np.sin(2 * np.pi * 12.0 * t),
        )
    ).astype(np.float32)

    filtered = brainco_display_preprocess(data, sfreq)

    assert filtered.shape == data.shape
    assert np.all(np.isfinite(filtered))
    assert np.std(filtered[0]) < np.std(data[0]) * 0.05


def test_robust_channel_scale_prevents_one_channel_from_flattening_the_other() -> None:
    data = np.vstack((np.linspace(0, 10_000, 1000), np.sin(np.linspace(0, 30, 1000)))).astype(np.float32)

    scaled = robust_channel_scale(data)

    assert scaled.shape == data.shape
    assert np.percentile(np.abs(scaled[0]), 95) == pytest.approx(1.0, rel=0.05)
    assert np.percentile(np.abs(scaled[1]), 95) == pytest.approx(1.0, rel=0.05)
