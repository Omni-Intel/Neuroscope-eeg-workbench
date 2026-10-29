"""EmotivPRO paired serial marker protocol from visual-video-task-master.

One byte, 115200 8N1, no acknowledgement: successful write is NOT receipt.
"""
import time

from neuroscope_eeg.timing.models import HardwareWrite


class EmotivSerialTransport:
    def __init__(self, port, receiving_port, serial_factory=None):
        self.port = port.strip()
        self.receiving_port = receiving_port.strip()
        if not self.port or not self.receiving_port or self.port.casefold() == self.receiving_port.casefold():
            raise ValueError("需填写不同的配对串口：本程序发送口与 EmotivPRO 接收口")
        self._factory, self._serial = serial_factory, None
        self._failure = None

    def open(self):
        if self._factory is None:
            import serial
            self._factory = serial.Serial
        self._serial = self._factory(port=self.port, baudrate=115200, bytesize=8, parity="N", stopbits=1,
                                     timeout=.1, write_timeout=.5, xonxoff=False, rtscts=False, dsrdtr=False)

    def send(self, code):
        if not isinstance(code, int) or not 1 <= code <= 255:
            raise ValueError("EmotivPRO marker code must be 1..255")
        if self._failure:
            raise RuntimeError(self._failure)
        requested = time.monotonic()
        frame = bytes([code])
        try:
            if self._serial is None or not self._serial.is_open:
                raise RuntimeError("Marker 串口尚未打开")
            _ = self._serial.in_waiting  # surface detached driver errors
            if self._serial.write(frame) != len(frame):
                raise RuntimeError("Marker 串口未完整写入")
            self._serial.flush()
        except Exception as exc:
            self._failure = str(exc)
            raise
        return HardwareWrite(code, frame.hex(), requested, time.monotonic())

    def close(self):
        serial, self._serial = self._serial, None
        if serial is not None:
            serial.close()


class OmniTriggerTransport:
    def __init__(self, port):
        self.port = port
        self.controller = None

    def open(self):
        from omnibci import TriggerController
        self.controller = TriggerController.connect(self.port)

    def send(self, code):
        requested = time.monotonic()
        self.controller.send(code)
        return HardwareWrite(code, bytes([0xA5, code, code ^ 0xFF]).hex(), requested, time.monotonic())

    def close(self):
        controller, self.controller = self.controller, None
        if controller is not None:
            controller.close()
