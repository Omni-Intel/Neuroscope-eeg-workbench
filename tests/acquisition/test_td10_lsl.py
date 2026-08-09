from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from neuroscope_eeg.acquisition.td10_lsl import TD10LSLSource, discover_td10_devices, eeg_source_id


class FakeInfo:
    def __init__(
        self,
        *,
        source_id: str = "ifet-td10-headset:eeg",
        sfreq: float = 250.0,
        channels: int = 4,
        channel_format: int = 4,
        stream_type: str = "EEG",
    ) -> None:
        self._source_id = source_id
        self._sfreq = sfreq
        self._channels = channels
        self._channel_format = channel_format
        self._stream_type = stream_type

    def name(self) -> str:
        return "iFET-TD10_EEG"

    def type(self) -> str:
        return self._stream_type

    def source_id(self) -> str:
        return self._source_id

    def channel_count(self) -> int:
        return self._channels

    def nominal_srate(self) -> float:
        return self._sfreq

    def channel_format(self) -> int:
        return self._channel_format


class FakeInlet:
    instances: list["FakeInlet"] = []
    chunks: list[tuple[list[list[int]], list[float]]] = []

    def __init__(self, info, **kwargs) -> None:
        self.info = info
        self.kwargs = kwargs
        self.open_timeout: float | None = None
        self.closed = False
        FakeInlet.instances.append(self)

    def open_stream(self, timeout: float) -> None:
        self.open_timeout = timeout

    def close_stream(self) -> None:
        self.closed = True

    def pull_chunk(self, *, timeout: float, max_samples: int):
        if not self.chunks:
            return [], []
        return self.chunks.pop(0)


def fake_pylsl(info: FakeInfo, monkeypatch) -> SimpleNamespace:
    FakeInlet.instances.clear()
    FakeInlet.chunks = []
    resolve_calls: list[tuple[object, ...]] = []

    def resolve_byprop(prop, value, *, minimum, timeout):
        resolve_calls.append((prop, value, minimum, timeout))
        return [info]

    sdk = SimpleNamespace(
        cf_int32=4,
        resolve_byprop=resolve_byprop,
        StreamInlet=FakeInlet,
        resolve_calls=resolve_calls,
    )
    monkeypatch.setitem(sys.modules, "pylsl", sdk)
    return sdk


def test_td10_resolves_exact_source_id_and_uses_stream_metadata(monkeypatch) -> None:
    sdk = fake_pylsl(FakeInfo(source_id="ifet-td10-subject-001:eeg", sfreq=500.0), monkeypatch)
    source = TD10LSLSource("ifet-td10-subject-001", resolve_timeout_sec=7.0)

    source.start()

    assert sdk.resolve_calls == [("source_id", "ifet-td10-subject-001:eeg", 1, 7.0)]
    assert source.metadata.source_id == "ifet-td10-subject-001:eeg"
    assert source.metadata.source_type == "td10_lsl"
    assert source.metadata.sfreq == 500.0
    assert source.metadata.channel_names == ("EEG1", "EEG2", "EEG3", "EEG4")
    assert source.metadata.channel_units == ("ADC counts",) * 4
    assert FakeInlet.instances[0].kwargs["processing_flags"] == 0

    source.stop()
    assert FakeInlet.instances[0].closed


def test_td10_preserves_lsl_timestamps_and_transposes_sample_major_data(monkeypatch) -> None:
    fake_pylsl(FakeInfo(), monkeypatch)
    FakeInlet.chunks = [
        (
            [[0, 1, 2, 3], [8_388_607, -8_388_608, -1, 0]],
            [101.25, 101.254],
        )
    ]
    source = TD10LSLSource("ifet-td10-headset:eeg")
    source.start()

    chunk = source.read_chunk()

    np.testing.assert_array_equal(
        chunk.data,
        np.asarray([[0, 8_388_607], [1, -8_388_608], [2, -1], [3, 0]], dtype=np.float32),
    )
    np.testing.assert_array_equal(chunk.timestamps, [101.25, 101.254])
    assert chunk.sequence == 0

    empty = source.read_chunk()
    assert empty.data.shape == (4, 0)
    assert empty.timestamps.shape == (0,)
    assert empty.sequence == 2


@pytest.mark.parametrize(
    ("info", "message"),
    [
        (FakeInfo(channels=5), "必须为 4 通道"),
        (FakeInfo(sfreq=200.0), "标称采样率"),
        (FakeInfo(channel_format=1), "通道格式必须为 int32"),
        (FakeInfo(stream_type="AUX"), "type 必须为 EEG"),
    ],
)
def test_td10_rejects_streams_that_violate_the_protocol(monkeypatch, info: FakeInfo, message: str) -> None:
    fake_pylsl(info, monkeypatch)
    source = TD10LSLSource()

    with pytest.raises(RuntimeError, match=message):
        source.start()


def test_td10_requires_unique_source_id(monkeypatch) -> None:
    sdk = fake_pylsl(FakeInfo(), monkeypatch)
    sdk.resolve_byprop = lambda *_args, **_kwargs: [FakeInfo(), FakeInfo()]
    source = TD10LSLSource()

    with pytest.raises(RuntimeError, match="多个相同 source_id"):
        source.start()


def test_td10_normalizes_base_and_full_source_ids() -> None:
    assert eeg_source_id("") == "ifet-td10-headset:eeg"
    assert eeg_source_id("ifet-td10-subject-001") == "ifet-td10-subject-001:eeg"
    assert eeg_source_id("ifet-td10-subject-001:eeg") == "ifet-td10-subject-001:eeg"


def test_td10_discovery_lists_all_protocol_compatible_devices(monkeypatch) -> None:
    compatible_2 = FakeInfo(source_id="ifet-td10-subject-002:eeg", sfreq=500.0)
    compatible_1 = FakeInfo(source_id="ifet-td10-subject-001:eeg", sfreq=250.0)
    wrong_type = FakeInfo(source_id="ifet-td10-subject-001:aux", stream_type="AUX")
    wrong_channels = FakeInfo(source_id="other-device:eeg", channels=8)
    sdk = SimpleNamespace(
        cf_int32=4,
        resolve_streams=lambda *, wait_time: [compatible_2, wrong_type, wrong_channels, compatible_1],
    )
    monkeypatch.setitem(sys.modules, "pylsl", sdk)

    devices = discover_td10_devices(1.5)

    assert [device.base_source_id for device in devices] == [
        "ifet-td10-subject-001",
        "ifet-td10-subject-002",
    ]
    assert [device.sfreq for device in devices] == [250.0, 500.0]
