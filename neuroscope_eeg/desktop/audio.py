from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Callable

import numpy as np

try:
    import sounddevice as sd
except ImportError:  # The dependency is optional until an auditory protocol starts.
    sd = None


DEFAULT_AUDIO_RATE = 48_000


class AudioUnavailableError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AudioTimingEvent:
    stage: str
    monotonic_time: float
    output_dac_time: float | None


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
        self._position = 0
        self._onset_callback: Callable[[AudioTimingEvent], None] | None = None
        self._completion_callback: Callable[[AudioTimingEvent], None] | None = None
        self._channels = "binaural"
        self._onset_sent = False
        self._lock = threading.Lock()
        try:
            self._stream = sd.OutputStream(
                samplerate=self.sample_rate,
                channels=2,
                dtype="float32",
                callback=self._audio_callback,
            )
            self._stream.start()
        except Exception as exc:
            raise AudioUnavailableError(f"无法打开持续音频输出流：{exc}") from exc

    def play_tone(
        self,
        frequency_hz: float,
        duration_sec: float,
        *,
        modulation_hz: float | None = None,
        channels: str = "binaural",
        onset_callback: Callable[[AudioTimingEvent], None] | None = None,
        completion_callback: Callable[[AudioTimingEvent], None] | None = None,
    ) -> None:
        if channels not in {"binaural", "right", "left"}:
            raise ValueError("channels must be binaural, right, or left")
        samples = synthesize_tone(
            frequency_hz,
            duration_sec,
            sample_rate=self.sample_rate,
            modulation_hz=modulation_hz,
        )
        with self._lock:
            self._samples = samples
            self._position = 0
            self._onset_callback = onset_callback
            self._completion_callback = completion_callback
            self._channels = channels
            self._onset_sent = False

    @staticmethod
    def _dac_time(time_info) -> float | None:
        value = (
            time_info.get("outputBufferDacTime")
            if isinstance(time_info, dict)
            else getattr(time_info, "outputBufferDacTime", None)
        )
        return None if value is None else float(value)

    def _audio_callback(self, outdata, frames: int, time_info, _status) -> None:
        outdata.fill(0.0)
        onset_callback = None
        completion_callback = None
        onset_event = None
        completion_event = None
        with self._lock:
            if self._samples is None:
                return
            start = self._position
            stop = min(len(self._samples), start + int(frames))
            copied = max(0, stop - start)
            if copied:
                if self._channels in {"binaural", "left"}:
                    outdata[:copied, 0] = self._samples[start:stop]
                if self._channels in {"binaural", "right"}:
                    outdata[:copied, 1] = self._samples[start:stop]
            dac_time = self._dac_time(time_info)
            now = time.monotonic()
            if copied and not self._onset_sent:
                self._onset_sent = True
                onset_callback = self._onset_callback
                onset_event = AudioTimingEvent("onset", now, dac_time)
            self._position = stop
            if stop >= len(self._samples):
                completion_callback = self._completion_callback
                completion_dac_time = (
                    None if dac_time is None else dac_time + copied / float(self.sample_rate)
                )
                completion_event = AudioTimingEvent("offset", now, completion_dac_time)
                self._samples = None
                self._position = 0
                self._onset_callback = None
                self._completion_callback = None
        if onset_callback is not None and onset_event is not None:
            onset_callback(onset_event)
        if completion_callback is not None and completion_event is not None:
            completion_callback(completion_event)

    def stop(self) -> None:
        with self._lock:
            self._samples = None
            self._position = 0
            self._onset_callback = None
            self._completion_callback = None
            self._onset_sent = False

    def close(self) -> None:
        self.stop()
        try:
            self._stream.stop()
            self._stream.close()
        except Exception:
            return
