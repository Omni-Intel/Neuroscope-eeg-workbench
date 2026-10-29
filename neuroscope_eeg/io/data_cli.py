"""Command line counterparts of the desktop data actions."""
import argparse
import json
from pathlib import Path

from neuroscope_eeg.acquisition.devices import read_profile
from neuroscope_eeg.io.bids_export import export_delivery, validate_delivery
from neuroscope_eeg.io.external_recording import associate_external
from neuroscope_eeg.io.native_recording import read_jsonl, write_json


def main():
    parser = argparse.ArgumentParser(description="NeuroScope 本地记录与 EEGQC 交付工具")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export")
    export.add_argument("run", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--profile", default="")
    export.add_argument("--allow-estimated-timing", action="store_true")
    export.add_argument("--allow-simulated", action="store_true", help="仅用于 simulation_ 目录中的测试包")
    associate = commands.add_parser("associate")
    associate.add_argument("run", type=Path)
    associate.add_argument("edf", type=Path)
    associate.add_argument("--confirm-identity", action="store_true")
    validate = commands.add_parser("validate")
    validate.add_argument("package", type=Path)
    validate.add_argument("--validator", default="bids-validator")
    alignment = commands.add_parser("alignment-template")
    alignment.add_argument("run", type=Path)
    args = parser.parse_args()
    try:
        if args.command == "export":
            result = export_delivery(args.run, args.output, profile=read_profile(args.profile),
                    allow_estimated_timing=args.allow_estimated_timing, allow_simulated=args.allow_simulated)
        elif args.command == "associate":
            result = associate_external(args.run, args.edf, operator_confirmed=args.confirm_identity)
        elif args.command == "validate":
            result = validate_delivery(args.package, args.validator)
            print(json.dumps(result, ensure_ascii=False))
            return 0 if result["bids_validated"] else 1
        else:
            info = json.loads((args.run / "run.json").read_text(encoding="utf-8"))
            events = read_jsonl(args.run / "events.jsonl")
            target = args.run / "alignment.template.json"
            if target.exists():
                raise FileExistsError("对齐模板已存在，不覆盖")
            write_json(target, {"session_id": info["session_id"], "method": "", "evidence": "",
                       "events": [{"event_index": i, "onset": None, "duration": 0.0,
                                   "label": e["label"], "phase": e["phase"], "software_monotonic": e["monotonic_time"]}
                                  for i, e in enumerate(events)]})
            result = target
        print(json.dumps(result, ensure_ascii=False, default=str))
        return 0
    except Exception as exc:  # noqa: BLE001 - CLI boundary reports SDK and filesystem failures
        parser.exit(1, str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
