from __future__ import annotations

from types import SimpleNamespace

import pytest

from neuroscope_eeg.timing.neuracle_dcp import (
    DCP_IDENTITY_QUERY,
    NDE0001Transport,
    TriggerBoxError,
    encode_immediate_event,
)


class FakeSerial:
    def __init__(self, *, reply: bytes = b"\x01\x04\x11\x00TriggerBox.Titing", short_write: bool = False) -> None:
        self.reply = reply
        self.short_write = short_write
        self.writes: list[bytes] = []
        self.is_open = True
        self.closed = False

    def write(self, payload: bytes) -> int:
        self.writes.append(bytes(payload))
        return len(payload) - 1 if self.short_write else len(payload)

    def flush(self) -> None:
        return None

    def read(self, size: int) -> bytes:
        result, self.reply = self.reply[:size], self.reply[size:]
        return result

    @property
    def in_waiting(self) -> int:
        return len(self.reply)

    def close(self) -> None:
        self.closed = True
        self.is_open = False


def test_dcp_frames_are_byte_exact() -> None:
    assert DCP_IDENTITY_QUERY == bytes.fromhex("01 04 00 00")
    assert encode_immediate_event(1) == bytes.fromhex("01 E1 01 00 01")
    assert encode_immediate_event(127) == bytes.fromhex("01 E1 01 00 7F")
    assert encode_immediate_event(255) == bytes.fromhex("01 E1 01 00 FF")
    with pytest.raises(ValueError):
        encode_immediate_event(-1)
    with pytest.raises(ValueError):
        encode_immediate_event(256)


def test_transport_identifies_nde0001_and_sends_dcp_event() -> None:
    serial = FakeSerial()
    serial_module = SimpleNamespace(
        EIGHTBITS=8,
        STOPBITS_ONE=1,
        PARITY_NONE="N",
        Serial=lambda **_kwargs: serial,
    )
    transport = NDE0001Transport("COM7", serial_module=serial_module, response_timeout_sec=0.05)
    identity = transport.open()
    dispatch = transport.send(53)
    transport.close()
    assert identity == "TriggerBox.Titing"
    assert serial.writes == [DCP_IDENTITY_QUERY, bytes.fromhex("01 E1 01 00 35")]
    assert dispatch.code == 53
    assert dispatch.frame_hex == "01 e1 01 00 35"
    assert dispatch.write_completed_at >= dispatch.requested_at
    assert serial.closed


def test_transport_rejects_wrong_identity_and_short_write() -> None:
    wrong = FakeSerial(reply=b"\x01\x04\x03\x00bad")
    module = SimpleNamespace(
        EIGHTBITS=8,
        STOPBITS_ONE=1,
        PARITY_NONE="N",
        Serial=lambda **_kwargs: wrong,
    )
    with pytest.raises(TriggerBoxError, match="TriggerBox.Titing"):
        NDE0001Transport("COM7", serial_module=module, response_timeout_sec=0.02).open()

    short = FakeSerial(short_write=True)
    module.Serial = lambda **_kwargs: short
    with pytest.raises(TriggerBoxError, match="写入不完整"):
        NDE0001Transport("COM7", serial_module=module, response_timeout_sec=0.02).open()
