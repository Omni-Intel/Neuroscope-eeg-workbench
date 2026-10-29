"""Local engineering indicators, deliberately separate from EEGQC scores."""
from pathlib import Path

import numpy as np
from scipy.signal import welch

from neuroscope_eeg.io.native_recording import read_native, utc_now, write_json


def write_local_report(run_dir):
    run, device, data = read_native(run_dir)
    fs = device["sfreq"]
    window = min(data.shape[0], int(fs*60))
    values = np.asarray(data[-window:], dtype=np.float64)
    channels = []
    for c, (name, kind, unit) in enumerate(zip(device["channel_names"], device["channel_types"], device["channel_units"])):
        channel = values[:, c]
        finite = np.isfinite(channel)
        item = {"name": name, "type": kind, "units": unit, "finite_ratio": float(finite.mean()),
                "rms_ac": None, "peak_to_peak": None, "line_noise_power_fraction": None}
        if finite.all() and len(channel) >= 4:
            centered = channel - channel.mean()
            item["rms_ac"] = float(np.sqrt(np.mean(centered**2)))
            item["peak_to_peak"] = float(np.ptp(channel))
            line = device.get("extra", {}).get("power_line_frequency")
            if kind == "eeg" and isinstance(line, (int, float)) and 0 < line < fs/2:
                freq, power = welch(centered, fs=fs, nperseg=min(len(channel), int(fs*4)))
                band = (freq >= 1) & (freq <= min(fs/2, 100))
                around_line = abs(freq-line) <= 1
                total = float(np.sum(power[band]))
                item["line_noise_power_fraction"] = float(np.sum(power[around_line])/total) if total else None
        channels.append(item)
    report = {"source_session_id": run["session_id"], "algorithm": "neuroscope-engineering-indicators",
              "algorithm_version": "1", "generated_at": utc_now(), "is_eegqc_score": False,
              "recording_status": run["recording_status"], "samples": run["samples"],
              "invalid_samples": run["invalid_samples"], "continuity_errors": run["continuity_errors"],
              "amplitude_window": {"start_sample": data.shape[0]-window, "samples": window, "seconds": window/fs},
              "channels": channels, "limitations": ["Amplitude and spectrum describe at most the last 60 seconds.",
              "No cross-device total score; electrode placement, reference and filters must be matched.",
              "Packet-loss detection depends on device capabilities; absence of a reported gap is not proof of zero loss."]}
    path = Path(run_dir) / "analysis/local_quality.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, report)
    return path
