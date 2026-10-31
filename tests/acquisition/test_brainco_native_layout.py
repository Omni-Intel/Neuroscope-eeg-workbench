"""Offline proof against the real SDK binary, not mocked get_eeg_buffer output.

Synthetic protobuf records enter MessageParser; no network or device is used.
"""
import json
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from neuroscope_eeg.acquisition.vendor.brainco_acquirer import BrainCoAcquirer
from neuroscope_eeg.acquisition.devices import DemoSource


def varint(value):
    out = bytearray()
    while value > 127:
        out.append((value & 127) | 128)
        value >>= 7
    out.append(value)
    return bytes(out)


def field(tag, value):
    return varint(tag * 8 + 2) + varint(len(value)) + value


def scalar(tag, value):
    return varint(tag * 8) + varint(value)


def frame(payload):
    packet = b"BRNC\x02\x0b" + struct.pack("<H", len(payload)) + bytes([0, 2, 0]) + payload
    crc = 65535
    for byte in packet:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return packet + crc.to_bytes(2, "little")


def eeg_packet(timestamp=1000):
    # MainApp.eeg=3; EegAcqResponse.data=2; EegData.sample_1..10.
    # EegSample.timestamp=1, channels=2; 4 ADS1299 groups, each 3 status + 24 ADC bytes.
    samples = []
    data = scalar(6, 1) + scalar(7, 4)  # 250 Hz, gain 6 in this SDK.
    for sample, tag in enumerate([1, 2, 3, 4, 8, 9, 10, 11, 12, 13]):
        raw = bytearray(108)
        counts = []
        for ch in range(32):
            count = (sample + 1) * (ch + 1) * (-1 if ch % 2 else 1)
            counts.append(count)
            offset = (ch // 8) * 27 + 3 + (ch % 8) * 3
            raw[offset:offset + 3] = (count & 0xFFFFFF).to_bytes(3, "big")
        samples.append(counts)
        data += field(tag, scalar(1, timestamp + sample * 4) + field(2, raw))
    return frame(field(3, field(2, data))), np.asarray(samples, dtype=np.float32) * (4.5e6 / 6 / 2**23)


@pytest.mark.parametrize("timestamp", [1000, 123456789])
def test_real_sdk_timestamp_column_channel_order_count_and_native_save(timestamp, tmp_path):
    sdk = pytest.importorskip("bcigo_sdk")
    if sdk.__version__ != "2.1.2":
        pytest.skip("This native layout proof targets SDK 2.1.2")
    sdk.set_cfg(10000, 256, 256)
    sdk.clear_eeg_buffer()
    packet, expected = eeg_packet(timestamp)
    parser = sdk.MessageParser("bcigo", sdk.MsgType.BCIGo)
    try:
        parser.receive_data(packet)
        raw = np.asarray(sdk.get_eeg_buffer(100, True))
        assert raw.shape == (10, 33)
        ticks = np.asarray(timestamp + np.arange(10) * 4, dtype=np.float32).astype(np.float64)
        np.testing.assert_array_equal(raw[:, 0], ticks)
        np.testing.assert_allclose(raw[:, 1:], expected)
        backend = BrainCoAcquirer()
        backend._sdk, backend._client = sdk, object()
        parser.receive_data(packet)
        # Callback and polling are two observations of the SAME samples, not two recordings.
        backend._handle_eeg_data_callback(raw)
        assert backend._callback_sample_count == 10
        assert backend._total_samples_seen == 0
        source = DemoSource(backend, "brainco")
        chunk = source.read_chunk()
        np.testing.assert_allclose(chunk.data, expected.T)
        np.testing.assert_array_equal(chunk.sample_indices, np.arange(10))
        np.testing.assert_array_equal(chunk.auxiliaries["brainco_device_timestamps"], ticks)
        assert backend._total_samples_seen == 10
        assert source.read_chunk().data.shape == (32, 0)
        assert backend._total_samples_seen == 10
        parser.receive_data(packet)
        second = source.read_chunk()
        np.testing.assert_array_equal(second.sample_indices, np.arange(10, 20))
        # Duplicate/rounded device timestamps must not delete any EEG samples.
        from neuroscope_eeg.io.native_recording import NativeRecorder, read_native
        recorder = NativeRecorder.start(root_dir=tmp_path, participant_id="00000001", paradigm="SSVEP",
                                        paradigm_code="SSVEP-20261031", unique_name="TEST-20261031",
                                        preset="native-layout-test", metadata=source.metadata,
                                        config={"experiment_metadata": {"full_name": "SDK offline fixture",
                                                "unique_name": "TEST-20261031", "description": "Synthetic parser proof"}})
        recorder.submit(chunk)
        recorder.submit(second)
        recorder.stop(status="completed", reason="offline native SDK proof")
        run, _, stored = read_native(recorder.session_dir)
        assert run["samples"] == 20
        np.testing.assert_allclose(stored, np.concatenate([expected, expected]))
        restored_ticks = np.fromfile(recorder.session_dir / "raw/brainco_device_timestamps.bin", dtype=np.float64)
        np.testing.assert_array_equal(restored_ticks, np.tile(ticks, 2))
    finally:
        sdk.clear_eeg_buffer()


@pytest.mark.parametrize("samples", [1, 10, 32, 33, 250])
@pytest.mark.parametrize("channels", [8, 32])
def test_sample_major_33_columns_never_transpose_or_shift(samples, channels):
    raw = np.arange(samples * 33, dtype=np.float64).reshape(samples, 33)
    raw[:, 0] = 1e9
    backend = BrainCoAcquirer(n_channels=channels)
    eeg, ticks = backend._split_buffer(raw)
    assert eeg.shape == (channels, samples)
    np.testing.assert_array_equal(eeg, raw[:, 1:1 + channels].T)
    np.testing.assert_array_equal(ticks, raw[:, 0])


def test_sdk_version_routes_production_to_verified_startup(monkeypatch):
    backend = BrainCoAcquirer()
    backend._sdk = SimpleNamespace(__version__="2.1.2")
    verified, original = Mock(), Mock()
    monkeypatch.setattr(backend, "_start_stream_verified", verified)
    monkeypatch.setattr(backend, "_start_stream_sdk", original)
    backend._start_stream_unified("parser")
    verified.assert_called_once_with("parser")
    original.assert_not_called()


@pytest.mark.parametrize("raw", [np.zeros((10, 34)), np.full((10, 33), np.nan)])
def test_invalid_layout_or_values_fail_without_guessing(raw):
    with pytest.raises(RuntimeError):
        BrainCoAcquirer()._split_buffer(raw)
