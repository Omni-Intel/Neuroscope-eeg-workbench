"""BrainCo EEG Cap acquisition backend backed by the bcigo_sdk package."""

from __future__ import annotations

import asyncio
import concurrent.futures
import json
import logging
import re
import threading
import time
from collections import deque
from collections.abc import Awaitable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from neuroscope_eeg.acquisition.vendor.base import AbstractAcquirer, AcquirerMetadata, EEGChunk

LOGGER = logging.getLogger(__name__)
_BRAINCO_MDNS_SERVICE = "_brainco-eeg._tcp.local."

_SAMPLE_RATE_TO_ENUM = {
    250: "SR_250Hz",
    500: "SR_500Hz",
    1000: "SR_1000Hz",
    2000: "SR_2000Hz",
}

_GAIN_TO_ENUM = {
    1: "GAIN_1",
    2: "GAIN_2",
    4: "GAIN_4",
    6: "GAIN_6",
    8: "GAIN_8",
    12: "GAIN_12",
    24: "GAIN_24",
}

_TRIGGER_EVENT_KEYS = ("triggerEvent", "trigger_event", "TriggerEvent")
_TRIGGER_EVENT_SEQ_KEYS = ("eventSeq", "event_seq")
_TRIGGER_SAMPLE_COUNTER_KEYS = ("sampleCounter", "sample_counter")


@dataclass(frozen=True, slots=True)
class BrainCoTriggerEvent:
    """A hardware trigger record delivered by the BrainCo TriggerBox."""

    event_seq: int
    sample_counter: int
    source_tick: int | None = None
    source_hz: float | None = None
    wifi_tick: int | None = None
    offset_tick: int | None = None
    round_trip_tick: int | None = None
    calibration_age_tick: int | None = None
    source_drops: int | None = None
    received_monotonic: float = 0.0


class BrainCoAcquirer(AbstractAcquirer):
    """Wrap BrainCo's async TCP SDK behind the unified acquirer API."""

    def __init__(
        self,
        sfreq: float = 250.0,
        n_channels: int = 32,
        buffer_sec: float = 60.0,
        brainco_addr: str = "",
        brainco_port: int = 0,
        auto_discover: bool = True,
        scan_timeout_sec: float = 6.0,
        ready_timeout_sec: float = 10.0,
        start_retries: int = 2,
        eeg_gain: int = 6,
        signal_source: str = "NORMAL",
        device_id: str = "bcigo",
        enable_trigger_sync: bool = True,
    ) -> None:
        if n_channels <= 0 or n_channels > 32:
            raise ValueError("BrainCo EEG Cap supports 1-32 EEG channels.")
        if int(sfreq) not in _SAMPLE_RATE_TO_ENUM:
            allowed = ", ".join(str(v) for v in sorted(_SAMPLE_RATE_TO_ENUM))
            raise ValueError(f"Unsupported BrainCo sample rate {sfreq}. Allowed: {allowed}")
        if eeg_gain not in _GAIN_TO_ENUM:
            allowed = ", ".join(str(v) for v in sorted(_GAIN_TO_ENUM))
            raise ValueError(f"Unsupported BrainCo gain {eeg_gain}. Allowed: {allowed}")

        self.metadata = AcquirerMetadata(name="brainco", sfreq=float(sfreq), n_channels=n_channels)
        self._buffer_sec = float(buffer_sec)
        self._brainco_addr = brainco_addr.strip()
        self._brainco_port = int(brainco_port)
        self._auto_discover = bool(auto_discover)
        self._scan_timeout_sec = float(scan_timeout_sec)
        self._ready_timeout_sec = float(ready_timeout_sec)
        self._start_retries = max(int(start_retries), 1)
        self._eeg_gain = int(eeg_gain)
        self._signal_source = signal_source.strip().upper() or "NORMAL"
        self._device_id = device_id
        self._enable_trigger_sync = bool(enable_trigger_sync)

        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._client: Any = None
        self._sdk: Any = None
        self._cache_lock = threading.Lock()
        self._first_sample_event = threading.Event()
        self._response_event = threading.Event()
        self._msg_resp_lock = threading.Lock()
        self._eeg_cache = np.empty((n_channels, 0), dtype=np.float32)
        self._cache_capacity = max(int(self.metadata.sfreq * self._buffer_sec), 1)
        self._cache_write_index = 0
        self._cache_valid_samples = 0
        self._pending_msg_responses: dict[int, deque[tuple[Any, ...]]] = {}
        self._generic_msg_responses: deque[tuple[Any, ...]] = deque()
        self._trigger_lock = threading.Lock()
        self._trigger_events: deque[BrainCoTriggerEvent] = deque()
        self._raw_packet_count = 0
        self._callback_sample_count = 0
        self._total_samples_seen = 0
        self._last_chunk_total_samples = 0
        self._last_raw_packet_monotonic = 0.0
        self._last_msg_response_monotonic = 0.0
        self._cached_discovery_target: tuple[str, int] | None = None

    def start_stream(self) -> None:
        import bcigo_sdk as sdk

        if self._client is not None:
            self.stop_stream()

        last_error: Exception | None = None

        for attempt in range(1, self._start_retries + 1):
            self._sdk = sdk
            self._first_sample_event.clear()
            self._response_event.clear()
            with self._cache_lock:
                self._eeg_cache = np.empty((self.metadata.n_channels, self._cache_capacity), dtype=np.float32)
                self._cache_write_index = 0
                self._cache_valid_samples = 0
            with self._msg_resp_lock:
                self._pending_msg_responses.clear()
                self._generic_msg_responses.clear()
            with self._trigger_lock:
                self._trigger_events.clear()
            self._raw_packet_count = 0
            self._callback_sample_count = 0
            self._total_samples_seen = 0
            self._last_chunk_total_samples = 0
            self._last_raw_packet_monotonic = 0.0
            self._last_msg_response_monotonic = 0.0
            self._start_loop_thread()
            try:
                addr, port = self._resolve_addr_port()
                self._client = self._run_sdk_call(sdk.BCIGoClient, addr, port)
                parser = sdk.MessageParser(self._device_id, sdk.MsgType.BCIGo)
                self._register_sdk_callbacks()
                if hasattr(self._client, "start_stream"):
                    self._start_stream_unified(parser)
                else:
                    self._start_stream_legacy(parser)
                self._enable_sdk_trigger_sync()
                break
            except Exception as exc:
                last_error = exc
                LOGGER.warning(
                    "BrainCo stream start attempt %s/%s failed: %s",
                    attempt,
                    self._start_retries,
                    exc,
                )
                self.stop_stream()
                if attempt >= self._start_retries:
                    raise
                time.sleep(0.5)
        else:
            if last_error is not None:
                raise last_error

        LOGGER.info(
            "BrainCo acquisition started at %s:%s sfreq=%.1fHz channels=%s",
            addr,
            port,
            self.metadata.sfreq,
            self.metadata.n_channels,
        )

    def _start_stream_unified(self, parser: Any) -> None:
        """Use the SDK's recommended one-key stream startup when available."""

        assert self._sdk is not None
        assert self._client is not None
        buffer_len = max(int(self.metadata.sfreq * min(self._buffer_sec, 60.0)), 1024)
        self._sdk.set_cfg(buffer_len, max(256, int(self.metadata.sfreq)), 256)
        self._sdk.clear_eeg_buffer()
        self._run_sdk_call(
            self._client.start_stream,
            parser,
            fs=getattr(self._sdk.EegSampleRate, _SAMPLE_RATE_TO_ENUM[int(self.metadata.sfreq)]),
            gain=getattr(self._sdk.EegSignalGain, _GAIN_TO_ENUM[self._eeg_gain]),
            signal=getattr(self._sdk.EegSignalSource, self._signal_source),
        )
        self._wait_for_samples()

    def _start_stream_legacy(self, parser: Any) -> None:
        assert self._sdk is not None
        assert self._client is not None
        self._run_sdk_call(self._client.start_data_stream, parser)
        buffer_len = max(int(self.metadata.sfreq * min(self._buffer_sec, 60.0)), 1024)
        self._sdk.set_cfg(buffer_len, max(256, int(self.metadata.sfreq)), 256)
        config_msg_id = self._run_sdk_call(
            self._client.set_eeg_config,
            getattr(self._sdk.EegSampleRate, _SAMPLE_RATE_TO_ENUM[int(self.metadata.sfreq)]),
            getattr(self._sdk.EegSignalGain, _GAIN_TO_ENUM[self._eeg_gain]),
            getattr(self._sdk.EegSignalSource, self._signal_source),
        )
        # Some BrainCo firmware/SDK combinations apply EEG config successfully
        # but never surface a matching msg response callback for this command.
        # Treat missing config acks like start_eeg_stream: warn and continue,
        # then rely on actual EEG sample arrival as the final success criterion.
        self._wait_for_command_response(config_msg_id, "set_eeg_config", allow_missing=True)
        self._sdk.clear_eeg_buffer()
        start_msg_id = self._run_sdk_call(self._client.start_eeg_stream)
        self._wait_for_command_response(start_msg_id, "start_eeg_stream", allow_missing=True)
        self._wait_for_samples()

    def _enable_sdk_trigger_sync(self) -> None:
        """Ask the device to stream TriggerBox records through the message callback.

        Trigger sync is optional: older firmware or SDK builds simply reject the
        command, which must not take down EEG acquisition.
        """

        if not self._enable_trigger_sync or self._client is None:
            return
        set_trigger_sync = getattr(self._client, "set_trigger_sync", None)
        if set_trigger_sync is None:
            LOGGER.warning(
                "bcigo_sdk %s does not expose set_trigger_sync; TriggerBox events are unavailable.",
                getattr(self._sdk, "__version__", "unknown"),
            )
            return
        try:
            result = self._run_sdk_call(set_trigger_sync, True)
        except Exception as exc:
            LOGGER.warning("BrainCo TriggerBox trigger sync could not be enabled: %s", exc)
            return
        LOGGER.info("BrainCo TriggerBox trigger sync enabled (SDK reply: %r)", result)

    def pop_trigger_events(self) -> list[BrainCoTriggerEvent]:
        """Return and clear hardware trigger records received since the last call."""

        with self._trigger_lock:
            events = list(self._trigger_events)
            self._trigger_events.clear()
        return events

    def stop_stream(self) -> None:
        sdk = self._sdk
        client = self._client
        self._client = None

        if client is not None:
            try:
                self._run_sdk_call(client.stop_eeg_stream)
            except Exception as exc:
                LOGGER.warning("Failed to stop BrainCo EEG stream cleanly: %s", exc)
            try:
                disconnect_tcp = getattr(client, "disconnect_tcp", None)
                if disconnect_tcp is not None:
                    self._run_sdk_call(disconnect_tcp)
                else:
                    client.disconnect_tcp_blocking()
            except Exception as exc:
                LOGGER.warning("Failed to disconnect BrainCo TCP client cleanly: %s", exc)

        if sdk is not None:
            try:
                sdk.clear_eeg_buffer()
            except Exception:
                pass
            self._clear_sdk_callbacks()

        self._stop_loop_thread()
        self._sdk = None
        self._first_sample_event.clear()
        self._response_event.clear()
        with self._cache_lock:
            self._eeg_cache = np.empty((self.metadata.n_channels, 0), dtype=np.float32)
        with self._msg_resp_lock:
            self._pending_msg_responses.clear()
            self._generic_msg_responses.clear()
        with self._trigger_lock:
            self._trigger_events.clear()
        self._raw_packet_count = 0
        self._callback_sample_count = 0
        self._total_samples_seen = 0
        self._last_chunk_total_samples = 0
        self._last_raw_packet_monotonic = 0.0
        self._last_msg_response_monotonic = 0.0
        LOGGER.info("BrainCo acquisition stopped")

    def get_chunk(self, window_sec: float) -> EEGChunk:
        if self._client is None or self._sdk is None:
            raise RuntimeError("BrainCo stream is not started")

        required = int(window_sec * self.metadata.sfreq)
        if required <= 0:
            raise RuntimeError("window_sec must yield at least one sample")

        deadline = time.monotonic() + max(window_sec, 0.1) + self._ready_timeout_sec
        # Keep pulling until we have enough buffered data and at least one new sample
        # since the previous sliding-window request. Otherwise repeated get_chunk()
        # calls can return the exact same trailing window forever.
        while time.monotonic() < deadline:
            self._drain_eeg_buffer()
            if self._cache_sample_count() >= required and self._total_samples_seen > self._last_chunk_total_samples:
                break
            time.sleep(0.05)
        available = self._cache_sample_count()
        if available < required:
            raise RuntimeError(f"Not enough BrainCo samples yet: have {available}, need {required}")
        if self._total_samples_seen <= self._last_chunk_total_samples:
            raise RuntimeError("BrainCo stream produced no new samples for realtime chunking.")
        with self._cache_lock:
            end = self._cache_write_index
            start = (end - required) % self._cache_capacity
            if start < end:
                eeg = self._eeg_cache[:, start:end].copy()
            else:
                eeg = np.concatenate((self._eeg_cache[:, start:], self._eeg_cache[:, :end]), axis=1)
        self._last_chunk_total_samples = self._total_samples_seen
        timestamps = np.arange(required, dtype=np.float64) / self.metadata.sfreq
        return eeg, timestamps

    def get_new_samples(self) -> EEGChunk:
        if self._client is None or self._sdk is None:
            raise RuntimeError("BrainCo stream is not started")
        data = self._drain_eeg_buffer()
        if data.size == 0:
            return (
                np.empty((self.metadata.n_channels, 0), dtype=np.float32),
                np.empty((0,), dtype=np.float64),
            )
        timestamps = np.arange(data.shape[1], dtype=np.float64) / self.metadata.sfreq
        return data, timestamps

    def _resolve_addr_port(self) -> tuple[str, int]:
        if not self._auto_discover:
            if self._brainco_addr and self._brainco_port > 0:
                return self._brainco_addr, self._brainco_port
            raise RuntimeError("BrainCo 手动连接需填写设备 IP 和端口")
        if self._cached_discovery_target is None:
            self._cached_discovery_target = self._discover_device()
        return self._cached_discovery_target

    def _discover_device(self) -> tuple[str, int]:
        # Init + quick scan + two mDNS windows + cleanup + Zeroconf.
        # The previous 8 s outer timeout cut off the fallback stages.
        return self._run_coroutine(self._discover_device_async(), timeout=3 * self._scan_timeout_sec + 20)

    async def _discover_device_async(self) -> tuple[str, int]:
        assert self._sdk is not None
        initialize = getattr(self._sdk, "init_adapter", None)
        if callable(initialize):
            try:
                await asyncio.wait_for(self._coerce_sdk_awaitable(initialize()), timeout=3)
            except Exception as exc:  # noqa: BLE001 - SDK discovery boundary
                LOGGER.warning("BrainCo init_adapter: %s", exc)
        scan = getattr(self._sdk, "scan_devices", None)
        if callable(scan):
            try:
                result = await asyncio.wait_for(self._coerce_sdk_awaitable(scan()), timeout=min(3, self._scan_timeout_sec))
                target = self._first_valid_discovered_target(result)
                if target:
                    return target
            except Exception as exc:  # noqa: BLE001 - SDK discovery boundary
                LOGGER.warning("BrainCo quick scan: %s", exc)
        target = await self._discover_device_via_callback_async()
        if target:
            return target
        # Some SDK versions resolve this Future only AFTER mdns_stop_scan.
        scan = getattr(self._sdk, "mdns_start_scan", None)
        task = None
        if callable(scan):
            try:
                task = asyncio.ensure_future(self._coerce_sdk_awaitable(scan()))
                await asyncio.sleep(self._scan_timeout_sec)
                await self._stop_sdk_mdns_scan_async()
                result = await asyncio.wait_for(asyncio.shield(task), timeout=2)
                target = self._first_valid_discovered_target(result)
                if target:
                    return target
            except Exception as exc:  # noqa: BLE001 - SDK discovery boundary
                LOGGER.warning("BrainCo single scan: %s", exc)
            finally:
                await self._stop_sdk_mdns_scan_async()
                await self._finish_scan_task(task)
        target = await self._discover_device_via_zeroconf_async()
        if target:
            return target
        raise RuntimeError("未发现 BrainCo 设备；请检查设备 WiFi 和防火墙，或关闭自动发现后填写 IP、端口")

    @staticmethod
    async def _finish_scan_task(task):
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001 - completed SDK session
            LOGGER.debug("BrainCo scan session ended: %s", exc)

    def _first_valid_discovered_target(self, devices: Any) -> tuple[str, int] | None:
        if devices is None:
            return None
        if isinstance(devices, (list, tuple)) and len(devices) == 2 and isinstance(devices[0], str) and isinstance(devices[1], int):
            return self._coerce_discovered_target(devices)
        if isinstance(devices, Sequence) and not isinstance(devices, (str, bytes, bytearray)):
            candidates = list(devices)
        else:
            candidates = [devices]
        for candidate in candidates:
            target = self._coerce_discovered_target(candidate)
            if target is not None:
                return target
        return None

    async def _stop_sdk_mdns_scan_async(self) -> None:
        try:
            await asyncio.wait_for(self._coerce_sdk_awaitable(self._sdk.mdns_stop_scan()), timeout=2)
        except Exception as exc:  # noqa: BLE001 - optional SDK cleanup
            LOGGER.debug("BrainCo scan stop: %s", exc)

    async def _discover_device_via_callback_async(self) -> tuple[str, int] | None:
        start = getattr(self._sdk, "mdns_start_scan_multi", None)
        if not callable(start):
            return None
        loop = asyncio.get_running_loop()
        discovered = loop.create_future()
        task = None

        def on_device(*values):
            target = self._first_valid_discovered_target(values)
            if target and not discovered.done() and not loop.is_closed():
                def deliver():
                    if not discovered.done():
                        discovered.set_result(target)
                try:
                    loop.call_soon_threadsafe(deliver)
                except RuntimeError:
                    LOGGER.debug("Ignoring BrainCo discovery callback after loop shutdown")
        try:
            task = asyncio.ensure_future(self._coerce_sdk_awaitable(start(on_device)))
            return await asyncio.wait_for(discovered, timeout=self._scan_timeout_sec)
        except Exception as exc:  # noqa: BLE001 - SDK discovery boundary
            LOGGER.warning("BrainCo multi scan: %s", exc)
            return None
        finally:
            await self._stop_sdk_mdns_scan_async()
            await self._finish_scan_task(task)

    async def _discover_device_via_zeroconf_async(self) -> tuple[str, int] | None:
        """Fallback to direct Zeroconf browsing when the SDK omits the TCP port."""

        return await asyncio.to_thread(self._discover_device_via_zeroconf_blocking)

    def _discover_device_via_zeroconf_blocking(self) -> tuple[str, int] | None:
        """Resolve BrainCo's mDNS service to an address and port using zeroconf."""

        try:
            from zeroconf import IPVersion, ServiceBrowser, ServiceListener, Zeroconf
        except ImportError:
            LOGGER.info("zeroconf is not installed; skipping direct BrainCo mDNS fallback")
            return None

        timeout_ms = max(int(self._scan_timeout_sec * 1000), 1000)
        resolved: tuple[str, int] | None = None
        resolved_event = threading.Event()
        zeroconf = Zeroconf()

        class Listener(ServiceListener):
            def add_service(self, zc: Any, service_type: str, name: str) -> None:
                self._resolve(zc, service_type, name)

            def update_service(self, zc: Any, service_type: str, name: str) -> None:
                self._resolve(zc, service_type, name)

            def remove_service(self, zc: Any, service_type: str, name: str) -> None:
                return

            def _resolve(self, zc: Any, service_type: str, name: str) -> None:
                nonlocal resolved
                if resolved_event.is_set():
                    return
                info = zc.get_service_info(service_type, name, timeout=timeout_ms)
                if info is None:
                    return
                addresses = info.parsed_addresses(IPVersion.All)
                if not addresses or int(info.port) <= 0:
                    return
                resolved = (addresses[0], int(info.port))
                resolved_event.set()

        browser: Any = None
        try:
            browser = ServiceBrowser(zeroconf, _BRAINCO_MDNS_SERVICE, listener=Listener())
            resolved_event.wait(self._scan_timeout_sec)
            if resolved is not None:
                LOGGER.info("BrainCo device discovered via zeroconf: addr=%s port=%s", resolved[0], resolved[1])
            return resolved
        finally:
            if browser is not None:
                browser.cancel()
            zeroconf.close()

    def _coerce_discovered_target(self, device: Any) -> tuple[str, int] | None:
        """Normalize SDK discovery outputs into a concrete TCP target."""

        addr = self._extract_candidate_addr(device)
        port = self._extract_candidate_port(device)
        if not addr:
            return None
        if port <= 0 and not self._auto_discover and self._brainco_port > 0:
            LOGGER.warning(
                "BrainCo auto-discovery returned address without port: %r. Falling back to configured port %s.",
                device,
                self._brainco_port,
            )
            port = self._brainco_port
        if port <= 0:
            return None
        LOGGER.info(
            "BrainCo device discovered: model=%s sn=%s addr=%s port=%s",
            getattr(device, "model", "unknown"),
            getattr(device, "sn", "unknown"),
            addr,
            port,
        )
        return addr, port

    def _extract_candidate_addr(self, device: Any) -> str:
        candidate: Any = None
        if isinstance(device, dict):
            candidate = (
                device.get("addr")
                or device.get("address")
                or device.get("host")
                or device.get("hostname")
                or device.get("ip")
            )
        elif isinstance(device, Sequence) and not isinstance(device, (str, bytes, bytearray)):
            if len(device) >= 1:
                candidate = device[0]
        else:
            candidate = (
                getattr(device, "addr", None)
                or getattr(device, "address", None)
                or getattr(device, "host", None)
                or getattr(device, "hostname", None)
            )

        if candidate is None and isinstance(device, (str, bytes, bytearray)):
            text = device.decode("utf-8", errors="ignore") if isinstance(device, (bytes, bytearray)) else device
            candidate, _ = self._split_discovery_text(text)
        return str(candidate).strip() if candidate not in (None, "") else ""

    def _extract_candidate_port(self, device: Any) -> int:
        candidate: Any = None
        if isinstance(device, dict):
            candidate = device.get("port")
        elif isinstance(device, Sequence) and not isinstance(device, (str, bytes, bytearray)):
            if len(device) >= 2:
                candidate = device[1]
        else:
            candidate = getattr(device, "port", None)

        if candidate in (None, "") and isinstance(device, (str, bytes, bytearray)):
            text = device.decode("utf-8", errors="ignore") if isinstance(device, (bytes, bytearray)) else device
            _, candidate = self._split_discovery_text(text)
        try:
            return int(candidate)
        except (TypeError, ValueError):
            return 0

    def _split_discovery_text(self, text: str) -> tuple[str, int]:
        """Parse discovery strings like 'host:port' while preserving plain IP strings."""

        value = text.strip()
        if not value:
            return "", 0
        bracket_match = re.fullmatch(r"\[(.+)\]:(\d+)", value)
        if bracket_match is not None:
            return bracket_match.group(1).strip(), int(bracket_match.group(2))
        if value.count(":") == 1:
            host, port_text = value.rsplit(":", 1)
            if host and port_text.isdigit():
                return host.strip(), int(port_text)
        return value, 0

    def _drain_eeg_buffer(self) -> np.ndarray:
        """Fetch any newly available BrainCo samples into the local rolling cache."""

        assert self._sdk is not None
        take = max(int(self.metadata.sfreq * min(self._buffer_sec, 60.0)), 256)
        data = self._normalize_buffer(self._sdk.get_eeg_buffer(take, True), allow_empty=True)
        if data.shape[1] == 0:
            return data

        self._append_eeg_samples(data, from_callback=False)
        return data

    def _wait_for_samples(self) -> None:
        deadline = time.monotonic() + self._ready_timeout_sec
        while time.monotonic() < deadline:
            if self._first_sample_event.is_set():
                return
            data = self._drain_eeg_buffer()
            if data.shape[1] > 0:
                return
            self._first_sample_event.wait(timeout=0.1)
        if self._raw_packet_count <= 0:
            raise RuntimeError(
                "Timed out waiting for BrainCo EEG samples. "
                "No TCP payloads or SDK message responses were observed after start_eeg_stream; "
                "the device likely rejected the command sequence or the configured device_id/protocol does not match."
            )
        raise RuntimeError(
            "Timed out waiting for BrainCo EEG samples. "
            "TCP payloads were observed, but neither the SDK callback path nor get_eeg_buffer() produced EEG data."
        )

    def _register_sdk_callbacks(self) -> None:
        assert self._sdk is not None
        self._sdk.set_connection_state_callback(self._handle_connection_state_callback)
        self._sdk.set_received_data_callback(self._handle_received_data_callback)
        self._sdk.set_msg_resp_callback(self._handle_message_response_callback)
        if hasattr(self._sdk, "set_eeg_data_callback"):
            self._sdk.set_eeg_data_callback(self._handle_eeg_data_callback)

    def _clear_sdk_callbacks(self) -> None:
        assert self._sdk is not None
        try:
            self._sdk.set_connection_state_callback(self._noop_callback)
        except Exception:
            pass
        try:
            self._sdk.set_received_data_callback(self._noop_callback)
        except Exception:
            pass
        try:
            self._sdk.set_msg_resp_callback(self._noop_callback)
        except Exception:
            pass
        try:
            if hasattr(self._sdk, "set_eeg_data_callback"):
                self._sdk.set_eeg_data_callback(self._noop_callback)
        except Exception:
            pass

    def _handle_connection_state_callback(self, *args: Any) -> None:
        if args:
            LOGGER.info("BrainCo connection state callback: %s", ", ".join(repr(arg) for arg in args))

    def _handle_received_data_callback(self, *args: Any) -> None:
        self._raw_packet_count += 1
        self._last_raw_packet_monotonic = time.monotonic()
        self._response_event.set()

    def _handle_message_response_callback(self, *args: Any) -> None:
        self._last_msg_response_monotonic = time.monotonic()
        self._response_event.set()
        self._record_trigger_events(args)
        message_id = self._extract_message_id(args)
        with self._msg_resp_lock:
            if message_id is None:
                self._generic_msg_responses.append(tuple(args))
            else:
                self._pending_msg_responses.setdefault(message_id, deque()).append(tuple(args))
        if args:
            LOGGER.debug("BrainCo message response callback: %s", ", ".join(repr(arg) for arg in args))

    def _handle_eeg_data_callback(self, *args: Any) -> None:
        for value in args:
            try:
                data = self._normalize_buffer(value, allow_empty=True)
            except Exception:
                continue
            if data.shape[1] > 0:
                # The SDK callback and get_eeg_buffer expose the same samples.
                # Recording is driven by get_eeg_buffer, so do not cache a second copy here.
                self._callback_sample_count += int(data.shape[1])
                self._first_sample_event.set()
                return

    def _record_trigger_events(self, payload: Any) -> None:
        """Pull TriggerBox records out of message-callback payloads.

        bcigo_sdk 2.1.x delivers trigger sync/event records through the existing
        message-response callback. The exact wrapping differs between SDK builds
        (dict, JSON string or attribute object), so accept all common shapes.
        """

        candidates: list[Any] = []
        self._collect_trigger_payloads(payload, candidates, set(), 0)
        if not candidates:
            return

        received_monotonic = time.monotonic()
        events = [
            event
            for candidate in candidates
            if (event := self._normalize_trigger_event(candidate, received_monotonic)) is not None
        ]
        if not events:
            return
        with self._trigger_lock:
            self._trigger_events.extend(events)
        for event in events:
            LOGGER.debug("BrainCo trigger event: %s", event)

    def _collect_trigger_payloads(
        self,
        value: Any,
        out: list[Any],
        seen: set[int],
        depth: int,
    ) -> None:
        if value is None or depth > 6:
            return
        if isinstance(value, (str, bytes, bytearray)):
            text = value.decode("utf-8", errors="ignore") if isinstance(value, (bytes, bytearray)) else value
            if text.lstrip().startswith(("{", "[")):
                try:
                    parsed = json.loads(text)
                except (TypeError, ValueError):
                    return
                self._collect_trigger_payloads(parsed, out, seen, depth + 1)
            return
        if isinstance(value, Mapping):
            # Guard against self-referential payloads.
            if id(value) in seen:
                return
            seen.add(id(value))
            if self._is_trigger_event(value):
                out.append(value)
                return
            nested = self._lookup_any(value, _TRIGGER_EVENT_KEYS)
            if nested is not None:
                self._collect_trigger_payloads(nested, out, seen, depth + 1)
            for key, item in value.items():
                if key not in _TRIGGER_EVENT_KEYS:
                    self._collect_trigger_payloads(item, out, seen, depth + 1)
            return
        if isinstance(value, Sequence):
            for item in value:
                self._collect_trigger_payloads(item, out, seen, depth + 1)
            return
        if self._is_trigger_event(value):
            out.append(value)
            return
        nested = self._lookup_any(value, _TRIGGER_EVENT_KEYS)
        if nested is not None:
            self._collect_trigger_payloads(nested, out, seen, depth + 1)

    def _is_trigger_event(self, value: Any) -> bool:
        event_seq = self._coerce_int(self._lookup_any(value, _TRIGGER_EVENT_SEQ_KEYS))
        sample_counter = self._coerce_int(self._lookup_any(value, _TRIGGER_SAMPLE_COUNTER_KEYS))
        return event_seq is not None and sample_counter is not None

    def _normalize_trigger_event(self, value: Any, received_monotonic: float) -> BrainCoTriggerEvent | None:
        event_seq = self._coerce_int(self._lookup_any(value, _TRIGGER_EVENT_SEQ_KEYS))
        sample_counter = self._coerce_int(self._lookup_any(value, _TRIGGER_SAMPLE_COUNTER_KEYS))
        if event_seq is None or sample_counter is None:
            return None
        return BrainCoTriggerEvent(
            event_seq=event_seq,
            sample_counter=sample_counter,
            source_tick=self._coerce_int(self._lookup_any(value, ("sourceTick", "source_tick"))),
            source_hz=self._coerce_float(self._lookup_any(value, ("sourceHz", "source_hz"))),
            wifi_tick=self._coerce_int(self._lookup_any(value, ("wifiTick", "wifi_tick"))),
            offset_tick=self._coerce_int(self._lookup_any(value, ("offsetTicks", "offset_tick"))),
            round_trip_tick=self._coerce_int(
                self._lookup_any(value, ("roundTripTicks", "round_trip_tick"))
            ),
            calibration_age_tick=self._coerce_int(
                self._lookup_any(value, ("calibrationAgeTicks", "calibration_age_tick"))
            ),
            source_drops=self._coerce_int(self._lookup_any(value, ("sourceDrops", "source_drops"))),
            received_monotonic=received_monotonic,
        )

    @staticmethod
    def _lookup_any(value: Any, keys: Sequence[str]) -> Any:
        if isinstance(value, Mapping):
            for key in keys:
                if key in value:
                    return value[key]
            return None
        for key in keys:
            if hasattr(value, key):
                return getattr(value, key)
        return None

    @staticmethod
    def _coerce_int(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _coerce_float(value: Any) -> float | None:
        if value is None or isinstance(value, bool):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _append_eeg_samples(self, data: np.ndarray, *, from_callback: bool) -> None:
        if data.shape[1] == 0:
            return
        with self._cache_lock:
            if self._eeg_cache.shape[1] != self._cache_capacity:
                self._eeg_cache = np.empty(
                    (self.metadata.n_channels, self._cache_capacity), dtype=np.float32
                )
                self._cache_write_index = 0
                self._cache_valid_samples = 0
            incoming = np.asarray(data[:, -self._cache_capacity :], dtype=np.float32)
            count = int(incoming.shape[1])
            first = min(count, self._cache_capacity - self._cache_write_index)
            self._eeg_cache[:, self._cache_write_index : self._cache_write_index + first] = incoming[:, :first]
            remaining = count - first
            if remaining:
                self._eeg_cache[:, :remaining] = incoming[:, first:]
            self._cache_write_index = (self._cache_write_index + count) % self._cache_capacity
            self._cache_valid_samples = min(self._cache_valid_samples + count, self._cache_capacity)
            self._total_samples_seen += int(data.shape[1])
        if from_callback:
            self._callback_sample_count += int(data.shape[1])
        self._first_sample_event.set()

    def _cache_sample_count(self) -> int:
        with self._cache_lock:
            return self._cache_valid_samples

    def _wait_for_command_response(self, msg_id: Any, label: str, *, allow_missing: bool = False) -> None:
        if not isinstance(msg_id, int) or msg_id <= 0:
            return

        deadline = time.monotonic() + self._ready_timeout_sec
        while time.monotonic() < deadline:
            with self._msg_resp_lock:
                responses = self._pending_msg_responses.get(msg_id)
                if responses:
                    responses.popleft()
                    if not responses:
                        self._pending_msg_responses.pop(msg_id, None)
                    return
                if self._generic_msg_responses:
                    self._generic_msg_responses.popleft()
                    LOGGER.debug(
                        "Using generic BrainCo response as acknowledgement for %s (msgId=%s).",
                        label,
                        msg_id,
                    )
                    return
            if self._response_event.wait(timeout=0.1):
                self._response_event.clear()

        if allow_missing:
            LOGGER.warning(
                "Timed out waiting for BrainCo response to %s (msgId=%s); continuing and waiting for EEG samples.",
                label,
                msg_id,
            )
            return
        raise RuntimeError(f"Timed out waiting for BrainCo response to {label} (msgId={msg_id}).")

    def _extract_message_id(self, payload: Any) -> int | None:
        if isinstance(payload, bool):
            return None
        if isinstance(payload, int):
            return payload if payload > 0 else None
        if isinstance(payload, dict):
            for key in ("msgId", "msg_id", "id"):
                message_id = self._extract_message_id(payload.get(key))
                if message_id is not None:
                    return message_id
            return None
        if isinstance(payload, (str, bytes, bytearray)):
            text = payload.decode("utf-8", errors="ignore") if isinstance(payload, (bytes, bytearray)) else payload
            match = re.search(r'"?msgId"?\s*[:=]\s*(\d+)', text)
            if match is not None:
                return int(match.group(1))
            return None
        if isinstance(payload, Sequence):
            for value in payload:
                message_id = self._extract_message_id(value)
                if message_id is not None:
                    return message_id
            return None
        for attr in ("msgId", "msg_id", "id"):
            if hasattr(payload, attr):
                message_id = self._extract_message_id(getattr(payload, attr))
                if message_id is not None:
                    return message_id
        return None

    @staticmethod
    def _noop_callback(*args: Any) -> None:
        return

    def _normalize_buffer(self, raw: Any, *, allow_empty: bool = False) -> np.ndarray:
        if raw is None:
            raw = []
        if isinstance(raw, np.ndarray):
            arr = np.asarray(raw, dtype=np.float32)
        else:
            arr = np.asarray(raw, dtype=np.float32)

        if arr.size == 0:
            if allow_empty:
                return np.empty((self.metadata.n_channels, 0), dtype=np.float32)
            raise RuntimeError("BrainCo EEG buffer is empty.")

        if arr.ndim == 1:
            if arr.size % self.metadata.n_channels != 0:
                raise RuntimeError(
                    f"Unexpected BrainCo buffer size {arr.size} for {self.metadata.n_channels} channels"
                )
            arr = arr.reshape(-1, self.metadata.n_channels)

        if arr.ndim != 2:
            raise RuntimeError(f"Unexpected BrainCo buffer shape: {arr.shape}")

        if arr.shape[1] == self.metadata.n_channels:
            return arr.T
        if arr.shape[0] == self.metadata.n_channels:
            return arr
        raise RuntimeError(f"Unexpected BrainCo channel layout: {arr.shape}")

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

        self._loop_thread = threading.Thread(target=runner, name="brainco-sdk-loop", daemon=True)
        self._loop_thread.start()
        if not ready.wait(timeout=2.0):
            raise RuntimeError("Failed to start BrainCo asyncio loop thread.")

    def _stop_loop_thread(self) -> None:
        loop = self._loop
        thread = self._loop_thread
        self._loop = None
        self._loop_thread = None
        if loop is None:
            return
        loop.call_soon_threadsafe(loop.stop)
        if thread is not None:
            thread.join(timeout=2.0)

    async def _coerce_sdk_awaitable(self, value: Any) -> Any:
        if hasattr(value, "__await__"):
            return await value
        return value

    def _run_sdk_call(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        async def runner() -> Any:
            return await self._coerce_sdk_awaitable(func(*args, **kwargs))

        return self._run_coroutine(runner(), timeout=self._ready_timeout_sec)

    def _run_coroutine(self, coro: Awaitable[Any], timeout: float) -> Any:
        if self._loop is None:
            raise RuntimeError("BrainCo asyncio loop is not running.")
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        try:
            return future.result(timeout=timeout)
        except concurrent.futures.TimeoutError as exc:
            future.cancel()
            raise RuntimeError("BrainCo SDK call timed out.") from exc
