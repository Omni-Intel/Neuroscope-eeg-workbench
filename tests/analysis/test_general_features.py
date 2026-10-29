"""Verify source-equivalent computations and selection boundaries, not just report text."""
import numpy as np
import pytest
from scipy.signal import welch

from neuroscope_eeg.analysis.general_features import assess_features, feature_values


def test_matches_source_libraries():
    import antropy as ant
    from mne_features.univariate import get_univariate_funcs
    x = np.random.default_rng(45).normal(size=1000)
    values, errors = feature_values(x)
    funcs = get_univariate_funcs(250)
    for key in ('samp_entropy', 'app_entropy', 'spect_entropy', 'hjorth_mobility', 'hjorth_complexity', 'svd_entropy', 'higuchi_fd', 'hurst_exp'):
        assert values[key] == pytest.approx(float(funcs[key](x[None, :])[0]))
    assert values['lziv_complexity'] == pytest.approx(ant.lziv_complexity(x > np.median(x), normalize=True))
    f,p = welch(x, fs=250, nperseg=1000, noverlap=0)
    m=(f>=2)&(f<=40)
    assert values['spect_slope'] == pytest.approx(np.polyfit(np.log(f[m]), np.log(p[m]+1e-20),1)[0])
    assert not errors


def test_excludes_invalid_flat_gap_and_short_windows():
    fs=250
    x=np.random.default_rng(9).normal(size=(6000,1))
    x[1000:2000]=0
    valid=np.ones(6000,dtype=bool);valid[2500]=False
    indices=np.arange(6000);indices[3500:]+=1
    stamps=np.arange(6000)/fs
    phases=[{'phase': 'baseline_eyes_open', 'label': '睁眼静息', 'completed': True,'start_sample': 0,'end_sample': 4500},
            {'phase': 'baseline_eyes_closed','label': '闭眼静息','completed': True,'start_sample': 4500,'end_sample': 6000}]
    dev={'sfreq': fs,'channel_names': ['C3'],'channel_types': ['eeg'],'channel_units': ['uV']}
    result=assess_features(x,valid,indices,stamps,dev,{},phases,['C3'],lambda _:None)
    assert result['status']=='available'
    assert [r['start_sample'] for r in result['epochs']]==[0,4500]
    assert result['selection'][0]['rejected']=={'amplitude':1,'invalid_samples':1,'discontinuous':1}
    dev['sfreq']=80
    assert assess_features(x,valid,indices,stamps,dev,{},phases,[],lambda _:None)['status']=='unavailable'
    dev['sfreq']=250;dev['channel_units']=['unknown']
    assert assess_features(x,valid,indices,stamps,dev,{},phases,[],lambda _:None)['status']=='unavailable'
