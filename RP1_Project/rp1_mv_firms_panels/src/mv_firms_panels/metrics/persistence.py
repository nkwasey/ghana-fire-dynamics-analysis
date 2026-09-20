# file: src/mv_firms_panels/metrics/persistence.py
"""Persistence metrics for active-fire detections.

Binding requirement
---------------------------------------
Persistence must be computed on the NH sample (nominal + high confidence):

- days_active_nh: number of distinct UTC days in the month with ≥1 NH detection.
- streak_max_nh: maximum streak length (in consecutive UTC days) of NH activity
  within the month.

Notes
-----
- This module is sensor-agnostic. Callers provide the sensor name to obtain
  sensor-prefixed output column names (via stages).
- No I/O here; determinism is enforced by stages.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

import pandas as pd

_NH = {"n", "h"}


def _max_consecutive_streak(dates: Iterable[pd.Timestamp]) -> int:
    """Return maximum run length of consecutive dates (UTC days)."""
    ds = (
        pd.to_datetime(pd.Series(list(dates), dtype="datetime64[ns]"), errors="coerce")
        .dropna()
        .sort_values()
    )
    if len(ds) == 0:
        return 0

    # Convert to integer day numbers for diff
    day_num = (ds.dt.normalize().astype("int64") // (24 * 60 * 60 * 10**9)).astype("int64")
    diffs = day_num.diff().fillna(1).astype("int64")
    # New streak whenever diff != 1
    streak_id = (diffs != 1).cumsum()
    streak_sizes = streak_id.value_counts()
    return int(streak_sizes.max()) if len(streak_sizes) > 0 else 0


def compute_monthly_persistence_metrics_nh(
    fires: pd.DataFrame,
    *,
    group_cols: Sequence[str],
    conf_col: str = "conf_cat",
    date_col: str = "date_utc",
) -> pd.DataFrame:
    """Compute NH persistence metrics at the group grain (typically unit-month)."""
    if fires is None or len(fires) == 0:
        out = pd.DataFrame({c: pd.Series(dtype="object") for c in group_cols})
        out["days_active_nh"] = pd.Series(dtype="int64")
        out["streak_max_nh"] = pd.Series(dtype="int64")
        return out

    missing = [c for c in list(group_cols) + [conf_col, date_col] if c not in fires.columns]
    if missing:
        raise ValueError(f"compute_monthly_persistence_metrics_nh: missing columns: {missing}")

    work = fires.loc[:, list(group_cols) + [conf_col, date_col]].copy()
    work[conf_col] = work[conf_col].astype("object")
    work = work.loc[work[conf_col].isin(_NH)].copy()
    if len(work) == 0:
        out = work.loc[:, list(group_cols)].drop_duplicates().copy()
        out["days_active_nh"] = 0
        out["streak_max_nh"] = 0
        return out

    # Unique unit-day activity (NH sample)
    work[date_col] = pd.to_datetime(work[date_col], errors="coerce").dt.normalize()
    work = work.loc[work[date_col].notna()].copy()
    daily = work.loc[:, list(group_cols) + [date_col]].drop_duplicates()

    days_active = daily.groupby(list(group_cols), dropna=False)[date_col].nunique().astype("int64")

    # streak_max_nh computed per group
    streak = (
        daily.groupby(list(group_cols), dropna=False)[date_col]
        .apply(_max_consecutive_streak)
        .astype("int64")
    )

    out = (
        days_active.rename("days_active_nh")
        .to_frame()
        .join(streak.rename("streak_max_nh"))
        .reset_index()
    )
    return out
