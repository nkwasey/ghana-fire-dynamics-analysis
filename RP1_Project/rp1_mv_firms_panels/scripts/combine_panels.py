# file: scripts/combine_panels.py
"""Wrapper script for `combine`.

Example
-------
python scripts/combine_panels.py --config configs/example_project.yaml --start-yyyymm 201401 --end-yyyymm 202412

Equivalent to:
python -m mv_firms_panels.cli.main --config configs/example_project.yaml combine --start-yyyymm 201401 --end-yyyymm 202412
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mv_firms_panels.cli.commands import cmd_combine


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="combine_panels.py")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--run-id", default=None)
    p.add_argument("--start-yyyymm", default=None, type=int)
    p.add_argument("--end-yyyymm", default=None, type=int)
    p.add_argument("--zip-sha256", default=None)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)

    return cmd_combine(
        repo_root=_repo_root(),
        config_path=args.config,
        run_id=args.run_id,
        start_yyyymm=args.start_yyyymm,
        end_yyyymm=args.end_yyyymm,
        zip_sha256=args.zip_sha256,
        log_level=args.log_level,
        skip_existing=bool(args.skip_existing),
        force=bool(args.force),
    )


if __name__ == "__main__":
    raise SystemExit(main())