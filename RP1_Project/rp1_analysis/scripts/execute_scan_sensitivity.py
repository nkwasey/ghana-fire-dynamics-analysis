#!/usr/bin/env python3
"""Execute the standalone MODIS Poisson burnable-support sensitivity."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline-secondary-dir", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--executable", type=Path, help="Prepare and run the batch engine with an execution receipt.")
    mode.add_argument("--prepare-only", action="store_true", help="Prepare the sensitivity inputs.")
    mode.add_argument("--integrate-results", action="store_true", help="Validate existing raw engine result files.")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    from rp1_analysis_v1 import scan_sensitivity

    expected = (Path(__file__).resolve().parents[1] / "src").resolve()
    if not Path(scan_sensitivity.__file__).resolve().is_relative_to(expected):
        parser.error(f"Import rp1_analysis_v1 from this checkout's source directory: {expected}")
    try:
        options = {"baseline_secondary_dir": args.baseline_secondary_dir, "run_dir": args.run_dir}
        if args.prepare_only:
            summary = scan_sensitivity.prepare_scan_sensitivity(**options)
        elif args.integrate_results:
            summary = scan_sensitivity.integrate_scan_sensitivity(**options)
        else:
            summary = scan_sensitivity.execute_scan_sensitivity(
                **options, executable_path=args.executable, timeout_seconds=args.timeout,
            )
    except Exception as exc:
        print(f"MODIS_SCANSENSITIVITY=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
