"""Frozen, calibration-free task metrics. No fitted subject model or label tuning."""
import numpy as np
from scipy.signal import butter, sosfiltfilt, welch


def wilson(correct, total):
    if not total:
        return None
    p, z = correct / total, 1.95996398454
    center = (p + z*z/(2*total)) / (1+z*z/total)
    radius = z*np.sqrt(p*(1-p)/total+z*z/(4*total*total))/(1+z*z/total)
    return [float(center-radius), float(center+radius)]


def mean_ci(values):
    values = np.asarray(values, dtype=float)
    values = values[np.isfinite(values)]
    if not len(values):
        return {"n": 0, "mean": None, "ci95": None}
    ci = None
    if len(values) >= 3:
        rng = np.random.default_rng(20261028)
        estimates = np.mean(rng.choice(values, (2000, len(values))), axis=1)
        ci = np.quantile(estimates, [.025, .975]).tolist()
    return {"n": len(values), "mean": float(np.mean(values)), "ci95": ci}


def canonical_correlation(x, y):
    def basis(a):
        a = a - a.mean(axis=0)
        u, s, _ = np.linalg.svd(a, full_matrices=False)
        return u[:, s > (s[0] * 1e-10 if len(s) else 0)]
    a, b = basis(x), basis(y)
    if not a.shape[1] or not b.shape[1]:
        return 0.
    return float(np.clip(np.linalg.svd(a.T @ b, compute_uv=False)[0], 0, 1))


def fbcca(data, fs, frequencies):
    """Samples × electrodes, fixed three filter bands and three harmonics."""
    if fs < 180:
        raise ValueError("固定 FBCCA 方案要求采样率至少 180 Hz（最高滤波边界 80 Hz）")
    t = np.arange(len(data)) / fs
    references = [np.column_stack([fn(2*np.pi*f*h*t) for h in (1, 2, 3) for fn in (np.sin, np.cos)]) for f in frequencies]
    scores = np.zeros(len(frequencies))
    for k, low in enumerate((6, 14, 22), 1):
        filtered = sosfiltfilt(butter(4, [low, 80], fs=fs, btype="bandpass", output="sos"), data, axis=0)
        scores += (k**-1.25 + .25) * np.asarray([canonical_correlation(filtered, ref)**2 for ref in references])
    return int(np.argmax(scores)), scores.tolist()


def spectral_guard(frequencies, df):
    # Eight 1-Hz-spaced targets require inter-target background bins. Preserve
    # the four-class definition; never narrow below one actual spectral bin.
    return max(.25, df) if len(frequencies) == 8 else .5


def local_snr(data, fs, target, frequencies, line, *, details=False):
    freq, power = welch(data, fs=fs, axis=0, nperseg=len(data))
    power = power.mean(axis=1)
    result = []
    powers = []
    guard = spectral_guard(frequencies, fs/len(data))
    for harmonic in (1, 2, 3):
        f = target * harmonic
        signal = np.abs(freq-f) <= max(.25, fs/len(data)/2)
        noise = (np.abs(freq-f) <= 2) & (np.abs(freq-f) >= .5)
        for other in frequencies:
            for h in (1, 2, 3):
                noise &= np.abs(freq-other*h) > guard
        if isinstance(line, (float, int)):
            for h in (1, 2):
                noise &= np.abs(freq-line*h) > 1
        denominator = float(np.median(power[noise])) if noise.sum() >= 3 else 0
        numerator = float(np.mean(power[signal])) if signal.any() else 0
        result.append(float(10*np.log10(numerator/denominator)) if denominator > 0 and numerator > 0 else None)
        powers.append({"harmonic": harmonic, "frequency_hz": f, "target_psd_uv2_per_hz": numerator,
                       "background_psd_uv2_per_hz": denominator if denominator > 0 else None,
                       "target_band_power_uv2": float(power[signal].sum()*fs/len(data)), "noise_bins": int(noise.sum()),
                       "target_exclusion_halfwidth_hz": guard})
    return (result, powers) if details else result


def band_power(data, fs, band):
    freq, p = welch(data, fs=fs, axis=0, nperseg=len(data), detrend="constant")
    mask = (freq >= band[0]) & (freq <= band[1])
    return p[mask].sum(axis=0) * fs / len(data)


def mi_metrics(baseline, task, fs):
    result = {}
    for label, band in (("mu", (8, 13)), ("beta", (13, 30))):
        base = band_power(baseline, fs, band)
        active = band_power(task, fs, band)
        if np.any(base <= 1e-12):
            raise ValueError("基线频带功率接近零，无法计算 ERD")
        erd = 100 * (active-base) / base
        db = 10*np.log10(np.maximum(active, 1e-12)/base)
        result.update({f"{label}_C3_erd_pct": float(erd[0]), f"{label}_C4_erd_pct": float(erd[1]),
                       f"{label}_lateral_db": float(db[0]-db[1])})
        for i, channel in enumerate(("C3", "C4")):
            result.update({f"{label}_{channel}_baseline_power_uv2": float(base[i]),
                           f"{label}_{channel}_task_power_uv2": float(active[i]),
                           f"{label}_{channel}_change_db": float(db[i])})
    # Positive means stronger C4 suppression: left hand. Uncertain is counted as not correct.
    d = result["mu_lateral_db"]
    result["prediction"] = "左手" if d > .6 else ("右手" if d < -.6 else "不确定")
    return result


def classification_summary(rows, labels, prediction_key="prediction"):
    # Missing evidence and a fixed-rule abstention are different outcomes.
    def prediction(row):
        if not row.get("analyzable", True):
            return "数据不可分析"
        value = row.get(prediction_key)
        return value if value in labels else "模型不确定"
    columns = [*labels, "模型不确定", "数据不可分析"]
    matrix = [[sum(r["condition"] == truth and prediction(r) == value for r in rows)
               for value in columns] for truth in labels]
    correct = sum(prediction(r) == r["condition"] for r in rows)
    counts = [sum(r["condition"] == label for r in rows) for label in labels]
    per_class = {str(label): (matrix[i][i]/counts[i] if counts[i] else None) for i, label in enumerate(labels)}
    available = [v for v in per_class.values() if v is not None]
    precision, f1 = {}, {}
    for i, label in enumerate(labels):
        predicted = sum(row[i] for row in matrix)
        precision[str(label)] = matrix[i][i]/predicted if predicted else None
        # An observed class with no correct predictions has F1=0; absent truth is unavailable.
        f1[str(label)] = 2*matrix[i][i]/(counts[i]+predicted) if counts[i] else None
    normalized = [[v/counts[i] if counts[i] else None for v in row] for i, row in enumerate(matrix)]
    data_unavailable = sum(not r.get("analyzable", True) for r in rows)
    abstained = sum(r.get("analyzable", True) and r.get(prediction_key) not in labels for r in rows)
    classified = sum(prediction(r) in labels for r in rows)
    return {"n": len(rows), "accuracy": correct/len(rows) if rows else None,
            "unknown_target": sum(r.get("condition") not in labels for r in rows),
            "unclassified": sum(r.get(prediction_key) not in labels for r in rows),
            "unclassified_fraction": sum(r.get(prediction_key) not in labels for r in rows)/len(rows) if rows else None,
            "ci95_wilson": wilson(correct, len(rows)), "balanced_accuracy": float(np.mean(available)) if len(available) == len(labels) else None,
            "per_condition": per_class, "confusion": matrix, "labels": labels,
            "prediction_columns": columns, "confusion_row_fraction": normalized,
            "precision_per_condition": precision, "f1_per_condition": f1,
            "macro_f1": float(np.mean(list(f1.values()))) if all(v is not None for v in f1.values()) else None,
            "data_unavailable": data_unavailable, "model_abstained": abstained,
            "coverage": classified/len(rows) if rows else None,
            "selective_accuracy": correct/classified if classified else None,
            "nominal_chance": 1/len(labels)}
