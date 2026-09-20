# file: src/mv_firms_panels/metrics/frp.py
"""FRP metrics computed from canonical detections.

Binding method (from project CP)
--------------------------------
1) Per unit-day (UTC day), compute daily_max_frp_mw = max(frp_mw) across detections.
2) Per unit-month, compute:
   - frp_active_days = number of UTC days with ≥1 detection (after gating)
   - frp_sum_daily_max_mw = sum(daily_max_frp_mw over active days)
   - frp_p95_daily_max_mw = 95th percentile of daily_max_frp_mw over active days
   - frp_mean_mw = frp_sum_daily_max_mw / frp_active_days
   - frp_mean_mw MUST be null (NA) if frp_active_days == 0

Gating (explicit; configurable)
-------------------------------
- min_frp_mw: discard detections with FRP < min_frp_mw (default 0.0).
  This supports strict exclusion of non-physical or placeholder values.

Notes
-----
- This module is sensor-agnostic. Callers provide the sensor name to obtain
  sensor-prefixed output column names.
- No I/O here; determinism (stable sort, fixed column order) is enforced by stages.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd


def compute_daily_max_frp(
    fires: pd.DataFrame,
    *,
    id_cols: Sequence[str],
    date_col: str = "date_utc",
    frp_col: str = "frp_mw",
    yyyymm_col: str = "yyyymm",
    min_frp_mw: float = 0.0,
) -> pd.DataFrame:
    """Compute daily maximum FRP at the unit-day grain.

    Parameters
    ----------
    fires:
        Canonical detections including date and FRP columns.
    id_cols:
        Identifier columns defining unit (typically ['level', 'unit_id']).
    date_col:
        UTC date column (YYYY-MM-DD or datetime-like).
    frp_col:
        FRP in MW.
    yyyymm_col:
        Month key column; used to carry month membership through the daily table.
    min_frp_mw:
        Gate out detections with frp_mw < min_frp_mw.

    Returns
    -------
    DataFrame with columns: id_cols + [yyyymm_col, date_col, 'daily_max_frp_mw'].
    """
    if fires is None or len(fires) == 0:
        cols = list(id_cols) + [yyyymm_col, date_col, "daily_max_frp_mw"]
        return pd.DataFrame({c: pd.Series(dtype="object") for c in cols})

    need = list(id_cols) + [date_col, frp_col, yyyymm_col]
    missing = [c for c in need if c not in fires.columns]
    if missing:
        raise ValueError(f"compute_daily_max_frp: missing columns: {missing}")

    work = fires.loc[:, need].copy()

    # Gate invalid / non-physical values
    work[frp_col] = pd.to_numeric(work[frp_col], errors="coerce")
    work = work.loc[work[frp_col].notna()].copy()
    work = work.loc[work[frp_col] >= float(min_frp_mw)].copy()

    if len(work) == 0:
        cols = list(id_cols) + [yyyymm_col, date_col, "daily_max_frp_mw"]
        out = pd.DataFrame({c: pd.Series(dtype="object") for c in cols})
        out["daily_max_frp_mw"] = pd.Series(dtype="float64")
        return out

    daily = (
        work.groupby(list(id_cols) + [yyyymm_col, date_col], dropna=False)[frp_col]
        .max()
        .reset_index()
        .rename(columns={frp_col: "daily_max_frp_mw"})
    )
    daily["daily_max_frp_mw"] = daily["daily_max_frp_mw"].astype("float64")
    return daily


def compute_monthly_frp_metrics_from_daily(
    daily: pd.DataFrame,
    *,
    sensor: str,
    id_cols: Sequence[str],
    yyyymm_col: str = "yyyymm",
    date_col: str = "date_utc",
    daily_max_col: str = "daily_max_frp_mw",
) -> pd.DataFrame:
    """Aggregate daily max FRP into month-level metrics."""
    if daily is None or len(daily) == 0:
        out = pd.DataFrame({c: pd.Series(dtype="object") for c in list(id_cols) + [yyyymm_col]})
        out[f"{sensor}_frp_active_days"] = pd.Series(dtype="int64")
        out[f"{sensor}_frp_sum_daily_max_mw"] = pd.Series(dtype="float64")
        out[f"{sensor}_frp_p95_daily_max_mw"] = pd.Series(dtype="float64")
        out[f"{sensor}_frp_mean_mw"] = pd.Series(dtype="float64")
        return out

    need = list(id_cols) + [yyyymm_col, date_col, daily_max_col]
    missing = [c for c in need if c not in daily.columns]
    if missing:
        raise ValueError(f"compute_monthly_frp_metrics_from_daily: missing columns: {missing}")

    work = daily.loc[:, need].copy()
    work[daily_max_col] = pd.to_numeric(work[daily_max_col], errors="coerce")

    grp = work.groupby(list(id_cols) + [yyyymm_col], dropna=False)

    out = grp.agg(
        frp_active_days=(date_col, "nunique"),
        frp_sum_daily_max_mw=(daily_max_col, "sum"),
        frp_p95_daily_max_mw=(
            daily_max_col,
            lambda s: float(s.quantile(0.95)) if s.notna().any() else float("nan"),
        ),
    ).reset_index()

    out["frp_active_days"] = out["frp_active_days"].astype("int64")
    out["frp_sum_daily_max_mw"] = out["frp_sum_daily_max_mw"].astype("float64")
    out["frp_p95_daily_max_mw"] = out["frp_p95_daily_max_mw"].astype("float64")

    # Binding: mean is NA when active_days==0
    out["frp_mean_mw"] = pd.NA
    active = out["frp_active_days"] > 0
    out.loc[active, "frp_mean_mw"] = (
        out.loc[active, "frp_sum_daily_max_mw"] / out.loc[active, "frp_active_days"]
    )
    out["frp_mean_mw"] = out["frp_mean_mw"].astype("Float64")

    # Sensor prefix
    keep = out.loc[:, list(id_cols) + [yyyymm_col]].copy()
    keep[f"{sensor}_frp_active_days"] = out["frp_active_days"]
    keep[f"{sensor}_frp_sum_daily_max_mw"] = out["frp_sum_daily_max_mw"]
    keep[f"{sensor}_frp_p95_daily_max_mw"] = out["frp_p95_daily_max_mw"]
    keep[f"{sensor}_frp_mean_mw"] = out["frp_mean_mw"]
    return keep
