"""Installed release bindings exercised above a fake hardware boundary, no physical I/O."""
import json
from dataclasses import asdict
from types import SimpleNamespace

import numpy as np
import pytest

from neuroscope_eeg.acquisition.devices import OmniBCISource
from neuroscope_eeg.desktop.device_discovery import discover_omni

sdk = pytest.importorskip('omnibci')


@pytest.mark.parametrize('device_type,width,status_width', [('esp32', 8, 3), ('stm32', 32, 12)])
def test_release_board_to_source_preserves_samples(monkeypatch, device_type, width, status_width):
    assert sdk.__version__ == '0.2.0'
    config_type = sdk.Stm32Config if device_type == 'stm32' else sdk.FrontendConfig
    config = asdict(config_type(verified=True))
    config['mode'] = 0 if device_type == 'stm32' else 1  # Native wire enums: both_bias / eeg.
    if device_type == 'esp32':
        config['reference'] = 0  # Native wire enum: SRB1.
    raw = np.arange(2*width, dtype='<i4').reshape(2, width)
    eeg = raw.astype('<f4') / 10
    calls = []

    class Native:
        def snapshot_json(self):
            return json.dumps({'state': 'stopped', 'metadata': None, 'config': config, 'generation': 1,
                                   'samples': 0, 'missing_samples': 0, 'crc_errors': 0, 'ble': {}, 'error': None})

        def start(self, timeout):
            calls.append('start')

        def read(self, timeout):
            return {'eeg_uv': eeg.tobytes(), 'raw_counts': raw.tobytes(),
                        'sequence': np.array([17, 18], dtype='<u4').tobytes(),
                        'valid': np.ones(2, dtype='?').tobytes(),
                        'sample_indices': np.array([17, 18], dtype='<u8').tobytes(),
                        'status': np.zeros((2, status_width), dtype='u1').tobytes(),
                        'mode': np.ones(2, dtype='u1').tobytes(), 'generation': 1, 'sample_rate_hz': 250,
                        'received_age_s': 0, 'channel_count': width, 'status_width': status_width,
                        'source_timestamp_us': np.array([68000, 72000], dtype='<u4').tobytes(),
                        'source_timestamp_valid': np.full(2, device_type == 'stm32', dtype='?').tobytes()}

        def read_triggers_json(self):
            events = [{'code': 42, 'sequence': 2, 'source_timestamp_ms': 72, 'timing': None}] if device_type == 'stm32' else []
            return json.dumps({'generation': 1, 'events': events})

        def stop(self, timeout):
            calls.append('stop')

        def close(self, timeout):
            calls.append('close')

    def connect(endpoint, timeout, selected='esp32'):
        assert endpoint == 'serial://CONTRACT_TEST' and selected == device_type
        calls.append('connect')
        return Native()

    monkeypatch.setattr(sdk._native, 'NativeDevice', SimpleNamespace(connect=connect))
    source = OmniBCISource('serial://CONTRACT_TEST', device_type)
    try:
        source.start()  # Imports the installed SDK, then uses its genuine Board/config/SampleBatch classes.
        chunk = source.read_chunk()
        np.testing.assert_array_equal(chunk.data, eeg.T)
        np.testing.assert_array_equal(chunk.auxiliaries['raw_counts'], raw)
        np.testing.assert_array_equal(chunk.sample_indices, [17, 18])
        np.testing.assert_array_equal(chunk.auxiliaries['source_timestamp_us'], [68000, 72000])
        assert chunk.valid.all() and source.metadata.n_channels == width
        assert source.metadata.extra['sdk_version'] == '0.2.0'
        assert source.metadata.extra['native_sdk_version'] == sdk.SDK_VERSION
        triggers = json.loads(str(chunk.auxiliaries['triggers_json']))
        assert [e['code'] for e in triggers] == ([42] if device_type == 'stm32' else [])
    finally:
        source.stop()
    assert calls == ['connect', 'start', 'stop', 'close']


@pytest.mark.parametrize('device_type', ['esp32', 'stm32'])
def test_release_discovery_routes_transport_and_model(monkeypatch, device_type):
    monkeypatch.setattr(sdk._native, 'serial_ports', lambda: ['COM_TEST'])
    calls = []
    def ble(timeout, selected='esp32'):
        calls.append((timeout, selected))
        return json.dumps([{'id': 'test-id', 'name': 'Test board', 'address': 'test-address', 'rssi_dbm': -50}])
    monkeypatch.setattr(sdk._native, 'discover_ble_json', ble)
    assert discover_omni('serial', device_type) == [{'endpoint': 'serial://COM_TEST', 'name': 'COM_TEST', 'type': device_type}]
    assert discover_omni('ble', device_type) == [{'endpoint': 'ble://test-id', 'name': 'Test board', 'type': device_type}]
    assert calls == [(6.0, device_type)]
