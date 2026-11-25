#!/usr/bin/env python3
"""Explicitly run one prepared SaTScan model and capture prospective evidence."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from _operational_preflight import InstallationMode, require_operational_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secondary-run-id", required=True)
    parser.add_argument("--model-id", required=True)
    parser.add_argument("--executable", type=Path, required=True, help="Actual batch executable; its version is probed.")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()
    require_operational_preflight(script_path=Path(__file__).resolve(), kernel="not-applicable", mode=InstallationMode.SOURCE)
    from rp1_analysis_v1.execution_evidence import execute_registered_satscan_model
    from rp1_analysis_v1.paths import ProjectPaths
    try:
        report = execute_registered_satscan_model(paths=ProjectPaths.discover(), secondary_run_id=args.secondary_run_id,
            model_id=args.model_id, executable_path=args.executable, timeout_seconds=args.timeout)
    except Exception as exc:
        print(f"RP1_SATSCAN_OBSERVED_EXECUTION=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, sort_keys=True))
    print("RP1_SATSCAN_OBSERVED_EXECUTION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
