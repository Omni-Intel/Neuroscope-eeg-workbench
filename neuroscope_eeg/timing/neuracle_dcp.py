from __future__ import annotations

import importlib
import time
from typing import Any

from neuroscope_eeg.timing.models import HardwareWrite


DCP_IDENTITY_QUERY = bytes.fromhex("01 04 00 00")
_IDENTITY_TEXT = b"TriggerBox.Titing"


class TriggerBoxError(RuntimeError):
    pass


def encode_immediate_event(code: int) -> bytes:
    code = int(code)
    if not 0 <= code <= 255:
        raise ValueError("NDE0001 Trigger code must be between 0 and 255")
    return bytes((0x01, 0xE1, 0x01, 0x00, code))


class NDE0001Transport:
    def __init__(
        self,
        port: str,
        *,
        serial_module: Any = None,
        write_timeout_sec: float = 0.1,
        response_timeout_sec: float = 0.5,
    ) -> None:
        self.port = str(port).strip()
        self._serial_module = serial_module
        self.write_timeout_sec = float(write_timeout_sec)
        self.response_timeout_sec = float(response_timeout_sec)
        self._serial: Any = None
        self.identity = ""

    def open(self) -> str:
        if not self.port:
            raise TriggerBoxError("NDE0001 串口不能为空")
        module = self._serial_module or importlib.import_module("serial")
        try:
            self._serial = module.Serial(
                port=self.port,
                baudrate=115200,
                bytesize=module.EIGHTBITS,
                parity=module.PARITY_NONE,
                stopbits=module.STOPBITS_ONE,
                timeout=0,
                write_timeout=self.write_timeout_sec,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False,
            )
            self._write_exact(DCP_IDENTITY_QUERY)
            reply = self._read_identity_reply()
            if _IDENTITY_TEXT not in reply:
                raise TriggerBoxError("NDE0001 自描述回复不包含 TriggerBox.Titing")
            self.identity = _IDENTITY_TEXT.decode("ascii")
            return self.identity
        except TriggerBoxError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            raise TriggerBoxError(f"无法打开或识别 NDE0001 串口 {self.port}: {exc}") from exc

    def _write_exact(self, payload: bytes) -> None:
        if self._serial is None or not bool(getattr(self._serial, "is_open", True)):
            raise TriggerBoxError("NDE0001 串口尚未打开")
        written = int(self._serial.write(payload))
        if written != len(payload):
            raise TriggerBoxError(f"NDE0001 DCP 写入不完整：期望 {len(payload)} 字节，实际 {written} 字节")
        self._serial.flush()

    def _read_identity_reply(self) -> bytes:
        deadline = time.monotonic() + self.response_timeout_sec
        result = bytearray()
        expected_size: int | None = None
        while time.monotonic() < deadline:
            waiting = int(getattr(self._serial, "in_waiting", 0))
            if waiting:
                result.extend(self._serial.read(waiting))
                if len(result) >= 4 and expected_size is None:
                    expected_size = 4 + int.from_bytes(result[2:4], "little")
                if expected_size is not None and len(result) >= expected_size:
                    break
            else:
                time.sleep(0.001)
        return bytes(result)

    def send(self, code: int) -> HardwareWrite:
        frame = encode_immediate_event(code)
        requested_at = time.monotonic()
        self._write_exact(frame)
        completed_at = time.monotonic()
        return HardwareWrite(int(code), frame.hex(" "), requested_at, completed_at)

    def close(self) -> None:
        serial = self._serial
        self._serial = None
        if serial is not None and bool(getattr(serial, "is_open", True)):
            serial.close()
        self.identity = ""
