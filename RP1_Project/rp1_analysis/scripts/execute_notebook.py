#!/usr/bin/env python3
"""Execute the canonical RP1 Analysis notebook in a fresh kernel."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from _operational_preflight import InstallationMode, requested_kernel, require_operational_preflight


def main() -> int:
    kernel = requested_kernel(sys.argv[1:], default="python3")
    require_operational_preflight(
        script_path=Path(__file__).resolve(),
        kernel=kernel,
        mode=InstallationMode.SOURCE,
    )
    from rp1_analysis_v1.operations import execute_notebook_report, json_text

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", default=None, help="Optional portable run identifier.")
    parser.add_argument("--kernel", default="python3", help="Jupyter kernel name.")
    parser.add_argument("--timeout", type=int, default=3600, help="Per-cell timeout in seconds.")
    args = parser.parse_args()
    try:
        report = execute_notebook_report(run_id=args.run_id, kernel=args.kernel, timeout=args.timeout)
    except Exception as exc:
        print(f"RP1_ANALYSIS_V1_NOTEBOOK_EXECUTION=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json_text(report), end="")
    print("RP1_ANALYSIS_V1_NOTEBOOK_EXECUTION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
