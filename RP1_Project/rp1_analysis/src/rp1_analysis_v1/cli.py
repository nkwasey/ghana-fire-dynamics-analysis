"""Installed command-line interface for RP1 Analysis."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .operations import (
    doctor_report,
    execute_notebook_report,
    json_text,
    reference_check_report,
    satscan_integrate_report,
    satscan_prepare_report,
    satscan_status_report,
    validate_inputs_report,
    validate_run_report,
    version_report,
    write_json_report,
)


def _path(value: str) -> Path:
    return Path(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="rp1-analysis",
        description="Operational command surface for RP1 Analysis.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("version", help="Report package and schema identities.")

    doctor = sub.add_parser("doctor", help="Inspect the installed operational runtime.")
    doctor.add_argument("--json-out", type=_path, help="Optional JSON report path.")

    validate_inputs = sub.add_parser("validate-inputs", help="Validate governed analysis inputs.")
    validate_inputs.add_argument("--json-out", type=_path, help="Optional JSON report path.")

    reference = sub.add_parser("reference-check", help="Qualify numerical reference methods.")
    reference.add_argument("--json-out", type=_path, help="Optional JSON report path.")

    run = sub.add_parser("run", help="Execute the canonical analysis notebook.")
    run.add_argument("--run-id", default=None, help="Optional portable run identifier.")
    run.add_argument("--kernel", default="python3", help="Jupyter kernel name.")
    run.add_argument("--timeout", type=int, default=3600, help="Per-cell timeout in seconds.")

    validate_run = sub.add_parser("validate-run", help="Validate a completed canonical run.")
    validate_run.add_argument("--run-id", required=True, help="Run identifier to validate.")
    validate_run.add_argument(
        "--write-report",
        action="store_true",
        help="Write run-validation and output-hash reports into the closeout run.",
    )

    satscan = sub.add_parser("satscan", help="Prepare, inspect and integrate external SaTScan results.")
    satscan_sub = satscan.add_subparsers(dest="satscan_command", required=True)

    prepare = satscan_sub.add_parser("prepare", help="Generate governed SaTScan input families.")
    prepare.add_argument("--run-id", default=None, help="Optional secondary run identifier.")
    prepare.add_argument("--timeout", type=int, default=300, help="Preparation timeout in seconds.")

    status = satscan_sub.add_parser("status", help="Inspect external-result state without modifying the run.")
    status.add_argument("--run-id", required=True, help="Secondary run identifier.")

    integrate = satscan_sub.add_parser("integrate", help="Validate and integrate genuine external results.")
    integrate.add_argument("--run-id", required=True, help="Secondary run identifier.")

    return parser


def _emit(payload: object) -> None:
    print(json_text(payload), end="")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "version":
            _emit(version_report())
            return 0
        if args.command == "doctor":
            report = doctor_report()
            write_json_report(args.json_out, report)
            _emit(report)
            return 0 if report["status"] == "PASS" else 1
        if args.command == "validate-inputs":
            report = validate_inputs_report(json_out=args.json_out)
            _emit(report)
            status = str(report.get("input_validation_status", report.get("status", "FAIL")))
            identity = str(report.get("canonical_input_identity", "DIFFERENT"))
            print(f"RP1_ANALYSIS_V1_INPUT_VALIDATION={status}")
            print(f"CANONICAL_INPUT_IDENTITY={identity}")
            return 0 if status == "PASS" else 1
        if args.command == "reference-check":
            report = reference_check_report(json_out=args.json_out)
            _emit(report)
            print(f"RP1_REFERENCE_METHOD_QUALIFICATION={report['status']}")
            return 0 if report["status"] == "PASS" else 1
        if args.command == "run":
            report = execute_notebook_report(
                run_id=args.run_id,
                kernel=args.kernel,
                timeout=args.timeout,
            )
            _emit(report)
            print("RP1_ANALYSIS_V1_NOTEBOOK_EXECUTION=PASS")
            return 0
        if args.command == "validate-run":
            report = validate_run_report(
                run_id=args.run_id,
                write_report=bool(args.write_report),
            )
            _emit(report)
            print("RP1_ANALYSIS_V1_RUN_VALIDATION=PASS")
            return 0
        if args.command == "satscan":
            if args.satscan_command == "prepare":
                report = satscan_prepare_report(run_id=args.run_id, timeout=args.timeout)
            elif args.satscan_command == "status":
                report = satscan_status_report(secondary_run_id=args.run_id)
            elif args.satscan_command == "integrate":
                report = satscan_integrate_report(secondary_run_id=args.run_id)
            else:  # pragma: no cover - argparse prevents this
                parser.error("Unknown SaTScan command")
            _emit(report)
            return 0
        parser.error("Unknown command")
    except Exception as exc:
        print(f"RP1_ANALYSIS_OPERATION=FAIL\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
