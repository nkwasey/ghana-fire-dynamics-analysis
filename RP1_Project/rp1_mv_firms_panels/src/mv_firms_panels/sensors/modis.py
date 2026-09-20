# file: src/mv_firms_panels/sensors/modis.py
"""MODIS sensor-specific normalisation.

Scientific assumptions (explicit)
--------------------------------
FIRMS MODIS 'confidence' is typically numeric in the range 0..100 (%).

This pipeline maps numeric confidence to binding categories {l,n,h} using
configurable thresholds:

- low_lt: values strictly less than this are "l"
- high_ge: values greater than or equal to this are "h"
- otherwise: "n"

The defaults are documented in configs/example_project.yaml (low_lt=30, high_ge=80).

Strictness:
- Under strict=True, missing/non-numeric/NaN values raise ValueError.
- Under strict=False, they become NA.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
from mv_firms_panels.core.time_spine import yyyymm_from_acq_date_series
from mv_firms_panels.sensors.base import require_valid_conf_cat


def modis_conf_cat_from_confidence(
    confidence: pd.Series,
    *,
    thresholds_pct: Mapping[str, int],
    strict: bool = True,
) -> pd.Series:
    """Map MODIS numeric confidence to conf_cat ∈ {l,n,h}."""
    low_lt = thresholds_pct.get("low_lt")
    high_ge = thresholds_pct.get("high_ge")
    if low_lt is None or high_ge is None:
        raise ValueError("thresholds_pct must include low_lt and high_ge")

    s_num = pd.to_numeric(confidence, errors="coerce")
    mapped = pd.Series(pd.NA, index=confidence.index, dtype="object")

    mapped.loc[s_num < float(low_lt)] = "l"
    mapped.loc[(s_num >= float(low_lt)) & (s_num < float(high_ge))] = "n"
    mapped.loc[s_num >= float(high_ge)] = "h"

    if strict and (mapped.isna().any() or s_num.isna().any()):
        raise ValueError(
            "MODIS confidence contains missing or non-numeric values under strict=True"
        )

    return require_valid_conf_cat(mapped, strict=strict)


def modis_yyyymm_from_acq_date(acq_date: pd.Series, *, strict: bool = True) -> pd.Series:
    """Deterministically derive yyyymm from acquisition date."""
    return yyyymm_from_acq_date_series(acq_date, strict=strict)
