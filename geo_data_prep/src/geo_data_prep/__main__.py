"""
Module entrypoint to support: python -m geo_data_prep ...
This is used by tests to avoid reliance on console-script discovery.
"""

from __future__ import annotations

from geo_data_prep.cli.main import main

if __name__ == "__main__":
    raise SystemExit(main())
