# file: scripts/pipeline.py
"""Wrapper script for `pipeline`.

This is the recommended entry point for most users.

Examples
--------
Dry-run plan (no IO beyond config snapshot):
    python scripts/pipeline.py --config configs/example_project.yaml --dry-run

Full run over detected years (from file_glob):
    python scripts/pipeline.py --config configs/example_project.yaml

Full run over explicit range:
    python scripts/pipeline.py --config configs/example_project.yaml --years 2014-2024
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mv_firms_panels.cli.commands import cmd_pipeline


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pipeline.py")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--run-id", default=None)
    p.add_argument("--years", default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-plots", action="store_true")
    p.add_argument("--zip-sha256", default=None)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)

    return cmd_pipeline(
        repo_root=_repo_root(),
        config_path=args.config,
        run_id=args.run_id,
        years=args.years,
        dry_run=bool(args.dry_run),
        make_plots=not bool(args.no_plots),
        zip_sha256=args.zip_sha256,
        log_level=args.log_level,
        skip_existing=bool(args.skip_existing),
        force=bool(args.force),
    )


if __name__ == "__main__":
    raise SystemExit(main())