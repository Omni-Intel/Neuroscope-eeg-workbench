"""Experiment timing, Neuracle hardware triggers, and LSL marker routing."""

from neuroscope_eeg.timing.codebook import CODEBOOK_VERSION, EVENT_CODES, event_code_for
from neuroscope_eeg.timing.models import TriggerDispatch, TriggerRequest
from neuroscope_eeg.timing.router import TriggerRouter

__all__ = (
    "CODEBOOK_VERSION",
    "EVENT_CODES",
    "TriggerDispatch",
    "TriggerRequest",
    "TriggerRouter",
    "event_code_for",
)
