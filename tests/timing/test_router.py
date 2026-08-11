from __future__ import annotations

import json

from neuroscope_eeg.timing.codebook import definition_by_symbol
from neuroscope_eeg.timing.models import TriggerRequest
from neuroscope_eeg.timing.router import TriggerRouter


class FakeHardware:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[int] = []
        self.opened = False

    def open(self) -> str:
        self.opened = True
        return "TriggerBox.Titing"

    def send(self, code: int):
        from neuroscope_eeg.timing.models import HardwareWrite

        self.calls.append(code)
        if self.fail:
            raise RuntimeError("hardware down")
        return HardwareWrite(code, f"01 e1 01 00 {code:02x}", 10.0, 10.001)

    def close(self) -> None:
        self.opened = False


class FakeLSL:
    def __init__(self, order: list[str], *, fail: bool = False) -> None:
        self.order = order
        self.fail = fail
        self.payloads: list[dict] = []

    def open(self, session_id: str) -> None:
        self.session_id = session_id

    def push(self, payload: dict) -> float:
        self.order.append("lsl")
        self.payloads.append(json.loads(json.dumps(payload)))
        if self.fail:
            raise RuntimeError("lsl down")
        return 42.25

    def close(self) -> None:
        return None


def request() -> TriggerRequest:
    return TriggerRequest(
        paradigm="N-back 工作记忆",
        phase="nback_trial",
        label="7",
        payload={"nback_level": 1, "is_target": True, "block_index": 2, "trial_index": 17},
        wall_time=1_786_400_000.0,
        intent_time=9.9,
        onset_hook_time=10.0,
        hook_type="frame_swapped",
    )


def test_hardware_lsl_dispatches_hardware_first_and_mirrors_same_event() -> None:
    order: list[str] = []
    hardware = FakeHardware()
    original_send = hardware.send

    def ordered_send(code: int):
        order.append("hardware")
        return original_send(code)

    hardware.send = ordered_send  # type: ignore[method-assign]
    lsl = FakeLSL(order)
    router = TriggerRouter("hardware_lsl", hardware=hardware, lsl=lsl)
    router.open("session-1")
    dispatch = router.dispatch(request(), definition_by_symbol("NBACK_1_TARGET"))
    router.close()
    assert order == ["hardware", "lsl"]
    assert dispatch.sequence == 1
    assert dispatch.event_id == "EVT-000001"
    assert dispatch.hardware_code == 53
    assert dispatch.lsl_timestamp == 42.25
    assert dispatch.timing_status == "hardware_dispatched_unverified"
    assert lsl.payloads[0]["event_id"] == dispatch.event_id
    assert lsl.payloads[0]["hardware_code"] == 53
    assert lsl.payloads[0]["block"] == 2
    assert lsl.payloads[0]["trial"] == 17


def test_lsl_only_never_opens_or_calls_hardware() -> None:
    hardware = FakeHardware()
    lsl = FakeLSL([])
    router = TriggerRouter("lsl_only", hardware=hardware, lsl=lsl)
    router.open("session-2")
    dispatch = router.dispatch(request(), definition_by_symbol("NBACK_1_TARGET"))
    router.close()
    assert not hardware.calls
    assert dispatch.hardware_code == 53
    assert dispatch.hardware_requested is False
    assert dispatch.timing_status == "lsl_software_sync_uncalibrated"


def test_runtime_failures_are_explicit_and_do_not_hide_other_path() -> None:
    hardware = FakeHardware(fail=True)
    lsl = FakeLSL([])
    router = TriggerRouter("hardware_lsl", hardware=hardware, lsl=lsl)
    router.open("session-3")
    dispatch = router.dispatch(request(), definition_by_symbol("NBACK_1_TARGET"))
    assert dispatch.timing_status == "hardware_failed"
    assert dispatch.lsl_timestamp == 42.25
    assert "hardware down" in dispatch.hardware_error

    hardware = FakeHardware()
    lsl = FakeLSL([], fail=True)
    router = TriggerRouter("hardware_lsl", hardware=hardware, lsl=lsl)
    router.open("session-4")
    dispatch = router.dispatch(request(), definition_by_symbol("NBACK_1_TARGET"))
    assert dispatch.timing_status == "hardware_only_degraded"
    assert "lsl down" in dispatch.lsl_error
