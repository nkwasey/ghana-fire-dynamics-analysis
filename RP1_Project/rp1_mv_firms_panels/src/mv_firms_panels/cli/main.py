"""Command-line interface for the MV-FIRMS panel pipeline.

The installed ``mv-firms-panels`` command and ``python -m
mv_firms_panels.cli.main`` share this parser. Common operational options are
accepted either before or after the selected subcommand.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from mv_firms_panels.cli.commands import (
    CliError,
    cmd_aggregate,
    cmd_combine,
    cmd_pipeline,
    cmd_prepare_year,
    cmd_visualise,
)


def _path(value: str) -> Path:
    return Path(value)


def _add_common_options(parser: argparse.ArgumentParser, *, subcommand: bool) -> None:
    default = argparse.SUPPRESS if subcommand else None
    parser.add_argument(
        "--config",
        type=_path,
        default=default,
        help="Path to project YAML config (may appear before or after the subcommand)",
    )
    parser.add_argument(
        "--repo-root",
        type=_path,
        default=default,
        help="Repository root (default: derived from the config path)",
    )
    parser.add_argument("--run-id", default=default, help="Optional explicit run_id override")
    parser.add_argument(
        "--zip-sha256",
        default=default,
        help="Optional SHA-256 of the input repository ZIP for provenance",
    )
    parser.add_argument("--log-level", default=default if subcommand else "INFO", help="Logging level")
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        default=default if subcommand else False,
        help="Safely skip stages when the sentinel, outputs and schema checks agree",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        default=default if subcommand else False,
        help="Force stage execution despite resume gating",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mv-firms-panels", add_help=True)
    _add_common_options(parser, subcommand=False)
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare-year", help="Ingest annual points into fires_canonical")
    _add_common_options(prepare, subcommand=True)
    prepare.add_argument("--sensor", required=True, choices=["viirs", "modis"], help="Sensor name")
    prepare.add_argument("--year", required=True, type=int, help="4-digit year")

    aggregate = sub.add_parser("aggregate", help="Build per-sensor monthly metrics")
    _add_common_options(aggregate, subcommand=True)
    aggregate.add_argument("--sensor", required=True, choices=["viirs", "modis"], help="Sensor name")
    aggregate.add_argument("--start-yyyymm", default=None, type=int, help="Optional inclusive start yyyymm")
    aggregate.add_argument("--end-yyyymm", default=None, type=int, help="Optional inclusive end yyyymm")

    combine = sub.add_parser("combine", help="Merge sensors into the balanced monthly panel")
    _add_common_options(combine, subcommand=True)
    combine.add_argument("--start-yyyymm", default=None, type=int, help="Optional inclusive start yyyymm")
    combine.add_argument("--end-yyyymm", default=None, type=int, help="Optional inclusive end yyyymm")

    visualise = sub.add_parser("visualise", help="Produce summaries and plots from panel_monthly")
    _add_common_options(visualise, subcommand=True)
    visualise.add_argument("--no-plots", action="store_true", help="Disable plot generation")

    pipeline = sub.add_parser("pipeline", help="Run prepare-year, aggregate, combine and visualise")
    _add_common_options(pipeline, subcommand=True)
    pipeline.add_argument(
        "--years",
        default=None,
        help='Years list "2014,2015" or range "2014-2024" (default: auto-detect)',
    )
    pipeline.add_argument(
        "--years-viirs",
        default=None,
        help="Optional VIIRS-specific years list/range overriding --years",
    )
    pipeline.add_argument(
        "--years-modis",
        default=None,
        help="Optional MODIS-specific years list/range overriding --years",
    )
    pipeline.add_argument("--dry-run", action="store_true", help="Print the resolved plan without running")
    pipeline.add_argument("--no-plots", action="store_true", help="Disable plot generation")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.config is None:
        parser.error("--config is required and may be placed before or after the subcommand")

    try:
        if args.command == "prepare-year":
            return cmd_prepare_year(
                repo_root=args.repo_root,
                config_path=args.config,
                sensor=args.sensor,
                year=args.year,
                run_id=args.run_id,
                zip_sha256=args.zip_sha256,
                log_level=args.log_level,
                skip_existing=bool(args.skip_existing),
                force=bool(args.force),
            )
        if args.command == "aggregate":
            return cmd_aggregate(
                repo_root=args.repo_root,
                config_path=args.config,
                sensor=args.sensor,
                run_id=args.run_id,
                start_yyyymm=args.start_yyyymm,
                end_yyyymm=args.end_yyyymm,
                zip_sha256=args.zip_sha256,
                log_level=args.log_level,
                skip_existing=bool(args.skip_existing),
                force=bool(args.force),
            )
        if args.command == "combine":
            return cmd_combine(
                repo_root=args.repo_root,
                config_path=args.config,
                run_id=args.run_id,
                start_yyyymm=args.start_yyyymm,
                end_yyyymm=args.end_yyyymm,
                zip_sha256=args.zip_sha256,
                log_level=args.log_level,
                skip_existing=bool(args.skip_existing),
                force=bool(args.force),
            )
        if args.command == "visualise":
            return cmd_visualise(
                repo_root=args.repo_root,
                config_path=args.config,
                run_id=args.run_id,
                make_plots=not bool(args.no_plots),
                zip_sha256=args.zip_sha256,
                log_level=args.log_level,
                skip_existing=bool(args.skip_existing),
                force=bool(args.force),
            )
        if args.command == "pipeline":
            return cmd_pipeline(
                repo_root=args.repo_root,
                config_path=args.config,
                run_id=args.run_id,
                years=args.years,
                years_viirs=args.years_viirs,
                years_modis=args.years_modis,
                dry_run=bool(args.dry_run),
                make_plots=not bool(args.no_plots),
                zip_sha256=args.zip_sha256,
                log_level=args.log_level,
                skip_existing=bool(args.skip_existing),
                force=bool(args.force),
            )
        raise CliError(f"Unknown command: {args.command}")
    except CliError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
