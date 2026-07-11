from __future__ import annotations

import numpy as np


BANDS = {
    "delta": (1.0, 4.0),
    "theta": (4.0, 8.0),
    "alpha": (8.0, 13.0),
    "beta": (13.0, 30.0),
    "gamma": (30.0, 45.0),
}


def power_spectrum(data: np.ndarray, sfreq: float, max_hz: float = 45.0) -> tuple[np.ndarray, np.ndarray]:
    values = np.nan_to_num(np.asarray(data, dtype=np.float32))
    if values.ndim != 2:
        raise ValueError("data must have shape (channels, samples)")
    centered = values - np.mean(values, axis=1, keepdims=True)
    window = np.hanning(centered.shape[1]).astype(np.float32)
    psd = np.abs(np.fft.rfft(centered * window[None, :], axis=1)) ** 2
    freqs = np.fft.rfftfreq(centered.shape[1], d=1.0 / sfreq)
    mask = freqs <= max_hz
    return freqs[mask], psd[:, mask]


def band_power(freqs: np.ndarray, psd: np.ndarray) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    for name, (low_hz, high_hz) in BANDS.items():
        mask = (freqs >= low_hz) & (freqs < high_hz)
        result[name] = 10.0 * np.log10(np.mean(psd[:, mask], axis=1) + 1e-12) if np.any(mask) else np.zeros(psd.shape[0])
    return result


def ssvep_snr(freqs: np.ndarray, psd: np.ndarray, targets: tuple[float, ...]) -> dict[float, float]:
    mean_power = np.mean(psd, axis=0)
    scores: dict[float, float] = {}
    for target in targets:
        center = int(np.argmin(np.abs(freqs - target)))
        target_power = float(np.mean(mean_power[max(center - 1, 0) : min(center + 2, len(mean_power))]))
        noise = np.concatenate(
            (
                mean_power[max(center - 8, 0) : max(center - 3, 0)],
                mean_power[min(center + 4, len(mean_power)) : min(center + 9, len(mean_power))],
            )
        )
        scores[target] = target_power / max(float(np.mean(noise)) if noise.size else 1e-12, 1e-12)
    return scores
