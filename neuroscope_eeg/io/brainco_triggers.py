"""Read BrainCo's raw trigger evidence without guessing stimulus codes or clocks."""
import json
from pathlib import Path

from neuroscope_eeg.io.edf_paths import edf_path


def read_brainco_triggers(run_dir):
    """Read both new and historical native recordings; never modify the source."""
    root = Path(edf_path(run_dir))
    device = json.loads((root / "device.json").read_text(encoding="utf-8"))
    if device.get("source_type") != "brainco":
        return None
    path = root / "raw/chunks.jsonl"
    records = []
    if path.exists():
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                chunk = json.loads(line)
                field = chunk.get("auxiliaries", {}).get("brainco_trigger_events_json")
                if field is None:
                    continue
                try:
                    events = json.loads(field["value"])
                    if not isinstance(events, list):
                        raise ValueError("expected a list")
                    for event in events:
                        if not isinstance(event, dict) or any(
                            type(event.get(key)) is not int or event[key] < 0
                            for key in ("event_seq", "sample_counter")
                        ):
                            raise ValueError("invalid event_seq/sample_counter")
                        records.append({**event, "saved_chunk_offset": chunk.get("offset"),
                                        "chunk_log_line": line_number})
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(f"BrainCo trigger record invalid at chunk line {line_number}: {exc}") from exc
    sync = device.get("extra", {}).get("brainco_trigger_sync", {"state": "unrecorded", "error": ""})
    return {
        "summary": {"received_events": len(records), "startup_sync": sync,
                    "alignment_status": "device_sample_counter_unmapped",
                    "physical_onset_calibrated": False,
                    "note": "event_seq 是触发序号，不是范式码；sample_counter 尚未映射到保存 EEG，不能据此声明物理同步。"},
        "records": records,
    }
