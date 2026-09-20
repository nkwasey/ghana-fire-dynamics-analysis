# file: src/mv_firms_panels/sensors/base.py
"""Sensor-normalisation primitives (VIIRS + MODIS).

Scope
---------------
This module defines shared, *sensor-agnostic* helpers used to normalise FIRMS-like
active-fire detections into an internal canonical representation.

Scientific/contractual bindings (see CP):
- conf_cat must be one of {l,n,h}.
- det_nh is defined later as det_nominal + det_high (never det_all).
- Determinism: mapping is pure and stable; errors are raised for unmappable values
  by default (strict=True) to avoid silent category drift.

Design notes
------------
- These functions operate on pandas objects so they are directly testable.
- Spatial/IO concerns are intentionally outside the sensor-semantics layer.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import pandas as pd

# Binding categories
VALID_CONF_CATS: Sequence[str] = ("l", "n", "h")
CONF_CAT_RANK: dict[str, int] = {"l": 0, "n": 1, "h": 2}


def _normalise_key(x: object) -> str:
    """Normalise a mapping key/value to a comparable string."""
    if x is None:
        return ""
    return str(x).strip().lower()


def require_valid_conf_cat(conf_cat: pd.Series, *, strict: bool = True) -> pd.Series:
    """Validate that conf_cat only contains {l,n,h} (or NA when strict=False).

    Parameters
    ----------
    conf_cat:
        Series of mapped confidence categories.
    strict:
        If True, any NA or invalid value raises ValueError. If False, invalid values become NA.

    Returns
    -------
    pandas.Series
        The validated series (dtype object).
    """
    s = conf_cat.astype("object")
    bad_mask = ~s.isna() & ~s.isin(list(VALID_CONF_CATS))
    if bad_mask.any():
        bad_vals = sorted({_normalise_key(v) for v in s[bad_mask].unique().tolist()})
        if strict:
            raise ValueError(f"conf_cat contains invalid values (expected l/n/h): {bad_vals}")
        s.loc[bad_mask] = pd.NA

    if strict and s.isna().any():
        raise ValueError("conf_cat contains missing values under strict=True")
    return s


def conf_cat_rank(conf_cat: pd.Series, *, strict: bool = True) -> pd.Series:
    """Return numeric ranks for conf_cat for deterministic tie-breaks (h>n>l)."""
    s = require_valid_conf_cat(conf_cat, strict=strict)
    return s.map(CONF_CAT_RANK).astype("Int64")


@dataclass(frozen=True)
class SensorNormalisationResult:
    """Minimal normalisation outputs produced by sensor adapters."""

    conf_cat: pd.Series
    # yyyymm is derived from acquisition date (UTC month boundaries)
    yyyymm: pd.Series
