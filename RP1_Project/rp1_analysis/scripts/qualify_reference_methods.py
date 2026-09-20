#!/usr/bin/env python3
"""Qualify implemented numerical capabilities against independent references."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    from rp1_analysis_v1.operations import json_text, reference_check_report

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-out", type=Path)
    args = parser.parse_args()
    try:
        report = reference_check_report(json_out=args.json_out)
    except Exception as exc:
        print(f"RP1_REFERENCE_METHOD_QUALIFICATION=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json_text(report), end="")
    print(f"RP1_REFERENCE_METHOD_QUALIFICATION={report['status']}")
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
