import asyncio
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from neuroscope_eeg.acquisition.vendor.brainco_acquirer import BrainCoAcquirer


def test_auto_ignores_hidden_manual_address_and_port():
    b = BrainCoAcquirer(brainco_addr="old", brainco_port=99, auto_discover=True)
    b._discover_device = Mock(return_value=("new", 100))
    assert b._resolve_addr_port() == ("new", 100)
    assert b._coerce_discovered_target({"addr": "new"}) is None
    b._auto_discover = False
    assert b._resolve_addr_port() == ("old", 99)
    b._discover_device.assert_called_once()


@pytest.mark.parametrize("method", ["quick", "multi", "single", "zeroconf"])
def test_discovery_order_and_stop_dependent_future(method):
    b = BrainCoAcquirer(scan_timeout_sec=.02)
    calls = []
    futures = []
    def initialize(): calls.append("init")
    def quick():
        calls.append("quick")
        return ("192.0.2.1", 9000) if method == "quick" else []
    def multi(callback):
        calls.append("multi")
        future = asyncio.get_running_loop().create_future()
        futures.append(future)
        if method == "multi":
            callback(SimpleNamespace(addr="192.0.2.1", port=9000))
        return future
    def single():
        calls.append("single")
        future = asyncio.get_running_loop().create_future()
        futures.append(future)
        return future
    def stop():
        calls.append("stop")
        for future in futures:
            if not future.done():
                future.set_result(("192.0.2.1", 9000) if method == "single" else None)
    async def zeroconf():
        calls.append("zeroconf")
        return ("192.0.2.1", 9000)
    b._sdk = SimpleNamespace(init_adapter=initialize, scan_devices=quick,
                             mdns_start_scan_multi=multi, mdns_start_scan=single, mdns_stop_scan=stop)
    b._discover_device_via_zeroconf_async = zeroconf
    assert asyncio.run(b._discover_device_async()) == ("192.0.2.1", 9000)
    assert calls[:2] == ["init", "quick"]
    if method == "multi": assert "single" not in calls
    if method == "single": assert "zeroconf" not in calls
    if method == "zeroconf": assert calls.index("multi") < calls.index("single") < calls.index("zeroconf")
    assert all(f.done() for f in futures)


def test_outer_timeout_covers_all_discovery_stages():
    b = BrainCoAcquirer(scan_timeout_sec=6)
    def run(coro, timeout):
        coro.close()
        assert timeout >= 3 * 6 + 14
        return ("target", 9000)
    b._run_coroutine = run
    assert b._discover_device() == ("target", 9000)


def test_sdk_constructor_runs_in_event_loop_and_failures_cleanup(monkeypatch):
    b = BrainCoAcquirer(brainco_addr="target", brainco_port=9000, auto_discover=False, start_retries=1)
    def constructor(*args):
        assert asyncio.get_running_loop() is b._loop
        raise RuntimeError("connection rejected")
    monkeypatch.setitem(sys.modules, "bcigo_sdk", SimpleNamespace(BCIGoClient=constructor))
    with pytest.raises(RuntimeError, match="connection rejected"):
        b.start_stream()
    assert b._loop is None
    assert b._client is None
