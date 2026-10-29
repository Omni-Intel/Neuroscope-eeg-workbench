"""N-back-derived descriptive features; independent of task scoring and quality decisions."""
import inspect
from collections import defaultdict
from fractions import Fraction
from importlib.metadata import version

import numpy as np
from scipy.signal import butter, resample_poly, sosfiltfilt, welch

from neuroscope_eeg.analysis.protocol_segments import quality_intervals

METHOD = {
    'source': '8.21/nback_eeg_toolkit/vendored/epoch_feature_extraction.py; step3_epoch_metrics.py',
    'window_sec': 4, 'target_sfreq': 250, 'max_epochs_per_segment_channel': 30,
    'preprocessing': 'native-rate demean and fourth-order Butterworth 1-40 Hz zero-phase per contiguous 4 s epoch; polyphase resample to 250 Hz; no rereference or notch',
    'difference_from_reference': 'Reference uses 1-80 Hz, Fpz reference, N-back conditions and first <=30 epochs. Here use 1-40 Hz, acquisition reference, eyes-open/closed/formal segments and evenly spaced <=30 eligible windows per channel. Never compare absolute values with reference report.',
    'screening': 'native uV EEG only; valid finite continuous samples; raw ptp 0.1..300 uV; confirmed rails excluded; no incomplete windows or concatenated pauses',
    'aggregation': 'per-channel epoch medians, then median across channels within segment; no cross-condition pooling or quality score',
    'slope': 'Hann Welch full 1000 samples, 2-40 Hz log-log linear fit with 1e-20 offset; oscillatory peaks NOT removed; descriptive slope, not aperiodic exponent',
    'entropy_parameters': 'mne-features pinned defaults; actual function signatures recorded; antropy DFA defaults, LZ median binary normalized',
}
FEATURES = ('rms', 'ptp_amp', 'variance', 'hjorth_mobility', 'hjorth_complexity',
            'spect_entropy', 'samp_entropy', 'app_entropy', 'svd_entropy', 'svd_fisher_info',
            'hurst_exp', 'higuchi_fd', 'katz_fd')


def feature_values(x, fs=250):
    import antropy as ant
    from mne_features.univariate import get_univariate_funcs
    funcs = get_univariate_funcs(fs)
    values, errors = {}, {}
    for name in FEATURES:
        try:
            value = float(np.asarray(funcs[name](x[None, :])).ravel()[0])
            values[name] = value if np.isfinite(value) else None
            if values[name] is None:
                errors[name] = 'nonfinite estimate'
        except (ValueError, TypeError, ZeroDivisionError, FloatingPointError, np.linalg.LinAlgError) as exc:
            values[name], errors[name] = None, str(exc)
    for name, compute in {'dfa_exponent': lambda: ant.detrended_fluctuation(x),
                          'lziv_complexity': lambda: ant.lziv_complexity(x > np.median(x), normalize=True)}.items():
        try:
            value = float(compute())
            values[name] = value if np.isfinite(value) else None
            if values[name] is None:
                errors[name] = 'nonfinite estimate'
        except (ValueError, ZeroDivisionError, FloatingPointError) as exc:
            values[name], errors[name] = None, str(exc)
    f, p = welch(x, fs=fs, window='hann', nperseg=len(x), noverlap=0)
    mask = (f >= 2) & (f <= 40)
    values['spect_slope'] = float(np.polyfit(np.log(f[mask]), np.log(p[mask]+1e-20), 1)[0])
    return values, errors


def assess_features(data, valid, indices, timestamps, device, profile, phases, selected_channels, progress):
    result = {'method': dict(METHOD), 'epochs': [], 'summary': [], 'selection': [], 'errors': [], 'status': 'unavailable'}
    fs = device['sfreq']
    if fs < 100:
        result['reason'] = '统一 1–40 Hz 特征要求原始采样率至少 100 Hz，不以升采样补足带宽'
        return result
    intervals = quality_intervals(phases)
    if not intervals:
        result['reason'] = '缺少可对齐区段，不混合指导、练习和正式数据计算通用特征'
        return result
    chosen = [i for i, (name, unit, kind) in enumerate(zip(device['channel_names'], device['channel_units'], device['channel_types']))
              if kind == 'eeg' and unit in {'uV', 'µV', 'μV'} and (not selected_channels or name in selected_channels)]
    if not chosen:
        result['reason'] = '缺少已确认微伏单位的 EEG 分析通道'
        return result
    try:
        import antropy  # noqa: F401
        from mne_features.univariate import get_univariate_funcs
    except ImportError as exc:
        result['reason'] = '通用指标依赖未安装，请重新运行 setup-workbench.ps1：' + str(exc)
        return result
    result['versions'] = {k: version(k) for k in ('mne-features', 'antropy', 'numba')}
    result['method']['signatures'] = {k: str(inspect.signature(v)) for k, v in get_univariate_funcs(250).items() if k in FEATURES}
    groups = defaultdict(list)
    n = round(4*fs)
    for interval in intervals:
        if not interval['completed']:
            continue
        label = interval['label'] if not interval['label'].startswith('正式') else '正式实验'
        groups[label].extend(range(interval['start_sample'], interval['end_sample']-n+1, n))
    ratio = Fraction(250/fs).limit_denominator(10000)
    sos = butter(4, [1, 40], fs=fs, btype='bandpass', output='sos')
    for label, starts in groups.items():
        for c in chosen:
            name = device['channel_names'][c]
            progress(f'通用特征：{label} / {name}')
            eligible = []
            rejected = defaultdict(int)
            for a in starts:
                b = a+n
                x = np.asarray(data[a:b, c], dtype=float)
                if not valid[a:b].all() or not np.isfinite(x).all():
                    rejected['invalid_samples'] += 1
                elif (np.any(np.diff(indices[a:b]) != 1) or not np.isfinite(timestamps[a:b]).all()
                      or np.any(np.diff(timestamps[a:b]) <= 0) or np.any(np.diff(timestamps[a:b]) > 2.5/fs)):
                    rejected['discontinuous'] += 1
                elif np.ptp(x) < .1 or np.ptp(x) > 300:
                    rejected['amplitude'] += 1
                elif name in profile.get('adc_rails_uv', {}) and (np.any(x <= profile['adc_rails_uv'][name][0]) or np.any(x >= profile['adc_rails_uv'][name][1])):
                    rejected['rails'] += 1
                else:
                    eligible.append(a)
            picked = [eligible[i] for i in np.linspace(0, len(eligible)-1, min(30, len(eligible)), dtype=int)]
            result['selection'].append({'segment': label, 'channel': name, 'candidate': len(starts), 'eligible': len(eligible), 'selected': len(picked), 'rejected': dict(rejected)})
            for a in picked:
                x = np.asarray(data[a:a+n, c], dtype=float)
                x = resample_poly(sosfiltfilt(sos, x-x.mean()), ratio.numerator, ratio.denominator)
                if len(x) != 1000:
                    result['errors'].append({'segment': label, 'channel': name, 'start_sample': a, 'reason': 'resampled length != 1000'})
                    continue
                values, errors = feature_values(x)
                result['epochs'].append({'segment': label, 'channel': name, 'start_sample': a, 'end_sample': a+n, **values})
                result['errors'].extend({'segment': label, 'channel': name, 'start_sample': a, 'metric': k, 'reason': v} for k, v in errors.items())
    for label in groups:
        for metric in (*FEATURES, 'dfa_exponent', 'lziv_complexity', 'spect_slope'):
            channel_medians, count = [], 0
            for c in chosen:
                values = [r[metric] for r in result['epochs'] if r['segment'] == label and r['channel'] == device['channel_names'][c] and r[metric] is not None]
                count += len(values)
                if values:
                    channel_medians.append(float(np.median(values)))
            result['summary'].append({'segment': label, 'metric': metric, 'value': float(np.median(channel_medians)) if channel_medians else None,
                                      'n_channels': len(channel_medians), 'n_channel_epochs': count})
    result['status'] = 'available' if result['epochs'] else 'unavailable'
    if not result['epochs']:
        result['reason'] = '没有满足连续性、幅值及完整 4 秒窗要求的数据'
    return result
