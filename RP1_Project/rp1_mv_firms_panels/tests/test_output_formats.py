# file: tests/test_output_formats.py
"""Output format support for monthly panels.

Coverage
--------
- CSV write via write_dataframe_csv
- CSV.GZ write via write_dataframe_csv
- Deterministic gzip bytes (same DataFrame written twice produces identical SHA-256)

These tests are deterministic by construction and do not require large inputs.
"""

from __future__ import annotations

import pandas as pd
from mv_firms_panels.core.hashing import sha256_file
from mv_firms_panels.io.writers import write_dataframe_csv


def _example_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unit_id": ["U2", "U1"],
            "yyyymm": [202402, 202401],
            "det_nh": [3, 1],
        }
    )


def test_csv_write(tmp_path) -> None:
    df = _example_df()
    p = tmp_path / "panel_monthly.csv"
    out = write_dataframe_csv(df=df, path=p)
    assert out.exists()
    got = pd.read_csv(out)
    assert list(got.columns) == ["unit_id", "yyyymm", "det_nh"]
    assert len(got) == 2


def test_csv_gz_write(tmp_path) -> None:
    df = _example_df()
    p = tmp_path / "panel_monthly.csv.gz"
    out = write_dataframe_csv(df=df, path=p)
    assert out.exists()
    got = pd.read_csv(out)
    assert list(got.columns) == ["unit_id", "yyyymm", "det_nh"]
    assert len(got) == 2


def test_deterministic_gzip_bytes(tmp_path) -> None:
    df = _example_df()
    p1 = tmp_path / "a.csv.gz"
    p2 = tmp_path / "b.csv.gz"

    write_dataframe_csv(df=df, path=p1)
    write_dataframe_csv(df=df, path=p2)

    h1 = sha256_file(p1)
    h2 = sha256_file(p2)
    assert h1 == h2
