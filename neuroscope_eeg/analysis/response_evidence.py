"""Descriptive response evidence; never fits a subject model or changes trial eligibility."""
from collections import Counter, defaultdict

import numpy as np
from scipy.signal import spectrogram, welch

from neuroscope_eeg.analysis.task_assessment import band_power, local_snr, mean_ci, spectral_guard

METHODS = {
    "spectral": "Hann Welch, constant detrend, density uV^2/Hz; SSVEP full analysis window; MI 1 s segments, 50% overlap",
    "bandpower": "sum(PSD bins)*df; half-open bands; relative denominator [1,40) Hz",
    "bands_hz": {"delta": [1, 4], "theta": [4, 8], "alpha": [8, 13], "beta": [13, 30], "low_gamma": [30, 40]},
    "aggregation": "arithmetic mean of per-trial values; ROI PSD averages channels before trials; SNR dB averages per-trial dB",
    "ssvep_noise": "median PSD within +/-2 Hz, excluding +/-0.5 Hz around center; targets/harmonics +/-0.5 Hz for 4 classes, +/-max(0.25 Hz,df) for 8 classes; known mains +/-1 Hz; >=3 bins",
    "baseline": "completed eyes-open interval, trim 0.5 s each end, nonoverlapping windows equal to SSVEP analysis window; matched channels and PSD; no gaze/luminance verification",
    "mi_baseline": "each trial fixation window from saved protocol, independent resting baseline does not replace it",
    "tfr": "Hann spectrogram, 1 s window, 0.25 s step, 4-40 Hz; per-trial 10log10(task PSD / fixation Welch PSD), then mean trials; centers only, no padding",
    "beta_recovery": "rest onset +0.5 to +1.5 s, only if rest >=1.5 s; relative to same trial fixation; descriptive recovery response",
    "ci": "trial bootstrap mean, 2000 repeats, seed 20261028, n>=3; descriptive within-record intervals, not population or block-independent inference",
    "scope": "fixed algorithms; no training, no ITR, no device total score; no pooled cross-session inference",
}


def harmonic_overlaps(frequencies):
    rows = []
    for target in frequencies:
        for h in (1, 2, 3):
            shared = [{"target_hz": f, "harmonic": k} for f in frequencies for k in (1, 2, 3)
                      if f != target and abs(f*k-target*h) <= .01]
            if shared:
                rows.append({"target_hz": target, "harmonic": h, "frequency_hz": target*h, "shared_with": shared})
    return rows


def snr_spectrum(f, p, targets, line):
    values = []
    excluded = np.zeros(len(f), dtype=bool)
    guard = spectral_guard(targets, float(f[1]-f[0]))
    for target in targets:
        for harmonic in (1, 2, 3):
            excluded |= abs(f-target*harmonic) <= guard
    if isinstance(line, (int, float)):
        for h in (1, 2):
            excluded |= abs(f-line*h) <= 1
    for center, power in zip(f, p):
        neighbors = (abs(f-center) <= 2) & (abs(f-center) >= .5) & ~excluded
        noise = float(np.median(p[neighbors])) if neighbors.sum() >= 3 else 0
        values.append(float(10*np.log10(power/noise)) if power > 0 and noise > 0 else None)
    return values


def retention(rows, labels, planned):
    out = []
    for label in [None, *labels]:
        selected = rows if label is None else [r for r in rows if r["condition"] == label]
        count = planned if label is None else (planned//len(labels) if isinstance(planned, int) and planned % len(labels) == 0 else None)
        completed = sum(r["completed"] for r in selected)
        analyzable = sum(r["analyzable"] for r in selected)
        clean = sum(r["clean"] for r in selected)
        out.append({"condition": "全部" if label is None else label, "planned": count,
                    "observed": len(selected), "completed": completed, "analyzable": analyzable, "clean": clean,
                    "completion_fraction": completed/count if count else None,
                    "analyzable_fraction_observed": analyzable/len(selected) if selected else None,
                    "clean_fraction_analyzable": clean/analyzable if analyzable else None,
                    "unavailable_reasons": dict(Counter(r["exclusion_reason"] for r in selected if not r["analyzable"])),
                    "screening_reasons": dict(Counter(reason for r in selected if r["analyzable"] and not r["clean"]
                                                      for reason in r["exclusion_reason"].split("；")))})
    return out


def summarize_metrics(rows, *, by_block=False):
    groups = defaultdict(list)
    for row in rows:
        for subset in (["analyzable", "screened"] if row["clean"] else ["analyzable"]):
            key = (subset, str(row["condition"]), row["channel"], row["metric"], row.get("harmonic"),
                   row.get("frequency_hz"), row["block"] if by_block else None)
            groups[key].append(row["value"])
    out = []
    for (subset, condition, channel, metric, harmonic, frequency, block), values in groups.items():
        finite = [v for v in values if v is not None and np.isfinite(v)]
        summary = mean_ci(finite)
        out.append({"subset": subset, "condition": condition, "channel": channel, "metric": metric,
                    "harmonic": harmonic, "frequency_hz": frequency, "block": block, "eligible_n": len(values),
                    **summary, "sd": float(np.std(finite, ddof=1)) if len(finite) > 1 else None})
    return out


class ResponseEvidence:
    def __init__(self, paradigm, fs, channels, frequencies, line):
        self.paradigm, self.fs = paradigm, fs
        # Selection is case-insensitive upstream; mi_metrics uses canonical names.
        self.channels = ["C3", "C4"] if paradigm == "运动想象" else channels
        self.frequencies, self.line = frequencies, line
        self.metrics, self.spectra, self.tfr, self.baseline_windows = [], [], [], []
        self.resting = {"status": "unavailable", "reason": "缺少可对齐的完整独立睁眼基线"}
        self.errors = []

    def metric(self, row, channel, metric, value, **extra):
        self.metrics.append({k: row[k] for k in ("trial", "block", "condition", "clean")} |
                            {"channel": channel, "metric": metric, "value": value, **extra})

    def psd(self, x, nperseg):
        return welch(x, fs=self.fs, nperseg=nperseg, noverlap=nperseg//2, axis=0,
                     window="hann", detrend="constant", scaling="density")

    def spectrum(self, row, x, phase, nperseg):
        f, p = self.psd(x, nperseg)
        channels = list(self.channels)
        if self.paradigm == "SSVEP":
            p = np.column_stack([p, p.mean(axis=1)])
            channels.append("ROI")
        for j, channel in enumerate(channels):
            mask = (f >= 1) & (f < 40)
            total = float(p[mask, j].sum()*(f[1]-f[0]))
            for band, (lo, hi) in METHODS["bands_hz"].items():
                power = float(p[(f >= lo) & (f < hi), j].sum()*(f[1]-f[0]))
                self.metric(row, channel, f"{phase}_{band}_power_uv2", power)
                self.metric(row, channel, f"{phase}_{band}_relative", power/total if total > 1e-12 else None)
            upper = max(80, 3*max(self.frequencies)+2) if self.frequencies else 80
            keep = (f >= .5) & (f <= upper)
            self.spectra.append({k: row[k] for k in ("trial", "condition", "clean")} |
                                {"phase": phase, "channel": channel, "frequency_hz": f[keep], "psd": p[keep, j]})

    def prepare_resting(self, intervals, data, valid, indices, timestamps, chosen, samples, rails):
        """Only use completed recorded intervals, with the same gate as task samples."""
        accepted = []
        for interval in intervals:
            if interval["phase"] != "baseline_eyes_open" or not interval["completed"]:
                continue
            start = interval["start_sample"] + round(.5*self.fs)
            end = interval["end_sample"] - round(.5*self.fs)
            for a in range(start, end-samples+1, samples):
                b = a+samples
                x = np.asarray(data[a:b, chosen], dtype=float)
                reason = ""
                if not valid[a:b].all() or not np.isfinite(x).all():
                    reason = "无效样本"
                elif (np.any(np.diff(indices[a:b]) != 1) or not np.isfinite(timestamps[a:b]).all()
                      or np.any(np.diff(timestamps[a:b]) <= 0) or np.any(np.diff(timestamps[a:b]) > 2.5/self.fs)):
                    reason = "样本或时间戳不连续"
                ptp = np.ptp(x, axis=0)
                screened = bool(not reason and np.all((ptp >= .1) & (ptp <= 300)))
                for j, channel in enumerate(self.channels):
                    if channel in rails:
                        lo, hi = rails[channel]
                        screened &= bool(not np.any((x[:, j] <= lo) | (x[:, j] >= hi)))
                entry = {"start_sample": a, "end_sample": b, "analyzable": not reason, "clean": screened,
                         "reason": reason or ("" if screened else "幅值或已确认量程筛查标记")}
                self.baseline_windows.append(entry)
                if not reason:
                    accepted.append((self.psd(x, samples), screened))
        if not accepted:
            self.resting["reason"] = "独立睁眼基线缺失、不完整或没有足长且连续有效的匹配窗口"
            return
        f = accepted[0][0][0]
        self.resting = {"status": "available", "window_sec": samples/self.fs, "subsets": {}}
        for subset in ("analyzable", "screened"):
            psds = [p for (_, p), clean in accepted if subset == "analyzable" or clean]
            self.resting["subsets"][subset] = {"n_windows": len(psds), "frequency_hz": f.tolist(),
                                               "psd": np.mean(psds, axis=0).tolist() if psds else None}

    def add_ssvep(self, row, task):
        self.spectrum(row, task, "task", len(task))
        for channel, x in [("ROI", task), *[(c, task[:, j:j+1]) for j, c in enumerate(self.channels)]]:
            snrs, powers = local_snr(x, self.fs, row["condition"], self.frequencies, self.line, details=True)
            for h, (snr, power) in enumerate(zip(snrs, powers), 1):
                extra = {"harmonic": h, "frequency_hz": power["frequency_hz"], "noise_bins": power["noise_bins"],
                         "target_exclusion_halfwidth_hz": power['target_exclusion_halfwidth_hz']}
                self.metric(row, channel, "snr_db", snr, **extra)
                self.metric(row, channel, "target_power_uv2", power["target_band_power_uv2"], **extra)
        # Independent rest comparison is calculated separately for both sample sets at finalization.

    def add_mi(self, row, baseline, task, imagery, rest):
        for phase, x in (("fixation", baseline), ("task", task)):
            self.spectrum(row, x, phase, round(self.fs))
        for band in ("mu", "beta"):
            for channel in self.channels:
                for suffix in ("baseline_power_uv2", "task_power_uv2", "erd_pct", "change_db"):
                    self.metric(row, channel, f"{band}_{suffix}", row[f"{band}_{channel}_{suffix}"])
            self.metric(row, "C3-C4", f"{band}_lateral_db", row[f"{band}_lateral_db"])
            if row["condition"] in {"左手", "右手"}:
                contra, ipsi = ("C4", "C3") if row["condition"] == "左手" else ("C3", "C4")
                self.metric(row, "contra", f"{band}_erd_pct", row[f"{band}_{contra}_erd_pct"])
                self.metric(row, "ipsi", f"{band}_erd_pct", row[f"{band}_{ipsi}_erd_pct"])
                self.metric(row, "contra-ipsi", f"{band}_change_db", row[f"{band}_{contra}_change_db"]-row[f"{band}_{ipsi}_change_db"])
        # Time-frequency values retain both channels and all three conditions.
        size = round(self.fs)
        f, base = self.psd(baseline, size)
        sf, t, power = spectrogram(imagery, fs=self.fs, window="hann", nperseg=size,
                                  noverlap=size-round(self.fs*.25), axis=0, detrend="constant", scaling="density")
        mask = (sf >= 4) & (sf <= 40)
        for j, channel in enumerate(self.channels):
            denominator = base[mask, j]
            values = np.full((mask.sum(), len(t)), np.nan)
            good = denominator > 1e-12
            values[good] = 10*np.log10(np.maximum(power[mask, j, :][good], 1e-12)/denominator[good, None])
            self.tfr.append({k: row[k] for k in ("trial", "condition", "clean")} |
                            {"channel": channel, "frequency_hz": f[mask], "time_sec": t, "change_db": values})
        if len(rest) >= round(1.5*self.fs):
            active = band_power(rest[round(.5*self.fs):round(1.5*self.fs)], self.fs, (13, 30))
            for j, channel in enumerate(self.channels):
                base_power = row[f"beta_{channel}_baseline_power_uv2"]
                self.metric(row, channel, "beta_recovery_erd_pct", float(100*(active[j]-base_power)/base_power))

    def finish(self, rows, labels, planned):
        result = {"methods": METHODS, "retention": retention(rows, labels, planned), "trial_metrics": self.metrics,
                  "resting_baseline": self.resting, "baseline_windows": self.baseline_windows,
                  "harmonic_overlaps": harmonic_overlaps(self.frequencies), "errors": self.errors,
                  "spectra": [], "time_frequency": [], "baseline_comparison": []}
        result["summary"] = summarize_metrics(self.metrics)
        main = [r for r in self.metrics if (r["metric"] == "snr_db" and r.get("harmonic") == 1 and r["channel"] == "ROI")
                or (r["metric"] in {"mu_erd_pct", "beta_erd_pct"} and r["channel"] in {"C3", "C4"})]
        result["block_summary"] = summarize_metrics(main, by_block=True)
        for source, destination, keys, value in ((self.spectra, result["spectra"], ("condition", "phase", "channel"), "psd"),
                                                 (self.tfr, result["time_frequency"], ("condition", "channel"), "change_db")):
            groups = defaultdict(list)
            for item in source:
                for subset in (["analyzable", "screened"] if item["clean"] else ["analyzable"]):
                    groups[(subset, *(str(item[k]) for k in keys))].append(item)
            for (subset, *key), items in groups.items():
                grid = items[0]["frequency_hz"]
                times = None
                if value == "psd":
                    # Display aggregation only: integration and trial SNR keep native bins.
                    grid = grid[(grid >= max(i["frequency_hz"][0] for i in items)) &
                                (grid <= min(i["frequency_hz"][-1] for i in items))]
                    stack = np.stack([np.interp(grid, item["frequency_hz"], item[value]) for item in items])
                else:
                    common = min(len(item["time_sec"]) for item in items)
                    times = items[0]["time_sec"][:common]
                    stack = np.stack([item[value][:, :common] for item in items])
                count = np.isfinite(stack).sum(axis=0)
                avg = np.divide(np.nansum(stack, axis=0), count, out=np.full_like(stack[0], np.nan), where=count > 0)
                output = {"subset": subset, **dict(zip(keys, key)), "n": len(items),
                          "frequency_hz": grid.tolist(), value: avg.tolist()}
                if value == "change_db":
                    output.update(time_sec=times.tolist(), n_per_cell=count.tolist())
                elif self.paradigm == "SSVEP":
                    output["snr_db"] = snr_spectrum(grid, avg, self.frequencies, self.line)
                destination.append(output)
        if self.resting["status"] == "available":
            for summary in result["summary"]:
                if summary["metric"] != "target_power_uv2" or summary["harmonic"] != 1:
                    continue
                baseline = self.resting["subsets"][summary["subset"]]
                f = np.asarray(baseline["frequency_hz"])
                p = np.asarray(baseline["psd"]) if baseline["psd"] is not None else None
                reference = None
                if p is not None:
                    channel = summary["channel"]
                    psd = p.mean(axis=1) if channel == "ROI" else p[:, self.channels.index(channel)]
                    mask = abs(f-summary["frequency_hz"]) <= max(.25, (f[1]-f[0])/2)
                    reference = float(psd[mask].sum()*(f[1]-f[0]))
                task_power = summary["mean"]
                change = float(10*np.log10(task_power/reference)) if reference and reference > 1e-12 and task_power and task_power > 0 else None
                result["baseline_comparison"].append({"subset": summary["subset"], "condition": summary["condition"],
                    "channel": summary["channel"], "n_trials": summary["n"], "n_baseline_windows": baseline["n_windows"],
                    "task_power_uv2": task_power, "baseline_power_uv2": reference, "change_db": change,
                    "reason": "" if change is not None else "匹配基线不足或基线功率接近零"})
        return result
