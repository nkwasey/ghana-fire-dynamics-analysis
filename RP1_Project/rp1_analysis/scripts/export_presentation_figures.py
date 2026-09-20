#!/usr/bin/env python3
"""Export standalone presentation figures from an existing qualified RP1 run.

The script is intentionally thin. Figure definitions, source selection,
rendering, dimensions, formats and SaTScan result-state requirements are owned
by the package configuration and renderer modules.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _operational_preflight import InstallationMode, require_operational_preflight


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  %(prog)s --list\n"
            "  %(prog)s --run-dir out/runs/<run>_close --output-dir presentation_figures --figure rq2_coastal_trend\n"
            "  %(prog)s --run-dir out/runs/<run>_close --output-dir presentation_figures --group rq3\n"
            "  %(prog)s --run-dir out/runs/<run>_close --output-dir presentation_figures --all\n"
            "  %(prog)s --run-dir out/runs/<run>_close --output-dir presentation_figures --all --format png\n"
        ),
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        help="Existing qualified RP1 closeout run directory under out/runs (the configured *_close member).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="New external presentation-output directory. It must not already exist and must be outside the source run.",
    )
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--list", action="store_true", help="List the configured presentation export catalogue.")
    actions.add_argument("--figure", metavar="EXPORT_ID", help="Export one configured presentation figure.")
    actions.add_argument("--group", metavar="GROUP", help="Export one configured group: study, rq1, rq2, rq3 or rq4.")
    actions.add_argument("--all", action="store_true", help="Export the complete configured presentation-figure estate.")
    parser.add_argument(
        "--format",
        dest="formats",
        metavar="FORMAT",
        action="append",
        help="Restrict output to a configured format (for example png or pdf). Repeat to request more than one. Omit to use configured formats.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    require_operational_preflight(
        script_path=Path(__file__).resolve(),
        kernel="not-applicable",
        mode=InstallationMode.SOURCE,
    )

    from rp1_analysis_v1.presentation import load_presentation_export_registry
    from rp1_analysis_v1.presentation_export import (
        PresentationExportError,
        export_presentation_figure_estate,
        list_presentation_exports,
    )

    if args.list:
        registry = load_presentation_export_registry()
        rows = list_presentation_exports()
        print(
            json.dumps(
                {
                    "schema": "rp1-presentation-export-list-v1",
                    "groups": list(registry.groups),
                    "configured_formats": list(registry.output.formats),
                    "exports": rows,
                },
                indent=2,
            )
        )
        return 0

    if args.run_dir is None or args.output_dir is None:
        parser.error("selected export mode requires both --run-dir and --output-dir (--figure, --group or --all)")

    try:
        report = export_presentation_figure_estate(
            run_dir=args.run_dir,
            output_dir=args.output_dir,
            export_id=args.figure,
            group=args.group,
            all_exports=bool(args.all),
            formats=args.formats,
        )
    except PresentationExportError as exc:
        print(f"RP1_PRESENTATION_EXPORT=FAIL\n{exc}", file=sys.stderr)
        return 1

    print(json.dumps(report, indent=2, sort_keys=True))
    if report["status"] != "PASS":
        print(
            "RP1_PRESENTATION_EXPORT=FAIL\n"
            f"{report['failed_exports']} requested export(s) failed. "
            f"See {report['manifest']} and {report['report']} for exact errors.",
            file=sys.stderr,
        )
        return 1

    print("RP1_PRESENTATION_EXPORT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
