from dataclasses import dataclass
from types import SimpleNamespace

import numpy as np
import pytest

from neuroscope_eeg.acquisition.devices import ExternalEmotivSource, NeuracleSource, OmniBCISource
from neuroscope_eeg.acquisition.vendor.collect.neuracle_api import RingBuffer
from neuroscope_eeg.timing.emotiv_serial import EmotivSerialTransport


def test_neuracle_preserves_aux_channel_and_actual_metadata(monkeypatch):
    class Server:
        channelNames = ("C3", "C4", "TRG")
        channelTypes = ("EEG", "EEG", "TRG")
        srates = (250, 250, 250)
        moduleName = "Fixture"
        def __init__(self, **kw):
            assert kw["enable_save_buffer"] is False
            self.buffer = SimpleNamespace(getUpdate=lambda: np.array([[1, 2, 3], [4, 5, 6], [0, 53, 0]]))
        def connect(self, **kw): return False
        def isReady(self): return True
        def start(self): pass
        def stop(self): pass
    monkeypatch.setattr("neuroscope_eeg.acquisition.vendor.collect.neuracle_api.DataServerThread", Server)
    source = NeuracleSource(sfreq=250, n_channels=2, profile={"channel_units": ["uV", "uV", "n/a"]})
    source.start()
    chunk = source.read_chunk()
    assert chunk.data.shape == (3, 3)
    assert source.metadata.channel_types == ("eeg", "eeg", "stim")
    assert source.drain_hardware_triggers()[0].sample_index == 1
    source.server.stream_error = "packet loss"
    with pytest.raises(RuntimeError, match="packet loss"):
        source.read_chunk()
    source.stop()


def test_ring_snapshot_is_owned_and_overflow_is_not_silent():
    buffer = RingBuffer(1, 4)
    buffer.appendBuffer(np.array([[1., 2.]]))
    chunk = buffer.getUpdate()
    buffer.appendBuffer(np.array([[3., 4., 5., 6.]]))
    np.testing.assert_array_equal(chunk, [[1., 2.]])
    buffer.appendBuffer(np.array([[7., 8.]]))
    with pytest.raises(RuntimeError, match="overflow"):
        buffer.getUpdate()


def test_exact_ring_capacity_after_wrap_returns_all_samples():
    buffer = RingBuffer(1, 4)
    buffer.appendBuffer(np.array([[1., 2.]]))
    buffer.getUpdate()
    buffer.appendBuffer(np.array([[3., 4., 5., 6.]]))
    np.testing.assert_array_equal(buffer.getUpdate(), [[3., 4., 5., 6.]])


def test_omni_preserves_raw_counts_indices_invalid_and_sdk_clocks():
    @dataclass
    class Config:
        verified: bool = True
        mode: str = "eeg"
    batch = SimpleNamespace(eeg_uv=np.arange(16).reshape(2, 8), raw_counts=np.arange(16).reshape(2, 8)*5,
              sequence=np.array([1, 3]), valid=np.array([True, False]), sample_indices=np.array([101, 103]),
              status=np.zeros((2, 3)), mode=np.ones(2), source_timestamp_us=np.array([4000, 12000]),
              source_timestamp_valid=np.ones(2, dtype=bool), generation=2, received_at=500., sample_rate_hz=250)
    class Board:
        @classmethod
        def connect(cls, *a, **kw): return cls()
        def get_config(self): return Config()
        def start(self): pass
        def read(self, **kw): return batch
        def read_triggers(self): return ()
        def stop(self): pass
        def close(self): pass
    sdk = SimpleNamespace(Board=Board, __version__="fixture", SDK_REVISION="fixture", OmniBCIError=RuntimeError,
                          DeviceTimeoutError=TimeoutError)
    source = OmniBCISource("serial://fixture", sdk=sdk)
    source.start()
    chunk = source.read_chunk()
    np.testing.assert_array_equal(chunk.data, batch.eeg_uv.T)
    np.testing.assert_array_equal(chunk.auxiliaries["raw_counts"], batch.raw_counts)
    np.testing.assert_array_equal(chunk.sample_indices, [101, 103])
    np.testing.assert_array_equal(chunk.valid, [True, False])
    assert chunk.received_at == 500.
    with pytest.raises(RuntimeError, match="丢样"):
        source.read_chunk()
    source.stop()


def test_external_emotiv_has_no_fictional_eeg():
    source = ExternalEmotivSource()
    source.start()
    assert source.metadata.n_channels == 0
    assert source.read_chunk().data.shape == (0, 0)


def test_omni_consumed_partial_batch_reaches_writer_before_error():
    batch = SimpleNamespace(eeg_uv=np.ones((1, 8)), raw_counts=np.full((1, 8), 8),
             sequence=np.array([1]), valid=np.array([True]), sample_indices=np.array([1]),
             status=np.zeros((1, 3)), mode=np.ones(1), source_timestamp_us=np.array([4000]),
             source_timestamp_valid=np.array([True]), generation=1, received_at=10., sample_rate_hz=250)
    class PartialError(RuntimeError):
        partial = batch
    def read(**kwargs):
        raise PartialError("timeout with consumed samples")
    source = OmniBCISource("serial://fixture", sdk=SimpleNamespace(OmniBCIError=RuntimeError, DeviceTimeoutError=TimeoutError))
    source.board = SimpleNamespace(read=read, read_triggers=lambda: ())
    assert source.read_chunk().n_samples == 1
    with pytest.raises(RuntimeError, match="consumed samples"):
        source.read_chunk()


def test_emotiv_serial_protocol_and_sticky_failure():
    class Port:
        is_open, in_waiting = True, 0
        def __init__(self, **kwargs):
            assert kwargs["baudrate"] == 115200
            self.payload = None
        def write(self, payload):
            self.payload = payload
            return len(payload)
        def flush(self): pass
        def close(self): pass
    with pytest.raises(ValueError):
        EmotivSerialTransport("COM5", "com5")
    transport = EmotivSerialTransport("COM5", "COM6", Port)
    transport.open()
    write = transport.send(120)
    assert transport._serial.payload == b"\x78"
    assert write.frame_hex == "78"
    transport._serial.is_open = False
    with pytest.raises(RuntimeError):
        transport.send(121)
    transport._serial.is_open = True
    with pytest.raises(RuntimeError):
        transport.send(121)
