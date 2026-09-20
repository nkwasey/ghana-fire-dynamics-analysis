#!/usr/bin/env python3
"""Validate a complete RP1 Analysis run and its governed output hashes."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _operational_preflight import InstallationMode, require_operational_preflight


def main() -> int:
    require_operational_preflight(
        script_path=Path(__file__).resolve(),
        kernel="not-applicable",
        mode=InstallationMode.SOURCE,
    )
    from rp1_analysis_v1.operations import json_text, validate_run_report

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Run identifier used by execute_notebook.py.")
    parser.add_argument(
        "--write-report",
        action="store_true",
        help="Write validation report and output hash inventory into the closeout run.",
    )
    args = parser.parse_args()
    try:
        report = validate_run_report(run_id=args.run_id, write_report=bool(args.write_report))
    except Exception as exc:
        print(f"RP1_ANALYSIS_V1_RUN_VALIDATION=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json_text(report), end="")
    print("RP1_ANALYSIS_V1_RUN_VALIDATION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
