#!/usr/bin/env python3
"""Validate or admit annual c3 extended exports into a new immutable bundle."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from RP1_Project.rp1_ba_consolidator.core import main


if __name__ == "__main__":
    raise SystemExit(main())
