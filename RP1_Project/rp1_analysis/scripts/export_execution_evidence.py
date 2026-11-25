#!/usr/bin/env python3
"""Export or validate a separate immutable execution-evidence bundle."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from _operational_preflight import InstallationMode, require_operational_preflight


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", help="Fresh or historical base run identity to export.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--allow-declared-limitations", action="store_true", help="Explicitly export historical/deferred limitations without upgrading their claims.")
    parser.add_argument("--validate-only", action="store_true", help="Verify an existing bundle without changing it.")
    parser.add_argument("--expected-manifest-sha256", help="Independently supplied manifest SHA-256 for validation.")
    args = parser.parse_args()
    if args.expected_manifest_sha256 and not args.validate_only:
        parser.error("--expected-manifest-sha256 requires --validate-only")
    require_operational_preflight(script_path=Path(__file__).resolve(), kernel="not-applicable", mode=InstallationMode.SOURCE)
    from rp1_analysis_v1.execution_evidence import export_execution_evidence, validate_execution_evidence_bundle
    from rp1_analysis_v1.paths import ProjectPaths
    try:
        if args.validate_only:
            manifest = validate_execution_evidence_bundle(
                args.output_dir, expected_manifest_sha256=args.expected_manifest_sha256,
            )
            result = {"status": "PASS", "evidence_status": manifest["status"], "run_id": manifest["run_id"], "files": len(manifest["files"])}
        else:
            if not args.run_id:
                parser.error("--run-id is required for export")
            result = export_execution_evidence(paths=ProjectPaths.discover(), run_id=args.run_id,
                output_dir=args.output_dir, allow_declared_limitations=args.allow_declared_limitations)
    except Exception as exc:
        print(f"RP1_EXECUTION_EVIDENCE=FAIL\n{exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    print("RP1_EXECUTION_EVIDENCE=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
