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


def test_eight_class_fbcca_and_word_export(tmp_path):
    import json

    from docx import Document

    from neuroscope_eeg.reports.generate import generate_report
    from tests.analysis.test_assessment import guided_fixture
    _plan,root=guided_fixture(tmp_path/'record','SSVEP',ssvep_mode='simultaneous_eight_v3',total_trials=8,block_trials=8)
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
    assert '12.5%' in text and '八个等大方块' in text
