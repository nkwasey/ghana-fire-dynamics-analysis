# file: scripts/aggregate_level.py
"""Wrapper script for `aggregate`.

Example
-------
python scripts/aggregate_level.py --config configs/example_project.yaml --sensor viirs

Equivalent to:
python -m mv_firms_panels.cli.main --config configs/example_project.yaml aggregate --sensor viirs
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mv_firms_panels.cli.commands import cmd_aggregate


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="aggregate_level.py")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--sensor", required=True, choices=["viirs", "modis"])
    p.add_argument("--run-id", default=None)
    p.add_argument("--zip-sha256", default=None)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)

    return cmd_aggregate(
        repo_root=_repo_root(),
        config_path=args.config,
        sensor=args.sensor,
        run_id=args.run_id,
        zip_sha256=args.zip_sha256,
        log_level=args.log_level,
        skip_existing=bool(args.skip_existing),
        force=bool(args.force),
    )


if __name__ == "__main__":
    raise SystemExit(main())