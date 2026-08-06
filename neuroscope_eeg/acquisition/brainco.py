"""BrainCo BCIGo 32-channel EEG acquisition through ``bcigo-sdk`` 1.0.2."""

from __future__ import annotations

import asyncio
import importlib
import inspect
import re
import threading
import time
from collections.abc import Sequence
from typing import Any

import numpy as np


_SAMPLE_RATE_TO_ENUM = {250: "SR_250Hz", 500: "SR_500Hz", 1000: "SR_1000Hz", 2000: "SR_2000Hz"}
_GAIN_TO_ENUM = {1: "GAIN_1", 2: "GAIN_2", 4: "GAIN_4", 6: "GAIN_6", 8: "GAIN_8", 12: "GAIN_12", 24: "GAIN_24"}


class BrainCoAcquirer:
    """Small synchronous facade for BCIGo's asynchronous TCP client."""

    def __init__(
        self,
        sfreq: float = 250.0,
        n_channels: int = 32,
        buffer_sec: float = 30.0,
        brainco_addr: str = "",
        brainco_port: int = 0,
        auto_discover: bool = True,
        scan_timeout_sec: float = 6.0,
        ready_timeout_sec: float = 20.0,
        start_retries: int = 2,
        eeg_gain: int = 6,
        signal_source: str = "NORMAL",
        device_id: str = "bcigo",
    ) -> None:
        if not 1 <= int(n_channels) <= 32:
            raise ValueError("BrainCo BCIGo supports 1-32 EEG channels.")
        if int(sfreq) not in _SAMPLE_RATE_TO_ENUM:
            raise ValueError("Unsupported BrainCo sample rate. Allowed: 250, 500, 1000, 2000")
        if int(eeg_gain) not in _GAIN_TO_ENUM:
            raise ValueError("Unsupported BrainCo gain. Allowed: 1, 2, 4, 6, 8, 12, 24")

        self.sfreq = float(sfreq)
        self.n_channels = int(n_channels)
        self.buffer_sec = float(buffer_sec)
        self.brainco_addr = brainco_addr.strip()
        self.brainco_port = int(brainco_port)
        self.auto_discover = bool(auto_discover)
        self.scan_timeout_sec = float(scan_timeout_sec)
        self.ready_timeout_sec = float(ready_timeout_sec)
        self.start_retries = max(int(start_retries), 1)
        self.eeg_gain = int(eeg_gain)
        self.signal_source = signal_source.strip().upper() or "NORMAL"
        self.device_id = device_id.strip() or "bcigo"

        self._sdk: Any = None
        self._client: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._first_sample = threading.Event()
        self._impedance_event = threading.Event()
        self._impedance_payloads: list[tuple[Any, ...]] = []
        self._impedance_lock = threading.Lock()
        self._cached_target: tuple[str, int] | None = None

    def start_stream(self) -> None:
        if self._client is not None:
            self.stop_stream()
        self._sdk = self._load_sdk()
        self._start_loop_thread()

        last_error: Exception | None = None
        for attempt in range(self.start_retries):
            try:
                addr, port = self._resolve_target()
                self._client = self._sdk.BCIGoClient(addr, port)
                self._register_callbacks()
                self._configure_sdk_buffer()
                parser = self._sdk.MessageParser(self.device_id, self._sdk.MsgType.BCIGo)
                self._run_sdk_call(
                    self._client.start_stream,
                    parser,
                    fs=self._enum_value(self._sdk.EegSampleRate, _SAMPLE_RATE_TO_ENUM[int(self.sfreq)]),
                    gain=self._enum_value(self._sdk.EegSignalGain, _GAIN_TO_ENUM[self.eeg_gain]),
                    signal=self._enum_value(self._sdk.EegSignalSource, self.signal_source),
                )
                self._wait_for_samples()
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                self._disconnect_client()
                if attempt + 1 < self.start_retries:
                    time.sleep(0.5)

        self.stop_stream()
        assert last_error is not None
        raise RuntimeError(f"Unable to start BrainCo BCIGo stream: {last_error}") from last_error

    def stop_stream(self) -> None:
        self._disconnect_client()
        if self._sdk is not None:
            self._clear_callbacks()
            clear_buffer = getattr(self._sdk, "clear_eeg_buffer", None)
            if clear_buffer is not None:
                try:
                    clear_buffer()
                except Exception:
                    pass
        self._sdk = None
        self._first_sample.clear()
        self._impedance_event.clear()
        self._impedance_payloads.clear()
        self._stop_loop_thread()

    def get_new_samples(self) -> tuple[np.ndarray, np.ndarray]:
        if self._client is None or self._sdk is None:
            raise RuntimeError("BrainCo stream is not started")
        data = self._drain_eeg_buffer()
        timestamps = np.arange(data.shape[1], dtype=np.float64) / self.sfreq
        return data, timestamps

    def supports_impedance_check(self) -> bool:
        sdk = self._sdk
        if sdk is None:
            try:
                sdk = self._load_sdk()
            except RuntimeError:
                return False
        client_type = getattr(sdk, "BCIGoClient", None)
        return bool(
            client_type is not None
            and hasattr(sdk, "set_imp_data_callback")
            and hasattr(client_type, "enable_impedance_detection_mode")
            and hasattr(client_type, "disable_impedance_detection_mode")
        )

    def check_impedance(self, timeout_sec: float = 10.0) -> list[tuple[Any, ...]]:
        """Collect raw SDK impedance callbacks and restore normal EEG streaming.

        The SDK does not publish the callback payload schema, so callers receive raw
        payloads instead of inferred resistance units or contact-quality labels.
        """

        if not self.supports_impedance_check():
            raise RuntimeError("bcigo-sdk 1.0.2 does not expose the required impedance API.")
        was_streaming = self._client is not None
        if not was_streaming:
            self.start_stream()
        assert self._client is not None
        with self._impedance_lock:
            self._impedance_payloads.clear()
            self._impedance_event.clear()
            try:
                self._run_sdk_call(self._client.enable_impedance_detection_mode)
                self._impedance_event.wait(timeout=max(float(timeout_sec), 0.5))
                payloads = list(self._impedance_payloads)
            finally:
                self._run_sdk_call(self._client.disable_impedance_detection_mode)
        if not was_streaming:
            self.stop_stream()
        return payloads

    def _load_sdk(self) -> Any:
        try:
            return importlib.import_module("bcigo_sdk")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "BrainCo requires bcigo-sdk==1.0.2. Install with: python -m pip install -r requirements-brainco.txt"
            ) from exc

    def _resolve_target(self) -> tuple[str, int]:
        if self.brainco_addr and self.brainco_port > 0:
            return self.brainco_addr, self.brainco_port
        if self._cached_target is not None:
            return self._cached_target
        if not self.auto_discover:
            raise RuntimeError("BrainCo address/port missing and automatic discovery is disabled.")
        assert self._sdk is not None
        target = self._discover_target()
        self._cached_target = target
        return target

    def _discover_target(self) -> tuple[str, int]:
        assert self._sdk is not None
        scan = getattr(self._sdk, "mdns_start_scan", None)
        if scan is not None:
            result = self._run_sdk_call(scan, timeout=self.scan_timeout_sec)
            self._stop_mdns_scan()
            target = self._first_target(result)
            if target is not None:
                return target
        scan_multi = getattr(self._sdk, "mdns_start_scan_multi", None)
        if scan_multi is not None:
            found: list[tuple[str, int]] = []
            event = threading.Event()
            task: Any = None

            def on_device(device: Any) -> None:
                target = self._target_from_device(device)
                if target is not None:
                    found.append(target)
                    event.set()

            operation = scan_multi(on_device)
            if inspect.isawaitable(operation):
                assert self._loop is not None

                async def keep_scan_running() -> None:
                    await operation

                task = asyncio.run_coroutine_threadsafe(keep_scan_running(), self._loop)
            event.wait(self.scan_timeout_sec)
            self._stop_mdns_scan()
            if task is not None and not task.done():
                task.cancel()
            if found:
                return found[0]
        raise RuntimeError("BrainCo automatic discovery found no usable address and port.")

    def _stop_mdns_scan(self) -> None:
        assert self._sdk is not None
        stop = getattr(self._sdk, "mdns_stop_scan", None)
        if stop is not None:
            try:
                self._run_sdk_call(stop, timeout=self.scan_timeout_sec)
            except Exception:
                pass

    def _first_target(self, result: Any) -> tuple[str, int] | None:
        if isinstance(result, Sequence) and not isinstance(result, (str, bytes, bytearray)):
            values = result
        else:
            values = [result]
        for value in values:
            target = self._target_from_device(value)
            if target is not None:
                return target
        return None

    def _target_from_device(self, device: Any) -> tuple[str, int] | None:
        if isinstance(device, dict):
            addr = device.get("addr") or device.get("address") or device.get("host") or device.get("hostname")
            port = device.get("port")
        elif isinstance(device, Sequence) and not isinstance(device, (str, bytes, bytearray)):
            addr = device[0] if device else None
            port = device[1] if len(device) > 1 else None
        else:
            addr = (
                getattr(device, "addr", None)
                or getattr(device, "address", None)
                or getattr(device, "hostname", None)
            )
            port = getattr(device, "port", None)
        if isinstance(device, (str, bytes, bytearray)):
            text = device.decode() if isinstance(device, (bytes, bytearray)) else device
            match = re.fullmatch(r"(?:\[(.+)\]|([^:]+)):(\d+)", text.strip())
            if match is not None:
                addr, port = match.group(1) or match.group(2), match.group(3)
        try:
            port_value = int(port)
        except (TypeError, ValueError):
            port_value = 0
        if addr and port_value > 0:
            return str(addr).strip(), port_value
        return None

    def _configure_sdk_buffer(self) -> None:
        assert self._sdk is not None
        set_cfg = getattr(self._sdk, "set_cfg", None)
        if set_cfg is not None:
            take = max(int(self.sfreq * min(self.buffer_sec, 60.0)), 1024)
            set_cfg(take, max(256, int(self.sfreq)), 256)
        clear_buffer = getattr(self._sdk, "clear_eeg_buffer", None)
        if clear_buffer is not None:
            clear_buffer()

    def _register_callbacks(self) -> None:
        assert self._sdk is not None
        for name, callback in (
            ("set_received_data_callback", self._on_received_data),
            ("set_imp_data_callback", self._on_impedance),
            ("set_connection_state_callback", self._on_connection_state),
        ):
            register = getattr(self._sdk, name, None)
            if register is not None:
                register(callback)

    def _clear_callbacks(self) -> None:
        assert self._sdk is not None
        for name in ("set_received_data_callback", "set_imp_data_callback", "set_connection_state_callback"):
            register = getattr(self._sdk, name, None)
            if register is not None:
                try:
                    register(None)
                except Exception:
                    pass

    def _on_received_data(self, *_args: Any) -> None:
        self._first_sample.set()

    def _on_impedance(self, *args: Any) -> None:
        self._impedance_payloads.append(tuple(args))
        self._impedance_event.set()

    @staticmethod
    def _on_connection_state(*_args: Any) -> None:
        return

    def _wait_for_samples(self) -> None:
        deadline = time.monotonic() + self.ready_timeout_sec
        while time.monotonic() < deadline:
            if self._drain_eeg_buffer().shape[1] > 0:
                return
            self._first_sample.wait(timeout=0.1)
            self._first_sample.clear()
        raise RuntimeError("Timed out waiting for BrainCo EEG samples after BCIGo startup.")

    def _drain_eeg_buffer(self) -> np.ndarray:
        assert self._sdk is not None
        get_buffer = getattr(self._sdk, "get_eeg_buffer", None)
        if get_buffer is None:
            raise RuntimeError("bcigo-sdk 1.0.2 does not expose get_eeg_buffer().")
        take = max(int(self.sfreq * min(self.buffer_sec, 60.0)), 256)
        return self._normalize_buffer(get_buffer(take, True))

    def _normalize_buffer(self, raw: Any) -> np.ndarray:
        array = np.asarray([] if raw is None else raw, dtype=np.float32)
        if array.size == 0:
            return np.empty((self.n_channels, 0), dtype=np.float32)
        if array.ndim == 1:
            if array.size % self.n_channels:
                raise RuntimeError(f"Unexpected BrainCo buffer size {array.size} for {self.n_channels} channels.")
            array = array.reshape(-1, self.n_channels)
        if array.ndim != 2:
            raise RuntimeError(f"Unexpected BrainCo buffer shape: {array.shape}")
        if array.shape[0] == self.n_channels:
            return array
        if array.shape[1] == self.n_channels:
            return array.T
        if array.shape[0] > self.n_channels:
            return array[: self.n_channels]
        if array.shape[1] > self.n_channels:
            return array[:, : self.n_channels].T
        raise RuntimeError(f"Unexpected BrainCo channel layout: {array.shape}")

    def _disconnect_client(self) -> None:
        client, self._client = self._client, None
        if client is None:
            return
        disconnect_blocking = getattr(client, "disconnect_tcp_blocking", None)
        if disconnect_blocking is not None:
            try:
                disconnect_blocking()
                return
            except Exception:
                pass
        disconnect = getattr(client, "disconnect_tcp", None)
        if disconnect is not None:
            try:
                self._run_sdk_call(disconnect)
            except Exception:
                pass

    @staticmethod
    def _enum_value(enum_type: Any, name: str) -> Any:
        try:
            return getattr(enum_type, name)
        except AttributeError as exc:
            raise RuntimeError(f"bcigo-sdk 1.0.2 does not provide {enum_type.__name__}.{name}.") from exc

    def _run_sdk_call(self, method, *args: Any, timeout: float | None = None, **kwargs: Any) -> Any:
        result = method(*args, **kwargs)
        if not inspect.isawaitable(result):
            return result
        assert self._loop is not None

        async def await_result() -> Any:
            return await result

        future = asyncio.run_coroutine_threadsafe(await_result(), self._loop)
        return future.result(timeout=timeout or self.ready_timeout_sec)

    def _start_loop_thread(self) -> None:
        if self._loop is not None:
            return
        ready = threading.Event()

        def runner() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop
            ready.set()
            loop.run_forever()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.close()

        self._loop_thread = threading.Thread(target=runner, name="bcigo-sdk-loop", daemon=True)
        self._loop_thread.start()
        if not ready.wait(timeout=2.0):
            raise RuntimeError("Failed to start BCIGo asyncio loop.")

    def _stop_loop_thread(self) -> None:
        loop, thread = self._loop, self._loop_thread
        self._loop = None
        self._loop_thread = None
        if loop is not None:
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
