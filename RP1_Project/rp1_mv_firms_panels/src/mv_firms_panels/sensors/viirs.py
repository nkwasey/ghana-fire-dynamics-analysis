# file: src/mv_firms_panels/sensors/viirs.py
"""VIIRS sensor-specific normalisation.

Scientific assumptions (explicit)
--------------------------------
FIRMS VIIRS 'confidence' is typically categorical. This pipeline maps the source
categories onto the binding {l,n,h} set using a *configurable mapping table*.

- Input values are treated case-insensitively and with surrounding whitespace ignored.
- Any value not present in the mapping table is an error under strict=True.

This avoids silent remapping when FIRMS changes encodings or when users provide
equivalent point datasets with different labels.
"""

from __future__ import annotations

from collections.abc import Mapping

import pandas as pd
from mv_firms_panels.core.time_spine import yyyymm_from_acq_date_series
from mv_firms_panels.sensors.base import _normalise_key, require_valid_conf_cat


def viirs_conf_cat_from_confidence(
    confidence: pd.Series,
    *,
    viirs_map: Mapping[str, str],
    strict: bool = True,
) -> pd.Series:
    """Map VIIRS confidence values to conf_cat ∈ {l,n,h}.

    Parameters
    ----------
    confidence:
        Source confidence series (typically strings like low/nominal/high).
    viirs_map:
        Mapping of source labels -> {l,n,h}. Keys are normalised (strip+lower).
    strict:
        If True, raise on unmappable or missing values. If False, return NA for those rows.

    Returns
    -------
    pandas.Series
        conf_cat series (dtype object).
    """
    norm_map = {_normalise_key(k): _normalise_key(v) for k, v in dict(viirs_map).items()}

    s = confidence.astype("object")
    mapped = s.map(lambda x: norm_map.get(_normalise_key(x), pd.NA))

    if strict and mapped.isna().any():
        bad = sorted({_normalise_key(v) for v in s[mapped.isna()].dropna().unique().tolist()})
        raise ValueError(
            "Unmappable VIIRS confidence values under strict=True. " f"Bad values: {bad}"
        )

    return require_valid_conf_cat(mapped, strict=strict)


def viirs_yyyymm_from_acq_date(acq_date: pd.Series, *, strict: bool = True) -> pd.Series:
    """Deterministically derive yyyymm from acquisition date."""
    return yyyymm_from_acq_date_series(acq_date, strict=strict)
