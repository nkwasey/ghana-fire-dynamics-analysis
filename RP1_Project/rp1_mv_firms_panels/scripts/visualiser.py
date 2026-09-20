# file: scripts/visualiser.py
"""Wrapper script for `visualise`.

Example
-------
python scripts/visualiser.py --config configs/example_project.yaml

Equivalent to:
python -m mv_firms_panels.cli.main --config configs/example_project.yaml visualise
"""

from __future__ import annotations

import argparse
from pathlib import Path

from mv_firms_panels.cli.commands import cmd_visualise


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="visualiser.py")
    p.add_argument("--config", required=True, type=Path)
    p.add_argument("--run-id", default=None)
    p.add_argument("--no-plots", action="store_true")
    p.add_argument("--zip-sha256", default=None)
    p.add_argument("--log-level", default="INFO")
    p.add_argument("--skip-existing", action="store_true")
    p.add_argument("--force", action="store_true")
    args = p.parse_args(argv)

    return cmd_visualise(
        repo_root=_repo_root(),
        config_path=args.config,
        run_id=args.run_id,
        make_plots=not bool(args.no_plots),
        zip_sha256=args.zip_sha256,
        log_level=args.log_level,
        skip_existing=bool(args.skip_existing),
        force=bool(args.force),
    )


if __name__ == "__main__":
    raise SystemExit(main())