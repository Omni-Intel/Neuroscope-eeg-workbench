"""Audit four-condition acquisition without running the legacy binary decoder."""
from itertools import pairwise

import numpy as np

from neuroscope_eeg.io.bids_export import _event_rows


def audit_collection(root, run, device, data, valid, indices, timestamps, events, plan):
    result = {'status': 'pending', 'collection_only': True,
              'reason': '四条件运动想象：任务响应分析待更改，分类模型待接入。',
              'trials': [], 'timecourses': [], 'condition_labels': list(plan.mi_labels),
              'selected_channels': [name for name, kind, unit in zip(device['channel_names'], device['channel_types'], device['channel_units'])
                                    if kind == 'eeg' and unit in {'uV', 'µV', 'μV'}]}
    fs = device['sfreq']
    try:
        aligned = _event_rows(root, run, fs, len(data), allow_estimated=not run['external_recording'])
        if len(aligned) != len(events) or any(float(r['onset']) < 0 for r in aligned):
            raise ValueError('事件数量或样本游标无效')
    except (ValueError, KeyError, TypeError) as exc:
        result['collection_error'] = '事件对齐不可用：' + str(exc)
        return result
    result['timing_methods'] = sorted({r['timing_method'] for r in aligned})
    groups = {}
    durations = dict(plan.phases)
    phase_names = [*durations, 'trial_complete']
    for event, timing in zip(events, aligned):
        payload = event.get('payload', {})
        if payload.get('is_practice') or 'trial' not in payload or event['phase'] not in phase_names:
            continue
        groups.setdefault(payload['trial'], {}).setdefault(event['phase'], []).append(
            {**event, 'onset': float(timing['onset'])})
    for trial, entries in sorted(groups.items()):
        phases = {k: v[0] for k, v in entries.items()}
        anchor = phases.get('imagery') or phases.get('cue') or next(iter(phases.values()))
        payload = anchor.get('payload', {})
        condition = payload.get('condition', anchor.get('label'))
        row = {'trial': trial, 'formal_trial_index': payload.get('formal_trial_index'), 'block': payload.get('block'),
               'condition': condition, 'condition_code': plan.mi_labels.index(condition)+1 if condition in plan.mi_labels else None,
               'completed': 'trial_complete' in phases, 'data_complete': False,
               'imagery_onset_sec': phases.get('imagery', {}).get('onset'),
               'collection_issue': '', 'analysis_status': 'pending_model'}
        try:
            if set(phase_names) != phases.keys() or any(len(v) != 1 for v in entries.values()):
                raise ValueError('阶段缺失或重复')
            if condition not in plan.mi_labels or any(e.get('payload', {}).get('condition') != condition for e in phases.values()):
                raise ValueError('提示条件缺失或不一致')
            formal = row['formal_trial_index']
            if not isinstance(formal, int) or not 0 <= formal < plan.total_trials or condition != plan.mi_labels[formal % plan.conditions]:
                raise ValueError('正式试次索引或固定顺序不一致')
            observed = {a: phases[b]['onset']-phases[a]['onset'] for a, b in pairwise(phase_names)}
            row['phase_durations_sec'] = observed
            start, end = phases['fixation']['onset'], phases['trial_complete']['onset']
            if not 0 <= start < end <= len(data)/fs+1/fs or any(abs(observed[k]-v) > .25 for k, v in durations.items()):
                raise ValueError('阶段时间或数据边界不符合计划')
            a, b = round(start*fs), min(len(data), round(end*fs))
            row.update(start_sample=a, end_sample_exclusive=b,
                       imagery_start_sample=round(phases['imagery']['onset']*fs),
                       imagery_end_sample_exclusive=round(phases['rest']['onset']*fs))
            if b <= a or not valid[a:b].all() or not np.isfinite(data[a:b]).all():
                raise ValueError('包含无效样本')
            if np.any(np.diff(indices[a:b]) != 1) or not np.isfinite(timestamps[a:b]).all() or np.any(np.diff(timestamps[a:b]) <= 0) or np.any(np.diff(timestamps[a:b]) > 2.5/fs):
                raise ValueError('样本序号或时间戳不连续')
            row['data_complete'] = True
        except (ValueError, TypeError) as exc:
            row['collection_issue'] = str(exc)
        result['trials'].append(row)
    result['collection_counts'] = [
        {'condition': label, 'planned': plan.total_trials//plan.conditions,
         'observed': sum(r['condition'] == label for r in result['trials']),
         'completed': sum(r['condition'] == label and r['completed'] for r in result['trials']),
         'data_complete': sum(r['condition'] == label and r['data_complete'] for r in result['trials'])}
        for label in plan.mi_labels]
    return result
