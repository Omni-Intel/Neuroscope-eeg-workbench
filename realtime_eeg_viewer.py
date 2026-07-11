#!/usr/bin/env python3
"""Realtime 64-channel Neuracle EEG visualization.

Panels:
- recent multi-channel time series
- mean power spectrum
- band-power summary
- scalp topomap
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np


DEFAULT_64_CH_NAMES = [
    "Fp1",
    "Fpz",
    "Fp2",
    "AF3",
    "AF4",
    "F7",
    "F5",
    "F3",
    "F1",
    "Fz",
    "F2",
    "F4",
    "F6",
    "F8",
    "FT7",
    "FC5",
    "FC3",
    "FC1",
    "FCz",
    "FC2",
    "FC4",
    "FC6",
    "FT8",
    "T7",
    "C5",
    "C3",
    "C1",
    "Cz",
    "C2",
    "C4",
    "C6",
    "T8",
    "TP7",
    "CP5",
    "CP3",
    "CP1",
    "CPz",
    "CP2",
    "CP4",
    "CP6",
    "TP8",
    "P7",
    "P5",
    "P3",
    "P1",
    "Pz",
    "P2",
    "P4",
    "P6",
    "P8",
    "PO7",
    "PO5",
    "PO3",
    "POz",
    "PO4",
    "PO6",
    "PO8",
    "O1",
    "Oz",
    "O2",
    "Iz",
    "AF7",
    "AF8",
    "PO10",
]

BANDS = [
    ("delta", 1.0, 4.0),
    ("theta", 4.0, 8.0),
    ("alpha", 8.0, 13.0),
    ("beta", 13.0, 30.0),
    ("gamma", 30.0, 45.0),
]

SSVEP_COLORS = ["#E11D48", "#2563EB", "#16A34A", "#F97316", "#7C3AED", "#0891B2", "#BE123C", "#4D7C0F"]


@dataclass
class SourceMetadata:
    name: str
    sfreq: float
    channel_names: list[str]


class RollingBuffer:
    def __init__(self, n_channels: int, max_samples: int) -> None:
        self.n_channels = n_channels
        self.max_samples = max_samples
        self._chunks: deque[np.ndarray] = deque()
        self._n_samples = 0
        self._lock = threading.Lock()

    def append(self, chunk: np.ndarray) -> None:
        if chunk.size == 0:
            return
        if chunk.ndim != 2:
            raise ValueError(f"expected 2D EEG chunk, got shape {chunk.shape}")
        data = np.asarray(chunk[: self.n_channels], dtype=np.float32)
        with self._lock:
            self._chunks.append(data)
            self._n_samples += data.shape[1]
            while self._n_samples > self.max_samples and self._chunks:
                extra = self._n_samples - self.max_samples
                head = self._chunks[0]
                if head.shape[1] <= extra:
                    self._chunks.popleft()
                    self._n_samples -= head.shape[1]
                else:
                    self._chunks[0] = head[:, extra:]
                    self._n_samples -= extra

    def latest(self, n_samples: int) -> np.ndarray | None:
        with self._lock:
            if self._n_samples < n_samples:
                return None
            data = np.concatenate(list(self._chunks), axis=1)
        return data[:, -n_samples:]

    def sample_count(self) -> int:
        with self._lock:
            return self._n_samples


class SimulatedSource:
    def __init__(self, sfreq: float, n_channels: int, stim_freqs: list[float], packet_sec: float = 0.05) -> None:
        self.metadata = SourceMetadata(
            name="simulated",
            sfreq=sfreq,
            channel_names=DEFAULT_64_CH_NAMES[:n_channels],
        )
        self.n_channels = n_channels
        self.stim_freqs = stim_freqs
        self.packet_samples = max(1, int(round(sfreq * packet_sec)))
        self._sample = 0

    def start(self) -> None:
        self._sample = 0

    def stop(self) -> None:
        pass

    def get_new_samples(self) -> np.ndarray:
        sfreq = self.metadata.sfreq
        idx = np.arange(self.packet_samples) + self._sample
        t = idx / sfreq
        self._sample += self.packet_samples

        data = 4.0 * np.random.randn(self.n_channels, self.packet_samples).astype(np.float32)
        alpha = np.sin(2.0 * np.pi * 10.0 * t).astype(np.float32)
        beta = np.sin(2.0 * np.pi * 20.0 * t).astype(np.float32)
        slow = np.sin(2.0 * np.pi * 0.35 * t).astype(np.float32)

        names = self.metadata.channel_names
        occipital = [i for i, name in enumerate(names) if name.startswith(("O", "PO"))]
        central_left = [i for i, name in enumerate(names) if name in {"C3", "C5", "CP3", "FC3"}]
        central_right = [i for i, name in enumerate(names) if name in {"C4", "C6", "CP4", "FC4"}]
        frontal = [i for i, name in enumerate(names) if name.startswith(("Fp", "AF", "F"))]

        if occipital:
            data[occipital] += 18.0 * alpha
        if central_left:
            data[central_left] += 9.0 * beta
        if central_right:
            data[central_right] += 7.0 * beta
        if frontal:
            data[frontal] += 25.0 * slow
        if occipital and self.stim_freqs:
            active_freq = self.stim_freqs[int(self._sample / max(1, int(sfreq * 5.0))) % len(self.stim_freqs)]
            ssvep = np.sin(2.0 * np.pi * active_freq * t).astype(np.float32)
            harmonic = np.sin(2.0 * np.pi * active_freq * 2.0 * t).astype(np.float32)
            data[occipital] += 14.0 * ssvep + 5.0 * harmonic

        time.sleep(self.packet_samples / sfreq)
        return data


class NeuracleSource:
    def __init__(
        self,
        oi_mi_path: Path,
        host: str,
        port: int,
        sfreq: float,
        n_channels: int,
        buffer_sec: float,
        ready_timeout_sec: float,
    ) -> None:
        sys.path.insert(0, str(oi_mi_path.expanduser()))
        from collect.neuracle_api import DataServerThread  # type: ignore

        self._DataServerThread = DataServerThread
        self.host = host
        self.port = port
        self.sfreq = sfreq
        self.requested_channels = n_channels
        self.buffer_sec = buffer_sec
        self.ready_timeout_sec = ready_timeout_sec
        self.server = None
        self.eeg_indices: list[int] = list(range(n_channels))
        self.metadata = SourceMetadata(
            name="neuracle",
            sfreq=sfreq,
            channel_names=DEFAULT_64_CH_NAMES[:n_channels],
        )

    def start(self) -> None:
        self.server = self._DataServerThread(sample_rate=int(self.sfreq), t_buffer=self.buffer_sec)
        failed = self.server.connect(hostname=self.host, port=self.port)
        if failed:
            self.server = None
            raise RuntimeError(f"could not connect JellyFish/Neuracle stream at {self.host}:{self.port}")

        started = time.monotonic()
        while not self.server.isReady():
            if time.monotonic() - started > self.ready_timeout_sec:
                self.stop()
                raise RuntimeError("timed out waiting for Neuracle metadata; check JellyFish forwarding")
            time.sleep(0.1)

        channel_names = list(getattr(self.server, "channelNames", []))
        channel_types = [str(x).upper() for x in getattr(self.server, "channelTypes", [])]
        eeg_indices = [i for i, kind in enumerate(channel_types) if kind == "EEG"]
        if not eeg_indices:
            eeg_indices = list(range(min(self.requested_channels, len(channel_names) or self.requested_channels)))
        self.eeg_indices = eeg_indices[: self.requested_channels]

        if channel_names:
            names = [normalize_channel_name(channel_names[i]) for i in self.eeg_indices]
        else:
            names = DEFAULT_64_CH_NAMES[: len(self.eeg_indices)]
        self.metadata = SourceMetadata(name="neuracle", sfreq=self.sfreq, channel_names=names)
        self.server.start()

    def stop(self) -> None:
        if self.server is not None:
            self.server.stop()
        self.server = None

    def get_new_samples(self) -> np.ndarray:
        if self.server is None:
            raise RuntimeError("Neuracle stream is not started")
        data = self.server.buffer.getUpdate()
        if data.size == 0:
            return np.empty((len(self.eeg_indices), 0), dtype=np.float32)
        if data.shape[0] <= max(self.eeg_indices):
            raise RuntimeError(f"stream has {data.shape[0]} channels, expected index {max(self.eeg_indices)}")
        return np.asarray(data[self.eeg_indices], dtype=np.float32)


class BrainCoSource:
    def __init__(
        self,
        oi_mi_path: Path,
        sfreq: float,
        n_channels: int,
        buffer_sec: float,
        brainco_addr: str,
        brainco_port: int,
        auto_discover: bool,
        scan_timeout_sec: float,
        ready_timeout_sec: float,
        start_retries: int,
        eeg_gain: int,
        signal_source: str,
        device_id: str,
    ) -> None:
        sys.path.insert(0, str(oi_mi_path.expanduser()))
        from acquisition.brainco_acquirer import BrainCoAcquirer  # type: ignore

        self.n_channels = min(max(int(n_channels), 1), 32)
        self.acquirer = BrainCoAcquirer(
            sfreq=sfreq,
            n_channels=self.n_channels,
            buffer_sec=buffer_sec,
            brainco_addr=brainco_addr,
            brainco_port=brainco_port,
            auto_discover=auto_discover,
            scan_timeout_sec=scan_timeout_sec,
            ready_timeout_sec=ready_timeout_sec,
            start_retries=start_retries,
            eeg_gain=eeg_gain,
            signal_source=signal_source,
            device_id=device_id,
        )
        self.metadata = SourceMetadata(
            name="brainco",
            sfreq=sfreq,
            channel_names=DEFAULT_64_CH_NAMES[: self.n_channels],
        )

    def start(self) -> None:
        self.acquirer.start_stream()

    def stop(self) -> None:
        self.acquirer.stop_stream()

    def get_new_samples(self) -> np.ndarray:
        data, _timestamps = self.acquirer.get_new_samples()
        return np.asarray(data, dtype=np.float32)


class StreamWorker(threading.Thread):
    def __init__(self, source, buffer: RollingBuffer) -> None:
        super().__init__(daemon=True)
        self.source = source
        self.buffer = buffer
        self.started_at: float | None = None
        self.error: str | None = None
        self.running = threading.Event()
        self.running.set()

    def run(self) -> None:
        try:
            self.source.start()
            self.started_at = time.monotonic()
            while self.running.is_set():
                self.buffer.append(self.source.get_new_samples())
                if self.source.metadata.name != "simulated":
                    time.sleep(0.01)
        except Exception as exc:  # noqa: BLE001
            self.error = str(exc)
        finally:
            try:
                self.source.stop()
            except Exception:
                pass

    def stop(self) -> None:
        self.running.clear()


def normalize_channel_name(name: str) -> str:
    raw = str(name).strip()
    if not raw:
        return raw
    known = {item.upper(): item for item in DEFAULT_64_CH_NAMES}
    return known.get(raw.upper(), raw)


def compute_spectrum(data: np.ndarray, sfreq: float, max_hz: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    centered = np.nan_to_num(data - np.mean(data, axis=1, keepdims=True))
    window = np.hanning(centered.shape[1]).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(centered * window[None, :], axis=1)) ** 2
    freqs = np.fft.rfftfreq(centered.shape[1], d=1.0 / sfreq)
    mask = freqs <= max_hz
    return freqs[mask], spectrum[:, mask], 10.0 * np.log10(np.mean(spectrum[:, mask], axis=0) + 1e-12)


def band_values(freqs: np.ndarray, spectrum: np.ndarray) -> dict[str, np.ndarray]:
    result: dict[str, np.ndarray] = {}
    for label, low, high in BANDS:
        mask = (freqs >= low) & (freqs < high)
        if np.any(mask):
            result[label] = 10.0 * np.log10(np.mean(spectrum[:, mask], axis=1) + 1e-12)
        else:
            result[label] = np.zeros((spectrum.shape[0],), dtype=np.float32)
    return result


def parse_frequency_list(raw: str) -> list[float]:
    if not raw.strip():
        return []
    values = []
    for item in raw.split(","):
        value = float(item.strip())
        if value <= 0:
            raise ValueError("stim frequencies must be positive")
        values.append(value)
    return values


def select_channels(channel_names: list[str], spec: str) -> list[int]:
    names_upper = [name.upper() for name in channel_names]
    selected: list[int] = []
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        if item.isdigit():
            idx = int(item) - 1
            if 0 <= idx < len(channel_names):
                selected.append(idx)
            continue
        upper = item.upper()
        if upper in names_upper:
            selected.append(names_upper.index(upper))
    return sorted(set(selected))


def compute_ssvep_snr(freqs: np.ndarray, spectrum: np.ndarray, stim_freqs: list[float]) -> dict[float, float]:
    mean_power = np.mean(spectrum, axis=0)
    result = {}
    for target_hz in stim_freqs:
        center = int(np.argmin(np.abs(freqs - target_hz)))
        target_lo = max(center - 1, 0)
        target_hi = min(center + 2, mean_power.shape[0])
        noise_left = mean_power[max(center - 8, 0) : max(center - 3, 0)]
        noise_right = mean_power[min(center + 4, mean_power.shape[0]) : min(center + 9, mean_power.shape[0])]
        noise = np.concatenate((noise_left, noise_right))
        target_power = float(np.mean(mean_power[target_lo:target_hi]))
        noise_power = float(np.mean(noise)) if noise.size else 1e-12
        result[target_hz] = target_power / max(noise_power, 1e-12)
    return result


def topomap_values(data: np.ndarray, sfreq: float, max_hz: float, metric: str) -> np.ndarray:
    if metric == "rms":
        centered = data - np.mean(data, axis=1, keepdims=True)
        return np.sqrt(np.mean(centered**2, axis=1))
    freqs, spectrum, _mean_db = compute_spectrum(data, sfreq, max_hz)
    values_by_band = band_values(freqs, spectrum)
    if metric not in values_by_band:
        raise ValueError(f"unknown topomap metric: {metric}")
    return values_by_band[metric]


class RealtimeViewer:
    def __init__(self, args: argparse.Namespace, source, buffer: RollingBuffer, worker: StreamWorker) -> None:
        import matplotlib.pyplot as plt

        self.args = args
        self.source = source
        self.buffer = buffer
        self.worker = worker
        self.plt = plt
        self.mne = None
        try:
            import mne

            mne.set_log_level("ERROR")
            self.mne = mne
        except Exception:
            self.mne = None

        self.fig = plt.figure(figsize=(14, 8))
        self.fig.patch.set_facecolor("white")
        self.ax_time = self.fig.add_axes([0.07, 0.57, 0.47, 0.33])
        self.ax_psd = self.fig.add_axes([0.62, 0.57, 0.33, 0.33])
        self.ax_topo = self.fig.add_axes([0.07, 0.10, 0.37, 0.33])
        self.ax_topo_cbar = self.fig.add_axes([0.46, 0.13, 0.015, 0.27])
        self.ax_band = self.fig.add_axes([0.62, 0.10, 0.33, 0.33])
        self.fig.canvas.mpl_connect("close_event", lambda _event: self.worker.stop())

    def draw_once(self) -> None:
        sfreq = self.source.metadata.sfreq
        analysis_samples = int(round(self.args.analysis_window_sec * sfreq))
        time_samples = int(round(self.args.time_window_sec * sfreq))
        data = self.buffer.latest(max(analysis_samples, time_samples))

        self.ax_time.clear()
        self.ax_psd.clear()
        self.ax_topo.clear()
        self.ax_topo_cbar.clear()
        self.ax_band.clear()

        if data is None:
            self._draw_waiting()
            return

        time_data = data[:, -time_samples:]
        analysis_data = data[:, -analysis_samples:]
        freqs, spectrum, mean_power_db = compute_spectrum(analysis_data, sfreq, self.args.max_hz)
        bands = band_values(freqs, spectrum)
        ssvep_freqs = parse_frequency_list(self.args.stim_freqs)
        ssvep_indices = select_channels(self.source.metadata.channel_names, self.args.ssvep_channels)
        ssvep_spectrum = spectrum[ssvep_indices] if ssvep_indices else spectrum

        self._draw_time_series(time_data, sfreq)
        self._draw_power_spectrum(freqs, mean_power_db, ssvep_freqs)
        if ssvep_freqs:
            self._draw_ssvep_summary(compute_ssvep_snr(freqs, ssvep_spectrum, ssvep_freqs), ssvep_indices)
        else:
            self._draw_band_summary(bands)
        self._draw_topomap(analysis_data)
        self._draw_title(data.shape[1])

    def _draw_waiting(self) -> None:
        status = self.worker.error or "waiting for enough realtime data..."
        for ax in [self.ax_time, self.ax_psd, self.ax_topo, self.ax_band]:
            ax.text(0.5, 0.5, status, ha="center", va="center", transform=ax.transAxes)
            ax.set_xticks([])
            ax.set_yticks([])
        self.ax_topo_cbar.set_axis_off()
        self.fig.suptitle("Realtime Neuracle 64ch EEG Viewer")

    def _draw_title(self, available_samples: int) -> None:
        elapsed = 0.0 if self.worker.started_at is None else time.monotonic() - self.worker.started_at
        meta = self.source.metadata
        status = "ERROR: " + self.worker.error if self.worker.error else "running"
        self.fig.suptitle(
            f"Realtime EEG | source={meta.name} | channels={len(meta.channel_names)} | "
            f"sfreq={meta.sfreq:g} Hz | buffered={available_samples} samples | t={elapsed:.1f}s | {status}",
            fontsize=12,
        )

    def _draw_time_series(self, data: np.ndarray, sfreq: float) -> None:
        n_show = min(self.args.show_channels, data.shape[0])
        shown = data[:n_show]
        centered = shown - np.mean(shown, axis=1, keepdims=True)
        scale = float(np.percentile(np.abs(centered), 95))
        scale = max(scale, 1.0)
        offsets = np.arange(n_show)[::-1] * 4.0
        t = np.arange(shown.shape[1]) / sfreq - shown.shape[1] / sfreq
        names = self.source.metadata.channel_names[:n_show]

        for idx in range(n_show):
            self.ax_time.plot(t, centered[idx] / scale + offsets[idx], lw=0.8)
        self.ax_time.set_title(f"Time series - last {self.args.time_window_sec:g}s")
        self.ax_time.set_xlabel("seconds from now")
        self.ax_time.set_yticks(offsets)
        self.ax_time.set_yticklabels(names, fontsize=8)
        self.ax_time.grid(True, alpha=0.25)
        self.ax_time.set_xlim(t[0], t[-1] if t.size else 0)

    def _draw_power_spectrum(self, freqs: np.ndarray, mean_power_db: np.ndarray, stim_freqs: list[float]) -> None:
        self.ax_psd.plot(freqs, mean_power_db, color="#2563EB", lw=1.6)
        for label, low, high in BANDS:
            self.ax_psd.axvspan(low, high, alpha=0.08)
            self.ax_psd.text((low + high) / 2, 0.97, label, ha="center", va="top", transform=self.ax_psd.get_xaxis_transform(), fontsize=8)
        y_min = float(np.nanmin(mean_power_db)) if mean_power_db.size else 0.0
        y_max = float(np.nanmax(mean_power_db)) if mean_power_db.size else 1.0
        for idx, target_hz in enumerate(stim_freqs):
            color = SSVEP_COLORS[idx % len(SSVEP_COLORS)]
            self.ax_psd.axvline(target_hz, color=color, lw=2.0)
            self.ax_psd.text(target_hz, y_max, f"{target_hz:g}Hz", color=color, ha="center", va="top", fontsize=9, fontweight="bold")
            harmonic = target_hz * 2.0
            if harmonic <= self.args.max_hz:
                self.ax_psd.axvline(harmonic, color=color, lw=1.0, ls="--", alpha=0.65)
                self.ax_psd.text(harmonic, y_min, "2x", color=color, ha="center", va="bottom", fontsize=8)
        self.ax_psd.set_title(f"Frequency distribution - last {self.args.analysis_window_sec:g}s")
        self.ax_psd.set_xlabel("Hz")
        self.ax_psd.set_ylabel("mean power (dB)")
        self.ax_psd.set_xlim(0.0, self.args.max_hz)
        self.ax_psd.grid(True, alpha=0.25)

    def _draw_band_summary(self, bands: dict[str, np.ndarray]) -> None:
        labels = [label for label, _low, _high in BANDS]
        values = [float(np.mean(bands[label])) for label in labels]
        colors = ["#64748B", "#0EA5E9", "#22C55E", "#F97316", "#A855F7"]
        self.ax_band.bar(labels, values, color=colors)
        self.ax_band.set_title("Band power summary")
        self.ax_band.set_ylabel("mean power (dB)")
        self.ax_band.grid(True, axis="y", alpha=0.25)

    def _draw_ssvep_summary(self, snr_scores: dict[float, float], channel_indices: list[int]) -> None:
        labels = [f"{freq:g}Hz" for freq in snr_scores]
        values = [snr_scores[freq] for freq in snr_scores]
        colors = [SSVEP_COLORS[idx % len(SSVEP_COLORS)] for idx in range(len(values))]
        self.ax_band.bar(labels, values, color=colors)
        best_idx = int(np.argmax(values)) if values else 0
        if values:
            self.ax_band.bar(labels[best_idx], values[best_idx], color=colors[best_idx], edgecolor="black", linewidth=2.0)
        channel_text = "all EEG" if not channel_indices else f"{len(channel_indices)} occipital/posterior ch"
        self.ax_band.set_title(f"SSVEP target SNR - {channel_text}")
        self.ax_band.set_ylabel("target / nearby noise")
        self.ax_band.grid(True, axis="y", alpha=0.25)

    def _draw_topomap(self, data: np.ndarray) -> None:
        values = topomap_values(data, self.source.metadata.sfreq, self.args.max_hz, self.args.topomap_metric)
        names = self.source.metadata.channel_names[: values.shape[0]]
        self.ax_topo.set_title(f"Scalp topomap - {self.args.topomap_metric}")
        if self.mne is None:
            self._draw_topomap_fallback(values, names)
            return

        montage = self.mne.channels.make_standard_montage("standard_1020")
        montage_names = set(montage.ch_names)
        valid = [idx for idx, name in enumerate(names) if name in montage_names]
        if len(valid) < 8:
            self._draw_topomap_fallback(values, names)
            return

        valid_names = [names[idx] for idx in valid]
        valid_values = values[valid]
        info = self.mne.create_info(valid_names, sfreq=self.source.metadata.sfreq, ch_types="eeg")
        info.set_montage(montage, on_missing="ignore")
        im, _contours = self.mne.viz.plot_topomap(
            valid_values,
            info,
            axes=self.ax_topo,
            show=False,
            contours=6,
            cmap="RdBu_r" if self.args.topomap_metric == "rms" else "viridis",
            sensors=True,
        )
        self.fig.colorbar(im, cax=self.ax_topo_cbar)

    def _draw_topomap_fallback(self, values: np.ndarray, names: list[str]) -> None:
        theta = np.linspace(0, 2.0 * np.pi, len(values), endpoint=False)
        radius = 0.15 + 0.8 * ((np.arange(len(values)) % 8) / 7.0)
        x = radius * np.cos(theta)
        y = radius * np.sin(theta)
        scatter = self.ax_topo.scatter(x, y, c=values, cmap="viridis", s=85, edgecolor="black", linewidth=0.4)
        for idx, name in enumerate(names[: len(values)]):
            if idx % max(1, len(values) // 16) == 0:
                self.ax_topo.text(x[idx], y[idx], name, fontsize=7, ha="center", va="center")
        head = self.plt.Circle((0, 0), 1.05, fill=False, color="black", lw=1.0)
        self.ax_topo.add_patch(head)
        self.ax_topo.set_aspect("equal")
        self.ax_topo.axis("off")
        self.fig.colorbar(scatter, cax=self.ax_topo_cbar)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Realtime EEG viewer for Neuracle and BrainCo.")
    parser.add_argument("--mode", choices=["simulated", "neuracle", "brainco"], default="simulated")
    parser.add_argument("--oi-mi-path", type=Path, default=Path("/Users/mac/Documents/GitHub/oi-mi"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8712)
    parser.add_argument("--sfreq", type=float, default=1000.0, help="Must match JellyFish forwarding sample rate.")
    parser.add_argument("--n-channels", type=int, default=64)
    parser.add_argument("--buffer-sec", type=float, default=30.0)
    parser.add_argument("--ready-timeout-sec", type=float, default=15.0)
    parser.add_argument("--time-window-sec", type=float, default=5.0)
    parser.add_argument("--analysis-window-sec", type=float, default=4.0)
    parser.add_argument("--update-ms", type=int, default=250)
    parser.add_argument("--max-hz", type=float, default=45.0)
    parser.add_argument("--show-channels", type=int, default=16)
    parser.add_argument("--topomap-metric", choices=["rms", "delta", "theta", "alpha", "beta", "gamma"], default="alpha")
    parser.add_argument("--stim-freqs", default="", help="Comma-separated SSVEP stimulus frequencies, e.g. 8,10,12,15.")
    parser.add_argument("--ssvep-channels", default="PO7,PO5,PO3,POz,PO4,PO6,PO8,O1,Oz,O2", help="Comma-separated channel names or 1-based indices used for SSVEP SNR.")
    parser.add_argument("--brainco-addr", default="", help="BrainCo device IP. Leave empty to auto-discover.")
    parser.add_argument("--brainco-port", type=int, default=0, help="BrainCo device port. Leave 0 to auto-discover.")
    parser.add_argument("--brainco-no-auto-discover", action="store_true", help="Disable BrainCo mDNS/SDK discovery and use addr/port only.")
    parser.add_argument("--brainco-scan-timeout-sec", type=float, default=6.0)
    parser.add_argument("--brainco-ready-timeout-sec", type=float, default=20.0)
    parser.add_argument("--brainco-start-retries", type=int, default=2)
    parser.add_argument("--brainco-gain", type=int, default=6)
    parser.add_argument("--brainco-signal-source", default="NORMAL")
    parser.add_argument("--brainco-device-id", default="eeg-cap")
    parser.add_argument("--save-frame", type=Path, default=None, help="Render one PNG frame and exit.")
    return parser.parse_args(argv)


def build_source(args: argparse.Namespace):
    if args.mode == "simulated":
        return SimulatedSource(sfreq=args.sfreq, n_channels=args.n_channels, stim_freqs=parse_frequency_list(args.stim_freqs))
    if args.mode == "brainco":
        return BrainCoSource(
            oi_mi_path=args.oi_mi_path,
            sfreq=args.sfreq,
            n_channels=args.n_channels,
            buffer_sec=args.buffer_sec,
            brainco_addr=args.brainco_addr,
            brainco_port=args.brainco_port,
            auto_discover=not args.brainco_no_auto_discover,
            scan_timeout_sec=args.brainco_scan_timeout_sec,
            ready_timeout_sec=args.brainco_ready_timeout_sec,
            start_retries=args.brainco_start_retries,
            eeg_gain=args.brainco_gain,
            signal_source=args.brainco_signal_source,
            device_id=args.brainco_device_id,
        )
    return NeuracleSource(
        oi_mi_path=args.oi_mi_path,
        host=args.host,
        port=args.port,
        sfreq=args.sfreq,
        n_channels=args.n_channels,
        buffer_sec=args.buffer_sec,
        ready_timeout_sec=args.ready_timeout_sec,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.save_frame is not None:
        import matplotlib

        matplotlib.use("Agg")

    source = build_source(args)
    buffer = RollingBuffer(args.n_channels, int(round(args.buffer_sec * args.sfreq)))
    worker = StreamWorker(source, buffer)
    worker.start()

    viewer = RealtimeViewer(args, source, buffer, worker)
    try:
        if args.save_frame is not None:
            min_samples = int(round(max(args.time_window_sec, args.analysis_window_sec) * args.sfreq))
            deadline = time.monotonic() + max(args.time_window_sec, args.analysis_window_sec) + 3.0
            while buffer.sample_count() < min_samples and worker.error is None and time.monotonic() < deadline:
                time.sleep(0.05)
            viewer.draw_once()
            args.save_frame.parent.mkdir(parents=True, exist_ok=True)
            viewer.fig.savefig(args.save_frame, dpi=150)
        else:
            import matplotlib.animation as animation

            viewer.animation = animation.FuncAnimation(
                viewer.fig,
                lambda _frame: viewer.draw_once(),
                interval=max(50, args.update_ms),
                cache_frame_data=False,
            )
            viewer.plt.show()
    finally:
        worker.stop()
        worker.join(timeout=2.0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
