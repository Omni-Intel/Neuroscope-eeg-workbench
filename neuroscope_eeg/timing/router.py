from __future__ import annotations

from dataclasses import replace
import threading
from typing import Any

from neuroscope_eeg.timing.codebook import CODEBOOK_VERSION, EventCodeDefinition
from neuroscope_eeg.timing.models import TriggerDispatch, TriggerRequest


class TriggerRouterError(RuntimeError):
    pass


class TriggerRouter:
    def __init__(self, mode: str, *, hardware: Any = None, lsl: Any) -> None:
        if mode not in {"hardware_lsl", "lsl_only"}:
            raise ValueError("timing mode must be hardware_lsl or lsl_only")
        self.mode = mode
        self.hardware = hardware
        self.lsl = lsl
        self.session_id = ""
        self._sequence = 0
        self._open = False
        self._lock = threading.Lock()

    def open(self, session_id: str) -> None:
        with self._lock:
            if self._open:
                raise TriggerRouterError("TriggerRouter 已经打开")
            self.session_id = str(session_id)
            try:
                if self.mode == "hardware_lsl":
                    if self.hardware is None:
                        raise TriggerRouterError("hardware_lsl 模式需要 NDE0001 transport")
                    self.hardware.open()
                self.lsl.open(self.session_id)
            except Exception:
                if self.hardware is not None:
                    self.hardware.close()
                self.session_id = ""
                raise
            self._sequence = 0
            self._open = True

    def dispatch(
        self,
        request: TriggerRequest,
        definition: EventCodeDefinition | None,
    ) -> TriggerDispatch:
        with self._lock:
            if not self._open:
                raise TriggerRouterError("TriggerRouter 尚未打开")
            self._sequence += 1
            sequence = self._sequence
            event_id = f"EVT-{sequence:06d}"
            code = definition.code if definition is not None else None
            symbol = definition.symbol if definition is not None else ""
            hardware_requested = self.mode == "hardware_lsl" and code is not None
            hardware_write = None
            hardware_error = ""
            if hardware_requested:
                try:
                    hardware_write = self.hardware.send(code)
                except Exception as exc:
                    hardware_error = str(exc)

            if self.mode == "lsl_only":
                status = "lsl_software_sync_uncalibrated"
            elif definition is None:
                status = "lsl_metadata_only"
            elif hardware_write is not None:
                status = "hardware_dispatched_unverified"
            else:
                status = "hardware_failed"

            dispatch = TriggerDispatch(
                event_id=event_id,
                sequence=sequence,
                session_id=self.session_id,
                paradigm=request.paradigm,
                phase=request.phase,
                label=request.label,
                payload=dict(request.payload),
                wall_time=float(request.wall_time),
                intent_time=float(request.intent_time),
                onset_hook_time=float(request.onset_hook_time),
                hook_type=request.hook_type,
                timing_mode=self.mode,
                timing_status=status,
                hardware_code=code,
                hardware_symbol=symbol,
                hardware_requested=hardware_requested,
                hardware_frame_hex=hardware_write.frame_hex if hardware_write else "",
                hardware_dispatch_time=hardware_write.requested_at if hardware_write else None,
                hardware_write_complete_time=hardware_write.write_completed_at if hardware_write else None,
                hardware_error=hardware_error,
                clock_bridge=getattr(self.lsl, "last_clock_bridge", None),
            )
            marker_payload = {
                "schema_version": 2,
                "codebook_version": CODEBOOK_VERSION,
                "event_id": event_id,
                "sequence": sequence,
                "session_id": self.session_id,
                "paradigm": request.paradigm,
                "phase": request.phase,
                "label": request.label,
                "hardware_code": code,
                "hardware_symbol": symbol,
                "hardware_requested": hardware_requested,
                "hardware_dispatch_time": dispatch.hardware_dispatch_time,
                "hardware_write_complete_time": dispatch.hardware_write_complete_time,
                "hardware_error": hardware_error,
                "wall_time": dispatch.wall_time,
                "intent_time": dispatch.intent_time,
                "onset_hook_time": dispatch.onset_hook_time,
                "hook_type": dispatch.hook_type,
                "timing_mode": self.mode,
                "timing_status": status,
                "block": request.payload.get("block_index", request.payload.get("block")),
                "trial": request.payload.get("trial_index", request.payload.get("trial")),
                "condition": request.payload.get("condition"),
                "payload": dict(request.payload),
            }
            try:
                lsl_timestamp = float(self.lsl.push(marker_payload))
                dispatch = replace(dispatch, lsl_timestamp=lsl_timestamp)
            except Exception as exc:
                lsl_error = str(exc)
                if hardware_write is not None:
                    status = "hardware_only_degraded"
                elif hardware_error:
                    status = "unsynchronized"
                else:
                    status = "lsl_failed"
                dispatch = replace(dispatch, timing_status=status, lsl_error=lsl_error)
            return dispatch

    def close(self) -> None:
        with self._lock:
            if not self._open:
                return
            try:
                self.lsl.close()
            finally:
                if self.hardware is not None:
                    self.hardware.close()
                self._open = False
                self.session_id = ""
