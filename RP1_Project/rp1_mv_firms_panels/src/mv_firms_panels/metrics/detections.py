# file: src/mv_firms_panels/metrics/detections.py
"""Detection-count metrics (confidence strata) for FIRMS-like active fire points.

Scientific definitions (explicit; binding in project CP)
------------------------------------------------------
- conf_cat is a normalised categorical confidence label shared across sensors:
  * 'l' = low confidence
  * 'n' = nominal confidence
  * 'h' = high confidence
- Monthly detection counts are simple event counts after upstream deduplication
  (the dedup key + tie-break are defined in cfg.processing.deduplication).
- det_nh is defined as det_nominal + det_high (NH sample). We never emit a
  'det_all' column.

pct_high_conf definition (explicit assumption)
----------------------------------------------
This code defines pct_high_conf as the percentage of HIGH confidence detections
among ALL detections in the unit-month:

    pct_high_conf = 100 * det_high / (det_low + det_nominal + det_high)

If the month has zero detections, pct_high_conf is 0.0.

Notes
-----
- This module is sensor-agnostic. Callers provide the sensor name to obtain
  sensor-prefixed output column names (e.g., viirs_det_high, modis_det_high).
- No I/O here; determinism (stable sort, fixed column order) is enforced by stages.
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

_CONF_CATS: tuple[str, ...] = ("l", "n", "h")


def compute_monthly_detection_metrics(
    fires: pd.DataFrame,
    *,
    sensor: str,
    group_cols: Sequence[str],
    conf_col: str = "conf_cat",
    round_pct_decimals: int = 3,
) -> pd.DataFrame:
    """Compute monthly detection counts by confidence class.

    Parameters
    ----------
    fires:
        Canonical per-detection table (or subset) containing `conf_col`.
    sensor:
        'viirs' or 'modis' (used purely for output prefixing).
    group_cols:
        Grouping columns that define the unit-month grain (typically:
        ['level', 'unit_id', 'yyyymm']).
    conf_col:
        Column name for confidence category ('l'/'n'/'h').
    round_pct_decimals:
        Deterministic rounding for pct_high_conf.

    Returns
    -------
    DataFrame with:
      group_cols +
      {sensor}_det_low, {sensor}_det_nominal, {sensor}_det_high, {sensor}_det_nh,
      {sensor}_pct_high_conf
    """
    if fires is None or len(fires) == 0:
        out = pd.DataFrame({c: pd.Series(dtype="object") for c in group_cols})
        for col in [
            f"{sensor}_det_low",
            f"{sensor}_det_nominal",
            f"{sensor}_det_high",
            f"{sensor}_det_nh",
            f"{sensor}_pct_high_conf",
        ]:
            out[col] = pd.Series(dtype="float" if col.endswith("pct_high_conf") else "int64")
        return out

    missing = [c for c in list(group_cols) + [conf_col] if c not in fires.columns]
    if missing:
        raise ValueError(f"compute_monthly_detection_metrics: missing columns: {missing}")

    work = fires.loc[:, list(group_cols) + [conf_col]].copy()
    work[conf_col] = work[conf_col].astype("object")

    # Count by confidence category at the group grain
    counts = (
        work.groupby(list(group_cols) + [conf_col], dropna=False)
        .size()
        .unstack(conf_col, fill_value=0)
        .reset_index()
    )

    for cat in _CONF_CATS:
        if cat not in counts.columns:
            counts[cat] = 0

    det_low = counts["l"].astype("int64")
    det_nom = counts["n"].astype("int64")
    det_high = counts["h"].astype("int64")
    det_total = (det_low + det_nom + det_high).astype("int64")
    det_nh = (det_nom + det_high).astype("int64")

    pct_high = pd.Series(0.0, index=counts.index, dtype="float64")
    nonzero = det_total > 0
    pct_high.loc[nonzero] = (100.0 * det_high.loc[nonzero] / det_total.loc[nonzero]).astype(
        "float64"
    )
    pct_high = pct_high.round(int(round_pct_decimals))

    out = counts.loc[:, list(group_cols)].copy()
    out[f"{sensor}_det_low"] = det_low
    out[f"{sensor}_det_nominal"] = det_nom
    out[f"{sensor}_det_high"] = det_high
    out[f"{sensor}_det_nh"] = det_nh
    out[f"{sensor}_pct_high_conf"] = pct_high

    return out
