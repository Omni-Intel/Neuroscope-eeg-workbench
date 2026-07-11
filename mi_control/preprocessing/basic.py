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
