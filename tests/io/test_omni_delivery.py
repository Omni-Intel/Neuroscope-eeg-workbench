import json

import numpy as np
import pyedflib
import pytest

from neuroscope_eeg.core.models import EEGChunk, SourceMetadata
from neuroscope_eeg.io.bids_export import export_delivery
from neuroscope_eeg.io.native_recording import NativeRecorder
from neuroscope_eeg.io.omni_delivery import delivery_profile


def device(count=32):
    return {'source_type': 'omnibci', 'channel_names': [f'CH{i+1}' for i in range(count)],
            'channel_units': ['uV']*count, 'extra': {'device_model': 'stm32' if count == 32 else 'esp32',
            'sdk_version': '0.2.0', 'native_sdk_version': '0.2.0', 'sdk_revision': 'fixture',
            'frontend_config': {'verified': True, 'gains': [24]*count}}}


@pytest.mark.parametrize('count', [8, 32])
def test_export_configuration_is_not_analysis_confirmation(count):
    p = delivery_profile(device(count), {'confirmed': False})
    assert p['delivery_confirmed'] and not p['confirmed']
    assert p['eeg_reference'] == p['power_line_frequency'] == 'n/a'
    assert len(p['physical_min']) == count
    assert p['physical_min'][0] < -4_500_000/24*(2**23/(2**23-1))
    assert p['physical_max'][0] > 4_500_000/24
    assert delivery_profile(device(count), {'eeg_reference':'Cz','power_line_frequency':50})['unrecorded_export_fields'] == []


@pytest.mark.parametrize('mutation', ['version', 'unverified', 'gain', 'unit', 'other'])
def test_unknown_contract_never_gets_auto_confirmation(mutation):
    d = device()
    if mutation == 'version': d['extra']['sdk_version'] = '0.3.0'
    if mutation == 'unverified': d['extra']['frontend_config']['verified'] = False
    if mutation == 'gain': d['extra']['frontend_config']['gains'][0] = 0
    if mutation == 'unit': d['channel_units'][0] = 'counts'
    if mutation == 'other': d['source_type'] = 'brainco'
    assert not delivery_profile(d, {'delivery_confirmed':True}).get('delivery_confirmed')


@pytest.mark.parametrize('count', [8, 32])
@pytest.mark.parametrize('paradigm', ['SSVEP', '运动想象'])
def test_real_source_without_scalp_map_exports_and_retains_original(tmp_path, count, paradigm):
    d = device(count)
    meta = SourceMetadata('omnibci','omnibci',250,tuple(d['channel_names']),('eeg',)*count,('uV',)*count,d['extra'])
    name = ('SSVEP' if paradigm == 'SSVEP' else 'MI') + '-20261030'
    recorder = NativeRecorder.start(root_dir=tmp_path, participant_id='00000001', paradigm=paradigm,
        preset='完整采集', metadata=meta, paradigm_code=name, unique_name=name,
        config={'experiment_metadata':{'full_name':'fixture','unique_name':name,'description':'test'}})
    data = np.tile(np.linspace(-180000,180000,503,dtype='float32'),(count,1))
    indices = np.arange(503)
    recorder.submit(EEGChunk(meta,data,indices/250,0,indices,np.ones(503,dtype=bool)))
    recorder.stop(status='completed',reason='completed')
    raw = recorder.session_dir/'raw/eeg.f32'
    original = raw.read_bytes()
    output = export_delivery(recorder.session_dir,tmp_path/'data',allow_estimated_timing=True)
    with pyedflib.EdfReader(str(next(output.rglob('*.edf')))) as reader:
        assert reader.getSignalLabels() == d['channel_names']
        assert list(reader.getNSamples()) == [503]*count
        assert list(reader.getSampleFrequencies()) == [250]*count
        np.testing.assert_allclose(reader.readSignal(0),data[0],atol=5.73)
    assert raw.read_bytes() == original
    encoding = json.loads((recorder.session_dir/'delivery/edf_encoding.json').read_text())
    assert encoding['channels'][0]['max_absolute_error'] <= encoding['channels'][0]['quantization_step']
