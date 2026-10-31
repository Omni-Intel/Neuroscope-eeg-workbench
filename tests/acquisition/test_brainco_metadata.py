from types import SimpleNamespace

import numpy as np
import pytest

from neuroscope_eeg.acquisition.devices import DemoSource
from neuroscope_eeg.acquisition.vendor.brainco_acquirer import BrainCoAcquirer


def backend():
    return SimpleNamespace(metadata=SimpleNamespace(sfreq=250, n_channels=2),
                           start_stream=lambda: None,
                           trigger_sync_status={"state": "unconfirmed", "error": "ack timeout"},
                           get_new_samples=lambda: (np.array([[1., -2.], [3., -4.]]), []),
                           pop_trigger_events=lambda: [])


def test_native_units_are_metadata_only_and_other_sources_keep_their_units(monkeypatch):
    monkeypatch.setattr("importlib.metadata.version", lambda _: "2.1.2")
    source = DemoSource(backend(), "brainco")
    source.start()
    assert source.metadata.channel_units == ("uV", "uV")
    assert source.metadata.channel_names == ("FP1", "FP2")
    assert source.metadata.extra["profile_confirmed"] is False
    np.testing.assert_array_equal(source.read_chunk().data, [[1, -2], [3, -4]])
    assert "未获确认" in source.trigger_status_text
    assert source.metadata.extra["brainco_trigger_sync"]["error"] == "ack timeout"
    lsl = backend()
    lsl.stream_identity = {"channels": 2}
    lsl._inlet = SimpleNamespace(time_correction=lambda **kw: 0)
    source = DemoSource(lsl, "lsl", {"channel_units": ["V", "V"]})
    source.start()
    assert source.metadata.channel_units == ("V", "V")


def test_conflicting_brainco_units_rejected_and_other_versions_not_guessed(monkeypatch):
    monkeypatch.setattr("importlib.metadata.version", lambda _: "2.1.2")
    with pytest.raises(ValueError, match="微伏"):
        DemoSource(backend(), "brainco", {"channel_units": ["V", "V"]}).start()
    monkeypatch.setattr("importlib.metadata.version", lambda _: "future")
    source = DemoSource(backend(), "brainco")
    source.start()
    assert source.metadata.channel_units == ("unknown", "unknown")
    assert source.metadata.channel_names == ("CH1", "CH2")


def test_brainco_mapping_preserves_sdk_order_and_profile_overrides(monkeypatch):
    monkeypatch.setattr("importlib.metadata.version", lambda _: "2.1.2")
    b = backend()
    b.metadata.n_channels = 32
    b.get_new_samples = lambda: (np.arange(64).reshape(32, 2), [])
    source = DemoSource(b, "brainco")
    source.start()
    assert source.metadata.channel_names[7:10] == ("C3", "C4", "Cz")
    assert source.metadata.channel_names[15:17] == ("O1", "O2")
    assert source.metadata.channel_names[-1] == "IO"
    assert source.metadata.channel_types == ("eeg",)*31 + ("misc",)
    assert source.metadata.extra["profile_confirmed"] is False
    np.testing.assert_array_equal(source.read_chunk().data, np.arange(64).reshape(32, 2))
    source = DemoSource(backend(), "brainco", {"channel_names": ["Cz", "REF"], "channel_types": ["eeg", "misc"]})
    source.start()
    assert source.metadata.channel_names == ("Cz", "REF")
    assert source.metadata.channel_types == ("eeg", "misc")


@pytest.mark.parametrize("reply,state", [(None, "acknowledged"), (True, "acknowledged"),
                                        (False, "rejected"), (TimeoutError("ack timeout"), "unconfirmed")])
def test_trigger_ack_failures_remain_visible_without_stopping_eeg(reply, state, monkeypatch):
    acquirer = BrainCoAcquirer()
    def request(enable):
        assert enable is True
        if isinstance(reply, Exception):
            raise reply
        return reply
    acquirer._client = SimpleNamespace(set_trigger_sync=request)
    monkeypatch.setattr(acquirer, "_run_sdk_call", lambda fn, *args: fn(*args))
    acquirer._enable_sdk_trigger_sync()
    assert acquirer.trigger_sync_status["state"] == state
    acquirer._enable_trigger_sync = False
    acquirer._enable_sdk_trigger_sync()
    assert acquirer.trigger_sync_status == {"state": "disabled", "error": ""}
    acquirer._enable_trigger_sync = True
    acquirer._client = object()
    acquirer._enable_sdk_trigger_sync()
    assert acquirer.trigger_sync_status["state"] == "unsupported"
