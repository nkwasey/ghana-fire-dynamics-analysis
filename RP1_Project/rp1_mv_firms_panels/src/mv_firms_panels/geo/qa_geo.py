# file: src/mv_firms_panels/geo/qa_geo.py
"""QA helpers for geospatial joins and masking.

Contractual outputs
---------------------------
Callers should be able to export QA artefacts including:
- Unmatched points (no polygon unit_id assigned after join)
- Outside-land points (if land mask provided)
- Coverage summaries (counts + rates)

This module only *builds* QA tables. Writing is handled in io.writers.
"""

from __future__ import annotations

from collections.abc import Sequence

import geopandas as gpd
import pandas as pd


def build_unmatched_points(
    *,
    joined_points: gpd.GeoDataFrame,
    keep_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return a tabular view of points where unit_id is null."""
    if "unit_id" not in joined_points.columns:
        raise ValueError("joined_points must contain 'unit_id' column")

    df = joined_points.loc[joined_points["unit_id"].isna()].copy()
    if keep_columns is not None:
        missing = [c for c in keep_columns if c not in df.columns]
        if missing:
            raise ValueError(f"Requested keep_columns missing: {missing}")
        df = df.loc[:, list(keep_columns)].copy()
    if "geometry" in df.columns and (keep_columns is None or "geometry" not in keep_columns):
        df = df.drop(columns=["geometry"])
    return pd.DataFrame(df)


def build_outside_land_points(
    *,
    outside_points: gpd.GeoDataFrame,
    keep_columns: Sequence[str] | None = None,
) -> pd.DataFrame:
    """Return a tabular view of points flagged as outside-land."""
    df = outside_points.copy()
    if keep_columns is not None:
        missing = [c for c in keep_columns if c not in df.columns]
        if missing:
            raise ValueError(f"Requested keep_columns missing: {missing}")
        df = df.loc[:, list(keep_columns)].copy()
    if "geometry" in df.columns and (keep_columns is None or "geometry" not in keep_columns):
        df = df.drop(columns=["geometry"])
    return pd.DataFrame(df)


def build_join_qa_summary(
    *,
    join_stats: pd.DataFrame,
    land_stats: dict[str, float] | None = None,
) -> pd.DataFrame:
    """Combine join and land-mask stats into a single 1-row QA summary."""
    if len(join_stats) != 1:
        raise ValueError("join_stats must be a 1-row DataFrame")

    row = dict(join_stats.iloc[0].to_dict())
    if land_stats is not None:
        for k, v in land_stats.items():
            row[f"land_{k}"] = v
    return pd.DataFrame([row])
