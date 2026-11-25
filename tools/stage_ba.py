#!/usr/bin/env python3
"""Burned-area staging requires the configured c3 production route."""
import sys


def main(argv=None):
    print('ERROR: C1 staging is retired. Use tools/consolidate_ba.py for annual c3 extended CSVs.', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
