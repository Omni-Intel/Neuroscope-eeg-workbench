from __future__ import annotations

import numpy as np
from scipy import signal


def common_average_reference(data: np.ndarray) -> np.ndarray:
    values = np.asarray(data, dtype=np.float32)
    return values - np.mean(values, axis=0, keepdims=True)


def bandpass(data: np.ndarray, sfreq: float, low_hz: float, high_hz: float, order: int = 4) -> np.ndarray:
    if not 0 < low_hz < high_hz < sfreq / 2:
        raise ValueError("bandpass frequencies must be inside (0, Nyquist)")
    sos = signal.butter(order, (low_hz, high_hz), btype="bandpass", fs=sfreq, output="sos")
    return signal.sosfiltfilt(sos, np.asarray(data, dtype=np.float32), axis=1).astype(np.float32)


def notch(data: np.ndarray, sfreq: float, freq_hz: float = 50.0, q: float = 30.0) -> np.ndarray:
    if not 0 < freq_hz < sfreq / 2:
        return np.asarray(data, dtype=np.float32)
    b, a = signal.iirnotch(freq_hz, q, fs=sfreq)
    return signal.filtfilt(b, a, np.asarray(data, dtype=np.float32), axis=1).astype(np.float32)


def brainco_display_preprocess(data: np.ndarray, sfreq: float) -> np.ndarray:
    """Remove BrainCo dry-electrode drift before display and quick analysis."""
    values = np.nan_to_num(np.asarray(data, dtype=np.float32))
    if values.ndim != 2:
        raise ValueError("data must have shape (channels, samples)")
    if values.shape[1] < 32:
        return values - np.mean(values, axis=1, keepdims=True)
    detrended = signal.detrend(values, axis=1, type="linear").astype(np.float32)
    filtered = notch(detrended, sfreq, 50.0)
    high_hz = min(45.0, sfreq * 0.45)
    if high_hz <= 1.0:
        return filtered
    return bandpass(filtered, sfreq, 1.0, high_hz)


def robust_channel_scale(data: np.ndarray) -> np.ndarray:
    """Scale channels independently so one dry-electrode artifact cannot hide all others."""
    values = np.nan_to_num(np.asarray(data, dtype=np.float32))
    if values.ndim != 2:
        raise ValueError("data must have shape (channels, samples)")
    centered = values - np.median(values, axis=1, keepdims=True)
    scales = np.percentile(np.abs(centered), 95, axis=1, keepdims=True)
    scales = np.maximum(scales, 1e-6)
    return (centered / scales).astype(np.float32)
