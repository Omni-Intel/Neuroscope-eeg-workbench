from __future__ import annotations

import time

import numpy as np

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata


DEFAULT_CHANNELS_32 = (
    "Fp1",
    "Fp2",
    "F7",
    "F3",
    "Fz",
    "F4",
    "F8",
    "FC5",
    "FC1",
    "FC2",
    "FC6",
    "T7",
    "C3",
    "Cz",
    "C4",
    "T8",
    "CP5",
    "CP1",
    "CP2",
    "CP6",
    "P7",
    "P3",
    "Pz",
    "P4",
    "P8",
    "PO7",
    "PO3",
    "POz",
    "PO4",
    "PO8",
    "O1",
    "O2",
)


class SimulatedSource:
    def __init__(
        self,
        sfreq: float = 250.0,
        channel_names: tuple[str, ...] = DEFAULT_CHANNELS_32,
        stim_freqs: tuple[float, ...] = (8.0, 10.0, 12.0, 15.0),
        packet_sec: float = 0.05,
        seed: int = 7,
        paced: bool = True,
    ) -> None:
        self.metadata = SourceMetadata.eeg("simulated", "simulated", sfreq, channel_names)
        self.stim_freqs = stim_freqs
        self.packet_samples = max(1, int(round(sfreq * packet_sec)))
        self.paced = paced
        self._rng = np.random.default_rng(seed)
        self._sample = 0
        self._started = False

    def start(self) -> None:
        self._sample = 0
        self._started = True

    def stop(self) -> None:
        self._started = False

    def read_chunk(self) -> EEGChunk:
        if not self._started:
            raise RuntimeError("source is not started")
        sfreq = self.metadata.sfreq
        sample_index = np.arange(self.packet_samples) + self._sample
        timestamps = sample_index / sfreq
        t = timestamps
        data = self._rng.normal(0.0, 3.0, (self.metadata.n_channels, self.packet_samples)).astype(np.float32)

        names = self.metadata.channel_names
        occipital = [i for i, name in enumerate(names) if name.startswith(("O", "PO"))]
        central_left = [i for i, name in enumerate(names) if name in {"C3", "CP5", "CP1", "FC5", "FC1"}]
        central_right = [i for i, name in enumerate(names) if name in {"C4", "CP6", "CP2", "FC6", "FC2"}]
        frontal = [i for i, name in enumerate(names) if name.startswith(("Fp", "F"))]

        alpha = np.sin(2.0 * np.pi * 10.0 * t).astype(np.float32)
        beta = np.sin(2.0 * np.pi * 20.0 * t).astype(np.float32)
        slow = np.sin(2.0 * np.pi * 0.35 * t).astype(np.float32)
        if occipital:
            data[occipital] += 14.0 * alpha
        if central_left:
            data[central_left] += 7.0 * beta
        if central_right:
            data[central_right] -= 6.0 * beta
        if frontal:
            data[frontal] += 18.0 * slow
        if occipital and self.stim_freqs:
            active = self.stim_freqs[int(self._sample / max(1, int(sfreq * 5.0))) % len(self.stim_freqs)]
            data[occipital] += 12.0 * np.sin(2.0 * np.pi * active * t).astype(np.float32)
            data[occipital] += 4.0 * np.sin(2.0 * np.pi * active * 2.0 * t).astype(np.float32)

        sequence = self._sample
        self._sample += self.packet_samples
        if self.paced:
            time.sleep(self.packet_samples / sfreq)
        return EEGChunk(metadata=self.metadata, data=data, timestamps=timestamps, sequence=sequence)
