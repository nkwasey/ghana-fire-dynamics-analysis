# file: src/mv_firms_panels/io/writers.py
"""Deterministic writers for tabular and geospatial QA artefacts.

Binding determinism rules
-------------------------
- Stable sort before every write (use mergesort for stability).
- Fixed column order when an explicit order is provided.
- Never write indices unless explicitly requested.

Monthly-panel writers
--------------------------
- Support writing DataFrames to either:
  * plain CSV (``.csv``), or
  * gzipped CSV (``.csv.gz``)
- For ``.csv.gz`` outputs, gzip bytes are deterministic to support stable hashing:
  * gzip header timestamp fixed (mtime=0)
  * original filename omitted from the gzip header

QA writers
----------------------------
- Optional geospatial QA exports (GeoPackage / Shapefile) are *best-effort*.
  They must not affect contracted outputs. If the GDAL/OGR stack is unavailable
  at runtime, writers raise ``WriteError`` and callers may choose to continue.

Failure modes
-------------
- Unsupported suffixes raise ``WriteError`` with a clear message.
"""

from __future__ import annotations

import gzip
import io
import json
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from mv_firms_panels.core.schema import enforce_exact_column_order


class WriteError(ValueError):
    """Raised when an output write fails."""


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _normalise_sort_keys(sort_keys: Sequence[str] | None) -> list[str] | None:
    if sort_keys is None:
        return None
    keys = [str(k) for k in sort_keys if str(k).strip()]
    return keys if len(keys) > 0 else None


def stable_sort_df(df: pd.DataFrame, sort_keys: Sequence[str]) -> pd.DataFrame:
    keys = _normalise_sort_keys(sort_keys)
    if keys is None:
        return df.reset_index(drop=True)
    missing = [c for c in keys if c not in df.columns]
    if missing:
        raise WriteError(f"sort_keys missing from DataFrame: {missing}")
    return df.sort_values(keys, kind="mergesort").reset_index(drop=True)


def _dataframe_to_csv_bytes(df: pd.DataFrame) -> bytes:
    """Render a DataFrame to UTF-8 CSV bytes with a fixed line terminator.

    Notes
    -----
    - Writing via an in-memory buffer avoids platform-specific newline translation.
    - The returned bytes are the canonical payload used for both .csv and .csv.gz writes.
    """
    buf = io.StringIO()
    df.to_csv(buf, index=False, lineterminator="\n")
    return buf.getvalue().encode("utf-8")


def _write_gzip_deterministic(*, payload: bytes, path: Path, compresslevel: int = 9) -> None:
    """Write deterministic gzip bytes (mtime=0; no stored filename)."""
    ensure_dir(path.parent)
    with path.open("wb") as f:
        # filename='' prevents embedding a varying original filename into the gzip header
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=f, compresslevel=compresslevel, mtime=0
        ) as gz:
            gz.write(payload)


def write_dataframe_csv(
    *,
    df: pd.DataFrame,
    path: str | Path,
    sort_keys: Sequence[str] | None = None,
    column_order: Sequence[str] | None = None,
) -> Path:
    """Write DataFrame deterministically to .csv or .csv.gz.

    The output format is inferred from the filename suffix:
    - ``*.csv``
    - ``*.csv.gz``

    Unsupported formats (including ``*.parquet`` or bare ``*.gz``) raise ``WriteError``.
    """
    out_path = Path(path)
    ensure_dir(out_path.parent)

    out_df = df.copy()

    keys = _normalise_sort_keys(sort_keys)
    if keys is not None:
        out_df = stable_sort_df(out_df, keys)

    if column_order is not None:
        out_df = enforce_exact_column_order(out_df, column_order, allow_reorder=True)

    name = out_path.name.lower()
    if name.endswith(".csv.gz"):
        payload = _dataframe_to_csv_bytes(out_df)
        _write_gzip_deterministic(payload=payload, path=out_path)
        return out_path

    if name.endswith(".csv"):
        payload = _dataframe_to_csv_bytes(out_df)
        out_path.write_bytes(payload)
        return out_path

    if name.endswith(".gz"):
        raise WriteError("Unsupported gzip suffix: only '.csv.gz' is supported")

    raise WriteError("Unsupported output format: expected .csv or .csv.gz")


def write_json(
    *,
    obj: object,
    path: str | Path,
) -> Path:
    out_path = Path(path)
    ensure_dir(out_path.parent)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, sort_keys=True, indent=2)
        f.write("\n")
    return out_path


def write_geofile(
    *,
    gdf: object,
    path: str | Path,
    driver: str | None = None,
    layer: str | None = None,
) -> Path:
    """Write a geospatial file from a GeoDataFrame-like object.

    This is intentionally a thin wrapper around ``gdf.to_file`` so the core package
    does not import GeoPandas at module import time.

    Parameters
    ----------
    gdf:
        Expected to be a GeoPandas GeoDataFrame (or compatible) with a ``to_file`` method.
    path:
        Output path. For Shapefiles, this is the ``.shp`` path (sidecar files will be created).
    driver:
        Optional OGR driver name (e.g., ``"GPKG"``, ``"ESRI Shapefile"``).
    layer:
        Optional layer name (GeoPackage).

    Raises
    ------
    WriteError
        If writing fails (often due to missing GDAL/OGR support in the runtime environment).
    """
    out_path = Path(path)
    ensure_dir(out_path.parent)

    kwargs = {"index": False}
    if driver is not None:
        kwargs["driver"] = driver
    if layer is not None:
        kwargs["layer"] = layer

    try:
        to_file = gdf.to_file
    except Exception as e:
        raise WriteError(
            "gdf has no to_file() method; geopandas is required for geospatial writes"
        ) from e

    try:
        to_file(out_path, **kwargs)
    except Exception as e:
        raise WriteError(f"Failed to write geospatial file to {out_path}") from e

    return out_path


def write_geo_qa_bundle(
    *,
    out_dir: str | Path,
    unmatched_points: pd.DataFrame,
    outside_land_points: pd.DataFrame | None,
    summary: pd.DataFrame,
    prefix: str,
) -> None:
    """Write the QA artefacts with deterministic filenames."""
    out_dir = Path(out_dir)
    ensure_dir(out_dir)

    def _candidate_sort(df_: pd.DataFrame) -> list[str] | None:
        candidates = ["source_file", "acq_datetime_utc", "latitude", "longitude"]
        keys = [c for c in candidates if c in df_.columns]
        return keys if keys else None

    write_dataframe_csv(
        df=unmatched_points,
        path=out_dir / f"{prefix}_unmatched_points.csv",
        sort_keys=_candidate_sort(unmatched_points),
    )

    if outside_land_points is not None:
        write_dataframe_csv(
            df=outside_land_points,
            path=out_dir / f"{prefix}_outside_land_points.csv",
            sort_keys=_candidate_sort(outside_land_points),
        )

    write_dataframe_csv(
        df=summary,
        path=out_dir / f"{prefix}_geo_qa_summary.csv",
        sort_keys=None,
    )
