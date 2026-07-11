from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True, slots=True)
class QualityReport:
    overall: str
    rms_uv: np.ndarray
    flat_channels: tuple[str, ...]
    noisy_channels: tuple[str, ...]
    clipped_channels: tuple[str, ...]
    dropped_ratio: float


def signal_quality(data: np.ndarray, channel_names: tuple[str, ...], expected_samples: int | None = None) -> QualityReport:
    values = np.asarray(data, dtype=np.float32)
    if values.size == 0:
        return QualityReport("waiting", np.array([], dtype=np.float32), (), (), (), 1.0)
    centered = values - np.mean(values, axis=1, keepdims=True)
    rms = np.sqrt(np.mean(centered**2, axis=1))
    flat = tuple(channel_names[i] for i, value in enumerate(rms) if value < 0.2)
    noisy = tuple(channel_names[i] for i, value in enumerate(rms) if value > 120.0)
    clipped = tuple(channel_names[i] for i in range(values.shape[0]) if np.mean(np.abs(values[i]) > 500.0) > 0.05)
    dropped_ratio = 0.0
    if expected_samples:
        dropped_ratio = max(0.0, 1.0 - values.shape[1] / expected_samples)
    issue_count = len(flat) + len(noisy) + len(clipped)
    overall = "good" if issue_count == 0 and dropped_ratio < 0.05 else "check"
    return QualityReport(overall, rms, flat, noisy, clipped, dropped_ratio)
