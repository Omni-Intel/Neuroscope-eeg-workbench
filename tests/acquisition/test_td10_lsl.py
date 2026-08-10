from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

from neuroscope_eeg.acquisition.td10_lsl import (
    TD10LSLSource,
    discover_td10_devices,
    eeg_source_id,
)


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

    def time_correction(self, timeout: float = 0.0) -> float:
        del timeout
        return {"EEG": 0.125, "Quality": 0.25, "Markers": 0.375}[self.info.type()]

    def pull_chunk(self, *, timeout: float, max_samples: int):
        if not self.chunks:
            return [], []
        return self.chunks.pop(0)


class FakeOutlet:
    instances: list["FakeOutlet"] = []

    def __init__(self, info) -> None:
        self.info = info
        self.samples: list[tuple[list[str], float]] = []
        self.instances.append(self)

    def push_sample(self, sample: list[str], *, timestamp: float) -> None:
        self.samples.append((sample, timestamp))


def fake_pylsl(info: FakeInfo, monkeypatch, *, companions: bool = False) -> SimpleNamespace:
    FakeInlet.instances.clear()
    FakeInlet.chunks = []
    resolve_calls: list[tuple[object, ...]] = []

    def resolve_byprop(prop, value, *, minimum, timeout):
        resolve_calls.append((prop, value, minimum, timeout))
        if value == info.source_id():
            return [info]
        if companions and value.endswith(":quality"):
            return [
                FakeInfo(
                    source_id=value,
                    sfreq=info.nominal_srate(),
                    channels=3,
                    stream_type="Quality",
                )
            ]
        if companions and value.endswith(":markers"):
            return [
                FakeInfo(
                    source_id=value,
                    sfreq=0.0,
                    channels=1,
                    channel_format=3,
                    stream_type="Markers",
                )
            ]
        return []

    sdk = SimpleNamespace(
        cf_int32=4,
        cf_string=3,
        resolve_byprop=resolve_byprop,
        StreamInlet=FakeInlet,
        StreamInfo=lambda *args: args,
        StreamOutlet=FakeOutlet,
        local_clock=lambda: 42.25,
        resolve_calls=resolve_calls,
    )
    monkeypatch.setitem(sys.modules, "pylsl", sdk)
    return sdk


def test_td10_resolves_exact_source_id_and_uses_stream_metadata(monkeypatch) -> None:
    sdk = fake_pylsl(FakeInfo(source_id="ifet-td10-subject-001:eeg", sfreq=500.0), monkeypatch)
    source = TD10LSLSource("ifet-td10-subject-001", resolve_timeout_sec=7.0)

    source.start()

    assert sdk.resolve_calls == [
        ("source_id", "ifet-td10-subject-001:eeg", 1, 7.0),
        ("source_id", "ifet-td10-subject-001:quality", 1, 7.0),
        ("source_id", "ifet-td10-subject-001:markers", 1, 7.0),
    ]
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
    np.testing.assert_array_equal(chunk.timestamps, [101.375, 101.379])
    assert chunk.sequence == 0

    empty = source.read_chunk()
    assert empty.data.shape == (4, 0)
    assert empty.timestamps.shape == (0,)
    assert empty.sequence == 2

    sidecars = source.drain_sidecars()
    np.testing.assert_array_equal(sidecars.eeg_timing[0].raw_timestamps, [101.25, 101.254])
    np.testing.assert_array_equal(sidecars.eeg_timing[0].corrected_timestamps, chunk.timestamps)
    assert sidecars.eeg_timing[0].time_correction == 0.125
    assert source.drain_sidecars().is_empty


def test_td10_receives_quality_and_markers_without_dropping_invalid_rows(monkeypatch) -> None:
    fake_pylsl(FakeInfo(), monkeypatch, companions=True)
    source = TD10LSLSource()
    source.start()
    eeg_inlet, quality_inlet, marker_inlet = FakeInlet.instances
    eeg_inlet.chunks = [([[1, 2, 3, 4], [5, 6, 7, 8]], [10.0, 10.004])]
    quality_inlet.chunks = [([[1, 255, 7], [0, 0, 9]], [20.0, 20.004])]
    marker_inlet.chunks = [([['{"event":"blink"}'], ["raw-marker"]], [30.0, 31.0])]

    source.read_chunk()
    sidecars = source.drain_sidecars()

    assert source.companions_ready
    np.testing.assert_array_equal(sidecars.quality[0].values, [[1, 255, 7], [0, 0, 9]])
    np.testing.assert_array_equal(sidecars.quality[0].raw_timestamps, [20.0, 20.004])
    np.testing.assert_array_equal(sidecars.quality[0].corrected_timestamps, [20.25, 20.254])
    assert [item.value for item in sidecars.ifet_markers] == ['{"event":"blink"}', "raw-marker"]
    assert [item.corrected_timestamp for item in sidecars.ifet_markers] == [30.375, 31.375]
    assert source.timing_stats["quality_invalid_samples"] == 1
    assert source.timing_stats["device_seq_wraps"] == 1


def test_td10_missing_companions_allows_preview_but_reports_not_ready(monkeypatch) -> None:
    fake_pylsl(FakeInfo(), monkeypatch)
    source = TD10LSLSource()

    source.start()

    assert not source.companions_ready
    assert source.missing_companion_streams == ("quality", "markers")


def test_td10_publishes_stable_neuroscope_marker_json_at_lsl_time(monkeypatch) -> None:
    fake_pylsl(FakeInfo(), monkeypatch, companions=True)
    FakeOutlet.instances.clear()
    source = TD10LSLSource()
    source.start()
    source.start_marker_outlet("session-1")

    marker = source.publish_marker({"phase": "stimulus", "trial": 2})

    assert marker.lsl_timestamp == 42.25
    assert FakeOutlet.instances[0].samples == [
        (["{\"phase\":\"stimulus\",\"trial\":2}"], 42.25)
    ]
    sidecars = source.drain_sidecars()
    assert sidecars.neuroscope_markers[0].lsl_timestamp == 42.25


@pytest.mark.parametrize(
    ("quality", "message"),
    [
        ([2, 1, 0], "Valid"),
        ([1, 256, 0], "DeviceSeq"),
    ],
)
def test_td10_rejects_invalid_quality_fields(monkeypatch, quality: list[int], message: str) -> None:
    fake_pylsl(FakeInfo(), monkeypatch, companions=True)
    source = TD10LSLSource()
    source.start()
    eeg_inlet, quality_inlet, _ = FakeInlet.instances
    eeg_inlet.chunks = [([[1, 2, 3, 4]], [10.0])]
    quality_inlet.chunks = [([quality], [10.0])]

    with pytest.raises(RuntimeError, match=message):
        source.read_chunk()


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
