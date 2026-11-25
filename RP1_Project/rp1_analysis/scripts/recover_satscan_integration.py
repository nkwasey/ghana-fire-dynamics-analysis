#!/usr/bin/env python3
"""Roll back a stopped, unsealed SaTScan integration transition explicitly."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from _operational_preflight import InstallationMode, require_operational_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secondary-run-id", required=True, help="Existing secondary run ID, including its _sec suffix.")
    args = parser.parse_args()
    require_operational_preflight(script_path=Path(__file__).resolve(), kernel="not-applicable", mode=InstallationMode.SOURCE)
    from rp1_analysis_v1.satscan_integration import recover_satscan_integration_transition
    try:
        result = recover_satscan_integration_transition(secondary_run_id=args.secondary_run_id)
    except Exception as exc:
        print(f"RP1_SATSCAN_RECOVERY=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("RP1_SATSCAN_RECOVERY=ROLLED_BACK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
