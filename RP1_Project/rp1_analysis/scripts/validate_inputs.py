#!/usr/bin/env python3
"""Validate governed RP1 Analysis inputs and analytical populations."""

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
    from rp1_analysis_v1.operations import json_text, validate_inputs_report

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path, help="Optional path for the validation report.")
    args = parser.parse_args()
    try:
        report = validate_inputs_report(json_out=args.json_out)
    except Exception as exc:
        print(f"RP1_ANALYSIS_V1_INPUT_VALIDATION=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json_text(report), end="")
    status = str(report.get("input_validation_status", report.get("status", "FAIL")))
    identity = str(report.get("canonical_input_identity", "DIFFERENT"))
    print(f"RP1_ANALYSIS_V1_INPUT_VALIDATION={status}")
    print(f"CANONICAL_INPUT_IDENTITY={identity}")
    return 0 if status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
