"""Desktop background pipeline: independent delivery and Word report outcomes."""
import argparse
import json
import sys

from neuroscope_eeg.io.automatic_delivery import ensure_delivery
from neuroscope_eeg.reports.generate import generate_report


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("run_directory")
    args = parser.parse_args()

    def emit(**message):
        print(json.dumps(message, ensure_ascii=False), flush=True)

    delivery = ensure_delivery(args.run_directory, lambda text: emit(progress=text))
    emit(delivery=delivery)
    try:
        report = generate_report(args.run_directory, lambda text: emit(progress=text))
        emit(report=str(report))
    except Exception as exc:  # noqa: BLE001 - report and export have independent status
        emit(report_error=str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
