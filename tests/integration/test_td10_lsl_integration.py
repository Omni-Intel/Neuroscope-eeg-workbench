from __future__ import annotations

import time
import uuid

import numpy as np
import pytest

from neuroscope_eeg.acquisition.td10_lsl import TD10LSLSource


def _pylsl_or_skip():
    try:
        import pylsl
    except (ImportError, RuntimeError, OSError) as exc:
        pytest.skip(f"pylsl/liblsl unavailable: {exc}")
    return pylsl


def test_td10_three_stream_loopback() -> None:
    pylsl = _pylsl_or_skip()
    base = f"ifet-td10-test-{uuid.uuid4().hex}"
    outlets = []
    for suffix, stream_type, channels, rate, channel_format in (
        ("eeg", "EEG", 4, 125.0, pylsl.cf_int32),
        ("quality", "Quality", 3, 125.0, pylsl.cf_int32),
        ("markers", "Markers", 1, 0.0, pylsl.cf_string),
    ):
        info = pylsl.StreamInfo(
            f"TD10 test {suffix}",
            stream_type,
            channels,
            rate,
            channel_format,
            f"{base}:{suffix}",
        )
        outlets.append(pylsl.StreamOutlet(info))

    source = TD10LSLSource(base, resolve_timeout_sec=3.0, pull_timeout_sec=0.2)
    try:
        source.start()
        time.sleep(0.05)
        timestamp = pylsl.local_clock()
        outlets[0].push_sample([1, 2, 3, 4], timestamp=timestamp)
        outlets[1].push_sample([0, 255, 7], timestamp=timestamp)
        outlets[2].push_sample(["loopback"], timestamp=timestamp)
        deadline = time.monotonic() + 2.0
        chunk = source.read_chunk()
        while chunk.n_samples == 0 and time.monotonic() < deadline:
            chunk = source.read_chunk()
        assert chunk.n_samples == 1
        np.testing.assert_array_equal(chunk.data[:, 0], [1, 2, 3, 4])
        sidecars = source.drain_sidecars()
        assert sidecars.quality[0].values[0].tolist() == [0, 255, 7]
        assert sidecars.ifet_markers[0].value == "loopback"
    finally:
        source.stop()
