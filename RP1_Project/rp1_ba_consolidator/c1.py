"""The production consolidator accepts the configured c3 source contract."""
from dataclasses import dataclass
from pathlib import Path
import sys


@dataclass(frozen=True)
class C1Options:
    input_dir: Path
    output_dir: Path
    boundary_label: str = 'unspecified'
    validate_only: bool = False


def stage(*args, **kwargs):
    raise ValueError('C1 staging is retired; use annual c3 extended CSV preparation')


def verify_handoff(*args, **kwargs):
    raise ValueError('C1 handoffs cannot satisfy the c3-only production contract')


def main(argv=None):
    print('ERROR: C1 staging is retired. Use tools/consolidate_ba.py for c3.', file=sys.stderr)
    return 2
