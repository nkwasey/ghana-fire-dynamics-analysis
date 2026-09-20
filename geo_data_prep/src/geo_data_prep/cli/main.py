"""
Console entry wrapper.

Note: `pyproject.toml` exposes `geo-prep = geo_data_prep.cli.app:app`.
Typer supports being called directly as a callable.
"""

from __future__ import annotations

from geo_data_prep.cli.app import app


def main() -> int:
    """Run the CLI."""
    app()
    return 0
