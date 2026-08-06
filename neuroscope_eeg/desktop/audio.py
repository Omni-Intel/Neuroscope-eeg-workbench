from __future__ import annotations

import numpy as np

try:
    import sounddevice as sd
except ImportError:  # The dependency is optional until an auditory protocol starts.
    sd = None


DEFAULT_AUDIO_RATE = 48_000


class AudioUnavailableError(RuntimeError):
    pass


def synthesize_tone(
    frequency_hz: float,
    duration_sec: float,
    *,
    sample_rate: int = DEFAULT_AUDIO_RATE,
    modulation_hz: float | None = None,
    amplitude: float = 0.2,
    fade_ms: float = 5.0,
) -> np.ndarray:
    if frequency_hz <= 0 or duration_sec <= 0 or sample_rate <= 0:
        raise ValueError("frequency, duration, and sample_rate must be positive")
    if modulation_hz is not None and modulation_hz <= 0:
        raise ValueError("modulation_hz must be positive")
    if not 0.0 < amplitude <= 1.0:
        raise ValueError("amplitude must be in (0, 1]")

    sample_count = max(1, int(round(duration_sec * sample_rate)))
    time = np.arange(sample_count, dtype=np.float64) / float(sample_rate)
    carrier = np.sin(2.0 * np.pi * frequency_hz * time)
    envelope = 1.0
    if modulation_hz is not None:
        envelope = 0.5 * (1.0 - np.cos(2.0 * np.pi * modulation_hz * time))
    samples = amplitude * carrier * envelope

    fade_samples = min(sample_count // 2, max(1, int(round(fade_ms * sample_rate / 1000.0))))
    ramp = np.linspace(0.0, 1.0, fade_samples, endpoint=False)
    samples[:fade_samples] *= ramp
    samples[-fade_samples:] *= ramp[::-1]
    return samples.astype(np.float32)


class AudioPlayer:
    def __init__(self, sample_rate: int = DEFAULT_AUDIO_RATE) -> None:
        if sd is None:
            raise AudioUnavailableError("听觉范式需要安装 sounddevice")
        try:
            sd.query_devices(kind="output")
        except Exception as exc:  # sounddevice exposes backend-specific PortAudio errors.
            raise AudioUnavailableError("没有检测到可用的音频输出设备") from exc
        self.sample_rate = sample_rate
        self._samples: np.ndarray | None = None

    def play_tone(
        self,
        frequency_hz: float,
        duration_sec: float,
        *,
        modulation_hz: float | None = None,
    ) -> None:
        samples = synthesize_tone(
            frequency_hz,
            duration_sec,
            sample_rate=self.sample_rate,
            modulation_hz=modulation_hz,
        )
        self.stop()
        self._samples = samples
        try:
            sd.play(self._samples, self.sample_rate, blocking=False)
        except Exception as exc:
            self._samples = None
            raise AudioUnavailableError(f"音频播放失败：{exc}") from exc

    def stop(self) -> None:
        if sd is not None:
            sd.stop()
        self._samples = None
