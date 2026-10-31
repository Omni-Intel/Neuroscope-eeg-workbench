from dataclasses import replace

import numpy as np
import pytest

from neuroscope_eeg.desktop.ssvep_presentation import FREQUENCIES, target_layout, target_levels
from neuroscope_eeg.protocol_config import AssessmentProtocol


@pytest.mark.parametrize('refresh',[60,75,120,144])
def test_all_eight_targets_flicker_at_declared_frequencies(refresh):
    frames=np.array([target_levels('flicker',3,i,refresh) for i in range(refresh*10)])
    assert frames.shape == (refresh*10,8)
    assert set(frames.flat) == {0,255}
    bins=np.fft.rfftfreq(len(frames),1/refresh)
    for i,f in enumerate(FREQUENCIES):
        power=abs(np.fft.rfft(frames[:,i]-frames[:,i].mean()))
        assert bins[np.argmax(power)] == pytest.approx(f)
    assert target_levels('cue',7,0,refresh)[7] == 170
    assert target_levels('cue',7,0,refresh).count(30) == 7


@pytest.mark.parametrize('refresh', [60, 75, 120, 144])
def test_sequential_mode_flashes_only_cued_target_at_each_frequency(refresh):
    for target, frequency in enumerate(FREQUENCIES):
        frames = np.array([target_levels('flicker', target, i, refresh, sequential=True)
                           for i in range(refresh * 10)])
        assert np.all(np.delete(frames, target, axis=1) == 30)
        assert set(frames[:, target]) == {0, 255}
        bins = np.fft.rfftfreq(len(frames), 1 / refresh)
        power = abs(np.fft.rfft(frames[:, target] - frames[:, target].mean()))
        assert bins[np.argmax(power)] == pytest.approx(frequency)


def test_recorded_sequential_mode_is_versioned_and_old_simultaneous_mode_preserved():
    new = AssessmentProtocol.defaults('SSVEP')
    assert new.sequential_eight and new.eight_target and new.conditions == 8
    assert new.to_dict()['version'] == 'guided-assessment-v5'
    assert AssessmentProtocol.from_dict(new.to_dict()) == new
    old = replace(new, ssvep_mode='simultaneous_eight_v3')
    saved = old.to_dict()
    assert saved['version'] == 'guided-assessment-v3'
    assert AssessmentProtocol.from_dict(saved).to_dict() == saved
    assert not AssessmentProtocol.from_dict(saved).sequential_eight


@pytest.mark.parametrize('size',[(800,600),(1920,1080),(1080,1920)])
def test_grid_has_eight_nonoverlapping_squares_and_clear_center(size):
    w,h=size
    boxes,_=target_layout(w,h,24,15)
    assert len(boxes)==8
    for i,(x,y,a,b) in enumerate(boxes):
        assert a==b and 0<=x<x+a<=w and 0<=y<y+b<=h
        assert not (x<=w/2<=x+a and y<=h/2<=y+b)
        for xx,yy,aa,bb in boxes[i+1:]:
            assert x+a<=xx or xx+aa<=x or y+b<=yy or yy+bb<=y


def test_legacy_record_is_not_migrated_until_new_run():
    old=replace(AssessmentProtocol.defaults('SSVEP'),ssvep_mode='single_target_v2',total_trials=12,block_trials=4)
    saved=old.to_dict()
    restored=AssessmentProtocol.from_dict(saved)
    assert restored.conditions==4 and restored.to_dict()==saved
    upgraded=restored.for_new_run().validate()
    assert upgraded.conditions==8 and upgraded.total_trials==16 and upgraded.block_trials==8
    assert AssessmentProtocol.from_dict(upgraded.to_dict())==upgraded


@pytest.mark.parametrize('mode', ['simultaneous_eight_v3', 'sequential_eight_v5'])
def test_eight_class_fbcca_and_word_export(tmp_path, mode):
    import json

    from docx import Document

    from neuroscope_eeg.reports.generate import generate_report
    from tests.analysis.test_assessment import guided_fixture
    _plan,root=guided_fixture(tmp_path/'record','SSVEP',ssvep_mode=mode,total_trials=8,block_trials=8)
    from neuroscope_eeg.desktop.display_timing import DisplayTiming
    from neuroscope_eeg.desktop.ssvep_clock import SSVEPFrameClock
    timing, clock = DisplayTiming(75, 100), SSVEPFrameClock(75)
    for i in range(76):
        context = ('formal', 'flicker' if i < 75 else 'rest', 8)
        timing.observe('frame_swapped', i/75, context)
        clock.observe(i/75, context, i)
    snapshot = dict(timing.snapshot(), ssvep_frame_clock=clock.snapshot())
    events_path = root/'events.jsonl'
    events = [json.loads(line) for line in events_path.read_text(encoding='utf-8').splitlines()]
    next(e for e in events if e['phase'] == 'stop')['payload']['display_timing'] = snapshot
    events_path.write_text(''.join(json.dumps(e, ensure_ascii=False)+'\n' for e in events), encoding='utf-8')
    path=generate_report(root)
    latest=json.loads((root/'analysis/latest.json').read_text(encoding='utf-8'))
    report=json.loads((root/'analysis'/latest['generation']/'assessment.json').read_text(encoding='utf-8'))
    task=report['task']
    assert task['status']=='available' and task['counts']['analyzable']==8
    assert len(task['all_trials']['confusion'])==8
    assert set(task['all_trials']['labels'])==set(FREQUENCIES)
    assert task['all_trials']['accuracy']==1
    assert all(r['mean'] is not None for r in task['response_evidence']['summary']
               if r['channel']=='ROI' and r['metric']=='snr_db' and r['harmonic']==1)
    assert len([s for s in task['response_evidence']['spectra'] if s['channel']=='ROI' and s['subset']=='analyzable'])==8
    text='\n'.join(p.text for p in Document(path).paragraphs)
    assert '异常仅记录，未据此自动中止实验' in text
    timing_csv = root/'analysis'/latest['generation']/'ssvep_frame_timing.csv'
    assert 'observed_rate_hz' in timing_csv.read_text(encoding='utf-8-sig')
    assert report['protocol']['display_timing']['ssvep_frame_clock']['trials'][0]['complete']
    assert '12.5%' in text and '八个等大方块' in text
    if mode == 'sequential_eight_v5':
        assert report['analysis_version'] == 'assessment-v1.6.0'
        assert '每次仅提示目标闪烁，其余七块保持暗色' in text
    else:
        assert '八个目标同时闪烁' in text
