#!/usr/bin/env python3
"""Merge AF and admitted annual c3 BA sources into separate-domain panels.

The 111-column projection preserves c3 values and guarded nulls. All 69 original
fields and file/row identities remain in the mandatory evidence companion.
Use --profile c3 and an admitted handoff; existing outputs are never replaced.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import os
import re
import math
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd

# The lightweight contract is also included in the analysis wheel.
_CONTRACT_SOURCE = Path(__file__).resolve().parent / "rp1_analysis" / "src"
_UMBRELLA_SOURCE = Path(__file__).resolve().parents[1]
if str(_UMBRELLA_SOURCE) not in sys.path:
    sys.path.insert(0, str(_UMBRELLA_SOURCE))
_contract_import_path = sys.path[:]
try:
    if str(_CONTRACT_SOURCE) not in sys.path:
        sys.path.insert(0, str(_CONTRACT_SOURCE))
    from rp1_ba_contracts import c3
finally:
    # A local contract import must not shadow installed distribution metadata.
    sys.path[:] = _contract_import_path

try:
    from RP1_Project import rp1_local_io as _local_io
except ModuleNotFoundError as exc:
    if exc.name != "RP1_Project":
        raise
    import rp1_local_io as _local_io


# =============================================================================
# LOCKED CONTRACT CONSTANTS
# =============================================================================

MERGE_SCHEMA_VERSION = "rp1_fire_panel_consolidated_v3"
START_YYYYMM = 200101
END_YYYYMM = 202412
VIIRS_SUPPORT_START_YYYYMM = 201201
BA2012_SUPPORT_START_YYYYMM = 201201
ANALYSIS_OVERLAP_START_YYYYMM = None
EXPECTED_UNITS = {"acz": 0, "district": 0}  # Bound to selected geography before production loading.
SUPPORTED_LEVELS = ("acz", "district")
MERGE_KEY = ["level", "unit_id", "yyyymm"]

# -----------------------------------------------------------------------------
# Umbrella-repository default path contract
# -----------------------------------------------------------------------------
#
# The canonical repository uses the umbrella root as the default repository
# root. This merger script lives under RP1_Project/, so AF, BA and analysis
# output defaults are resolved relative to that root rather than relative to the
# script directory. Centralising these paths keeps the operational layout
# explicit and auditable.
# -----------------------------------------------------------------------------
DEFAULT_UNIT_UNIVERSE_RELATIVE = Path("geo_data_prep/out/example_acz/unit_universe.csv")
DEFAULT_AF_ROOT_RELATIVE = Path("RP1_Project/rp1_mv_firms_panels/out/runs/ghana_full/rp1_af_exports")
DEFAULT_AF_DISCOVERY_GLOB = "RP1_Project/rp1_mv_firms_panels/out/runs/*/rp1_af_exports"
DEFAULT_OUTPUT_DIR_RELATIVE = Path("RP1_Project/rp1_analysis/data/raw")

PROVENANCE_SCHEMA_VERSION = "rp1-fire-panel-provenance-v2"
PROVENANCE_PATH_SEMANTICS = {
    "origin_path": (
        "Repository-relative source/original provenance path. It may refer to a historical "
        "or upstream intermediate location that is not distributed with the release."
    ),
    "staged_path": (
        "Repository-relative current durable location in the distributed repository; null only "
        "for upstream intermediate sources that are intentionally not distributed."
    ),
}

IDENTITY_COLUMNS = [
    "level",
    "unit_id",
    "unit_code",
    "unit_name",
    "parent_level",
    "parent_id",
    "parent_code",
    "parent_name",
]

COMMON_PREFIX_COLUMNS = [
    "run_id",
    "schema_version",
    "level",
    "unit_id",
    "unit_code",
    "unit_name",
    "parent_level",
    "parent_id",
    "parent_code",
    "parent_name",
    "yyyymm",
    "year",
    "month",
]

MODIS_AF_ANALYTICAL_COLUMNS = [
    "modis_det_low",
    "modis_det_nominal",
    "modis_det_high",
    "modis_det_all",
    "modis_det_nh",
    "modis_pct_high_conf",
    "modis_days_active_nh",
    "modis_streak_max_nh",
    "modis_frp_active_days",
    "modis_frp_sum_daily_max_mw",
    "modis_frp_mean_mw",
    "modis_frp_p95_daily_max_mw",
]

VIIRS_AF_ANALYTICAL_COLUMNS = [
    "viirs_det_low",
    "viirs_det_nominal",
    "viirs_det_high",
    "viirs_det_all",
    "viirs_det_nh",
    "viirs_pct_high_conf",
    "viirs_days_active_nh",
    "viirs_streak_max_nh",
    "viirs_frp_active_days",
    "viirs_frp_sum_daily_max_mw",
    "viirs_frp_mean_mw",
    "viirs_frp_p95_daily_max_mw",
]

BA_ANALYTICAL_COLUMNS = [
    "modis_ba_km2",
    "modis_burned_pixel_count",
    "modis_ba_any",
    "modis_aoi_area_land_km2",
    "modis_burnable_km2_union",
    "modis_burnable_km2_annual",
    "modis_burned_frac_union",
    "modis_burned_frac_annual",
    "modis_zero_union_den_flag",
    "modis_zero_annual_den_flag",
]

MODIS_AF_REQUIRED_COLUMNS = COMMON_PREFIX_COLUMNS + MODIS_AF_ANALYTICAL_COLUMNS
VIIRS_AF_REQUIRED_COLUMNS = COMMON_PREFIX_COLUMNS + VIIRS_AF_ANALYTICAL_COLUMNS
BA_REQUIRED_COLUMNS = COMMON_PREFIX_COLUMNS + BA_ANALYTICAL_COLUMNS

BA_RENAME_2001 = {
    "modis_ba_km2": "modis_ba_km2_ba2001",
    "modis_burned_pixel_count": "modis_burned_pixel_count_ba2001",
    "modis_ba_any": "modis_ba_any_ba2001",
    "modis_aoi_area_land_km2": "modis_aoi_area_land_km2_ba2001",
    "modis_burnable_km2_union": "modis_burnable_km2_union_ba2001",
    "modis_burnable_km2_annual": "modis_burnable_km2_annual_ba2001",
    "modis_burned_frac_union": "modis_burned_frac_union_ba2001",
    "modis_burned_frac_annual": "modis_burned_frac_annual_ba2001",
    "modis_zero_union_den_flag": "modis_zero_union_den_flag_ba2001",
    "modis_zero_annual_den_flag": "modis_zero_annual_den_flag_ba2001",
}

BA_RENAME_2012 = {
    "modis_ba_km2": "modis_ba_km2_ba2012",
    "modis_burned_pixel_count": "modis_burned_pixel_count_ba2012",
    "modis_ba_any": "modis_ba_any_ba2012",
    "modis_aoi_area_land_km2": "modis_aoi_area_land_km2_ba2012",
    "modis_burnable_km2_union": "modis_burnable_km2_union_ba2012",
    "modis_burnable_km2_annual": "modis_burnable_km2_annual_ba2012",
    "modis_burned_frac_union": "modis_burned_frac_union_ba2012",
    "modis_burned_frac_annual": "modis_burned_frac_annual_ba2012",
    "modis_zero_union_den_flag": "modis_zero_union_den_flag_ba2012",
    "modis_zero_annual_den_flag": "modis_zero_annual_den_flag_ba2012",
}

FINAL_OUTPUT_COLUMNS = [
    # 1. Governance, identity, and time
    "run_id",
    "schema_version",
    "level",
    "unit_id",
    "unit_code",
    "unit_name",
    "parent_level",
    "parent_id",
    "parent_code",
    "parent_name",
    "yyyymm",
    "year",
    "month",
    # 2. MODIS AF
    "modis_det_low",
    "modis_det_nominal",
    "modis_det_high",
    "modis_det_all",
    "modis_det_nh",
    "modis_pct_high_conf",
    "modis_days_active_nh",
    "modis_streak_max_nh",
    "modis_frp_active_days",
    "modis_frp_sum_daily_max_mw",
    "modis_frp_mean_mw",
    "modis_frp_p95_daily_max_mw",
    # 3. VIIRS AF
    "viirs_det_low",
    "viirs_det_nominal",
    "viirs_det_high",
    "viirs_det_all",
    "viirs_det_nh",
    "viirs_pct_high_conf",
    "viirs_days_active_nh",
    "viirs_streak_max_nh",
    "viirs_frp_active_days",
    "viirs_frp_sum_daily_max_mw",
    "viirs_frp_mean_mw",
    "viirs_frp_p95_daily_max_mw",
    # 4. BA-2001
    "modis_ba_km2_ba2001",
    "modis_burned_pixel_count_ba2001",
    "modis_ba_any_ba2001",
    "modis_aoi_area_land_km2_ba2001",
    "modis_burnable_km2_union_ba2001",
    "modis_burnable_km2_annual_ba2001",
    "modis_burned_frac_union_ba2001",
    "modis_burned_frac_annual_ba2001",
    "modis_zero_union_den_flag_ba2001",
    "modis_zero_annual_den_flag_ba2001",
    # 5. BA-2012
    "modis_ba_km2_ba2012",
    "modis_burned_pixel_count_ba2012",
    "modis_ba_any_ba2012",
    "modis_aoi_area_land_km2_ba2012",
    "modis_burnable_km2_union_ba2012",
    "modis_burnable_km2_annual_ba2012",
    "modis_burned_frac_union_ba2012",
    "modis_burned_frac_annual_ba2012",
    "modis_zero_union_den_flag_ba2012",
    "modis_zero_annual_den_flag_ba2012",
    # 6. AF primary and AF summary derivations
    "modis_det_primary",
    "modis_det_nh_share_of_all",
    "modis_det_primary_any",
    "viirs_det_primary",
    "viirs_det_nh_share_of_all",
    "viirs_det_primary_any",
    # 7. BA area-rate derivations
    "modis_ba_km2_per100km2_union_ba2001",
    "modis_ba_km2_per100km2_annual_ba2001",
    "modis_ba_km2_per100km2_union_ba2012",
    "modis_ba_km2_per100km2_annual_ba2012",
    # 8. AF density derivations
    "modis_det_primary_per100km2_burnable_union_ba2001",
    "modis_det_primary_per100km2_burnable_annual_ba2001",
    "modis_det_primary_per100km2_burnable_union_ba2012",
    "modis_det_primary_per100km2_burnable_annual_ba2012",
    "viirs_det_primary_per100km2_burnable_union_ba2001",
    "viirs_det_primary_per100km2_burnable_annual_ba2001",
    "viirs_det_primary_per100km2_burnable_union_ba2012",
    "viirs_det_primary_per100km2_burnable_annual_ba2012",
    # 9. FRP density derivations
    "modis_frp_sum_daily_max_mw_per_km2_burnable_union_ba2001",
    "modis_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2001",
    "modis_frp_sum_daily_max_mw_per_km2_burnable_union_ba2012",
    "modis_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2012",
    "viirs_frp_sum_daily_max_mw_per_km2_burnable_union_ba2001",
    "viirs_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2001",
    "viirs_frp_sum_daily_max_mw_per_km2_burnable_union_ba2012",
    "viirs_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2012",
    # 10. Within-sensor intensity derivations
    "modis_det_primary_per_active_day",
    "modis_frp_sum_daily_max_mw_per_active_day",
    "modis_frp_sum_daily_max_mw_per_primary_det",
    "viirs_det_primary_per_active_day",
    "viirs_frp_sum_daily_max_mw_per_active_day",
    "viirs_frp_sum_daily_max_mw_per_primary_det",
    # 11. Support flags
    "viirs_supported_flag",
    "ba2012_supported_flag",
    "full_overlap_supported_flag",
    # 12. Concordance flags
    "ba_any_ba2001_and_viirs_primary_any_flag",
    "ba_any_ba2012_and_viirs_primary_any_flag",
    "ba_any_ba2001_and_modis_primary_any_flag",
    "ba_any_ba2012_and_modis_primary_any_flag",
    "ba_any_ba2001_without_viirs_primary_flag",
    "ba_any_ba2012_without_viirs_primary_flag",
    "viirs_primary_without_ba_any_ba2001_flag",
    "viirs_primary_without_ba_any_ba2012_flag",
    "viirs_primary_any_and_modis_primary_any_flag",
    # 13. Merge / provenance QC
    "af_modis_source_present",
    "af_viirs_source_present",
    "ba2001_source_present",
    "ba2012_source_present",
    "row_in_canonical_spine",
    "merge_key_complete_flag",
    "merge_duplicate_resolved_flag",
    "viirs_structural_missing_flag",
    "ba2012_structural_missing_flag",
    "merge_note",
]

assert len(FINAL_OUTPUT_COLUMNS) == 111, "Final consolidated schema must contain exactly 111 columns."

ALL_FINAL_BA_COLUMNS = [col for col in FINAL_OUTPUT_COLUMNS if col.endswith("_ba2001") or col.endswith("_ba2012")]
VIIRS_BASE_FINAL_COLUMNS = VIIRS_AF_ANALYTICAL_COLUMNS
VIIRS_DERIVED_FINAL_COLUMNS = [
    "viirs_det_primary",
    "viirs_det_nh_share_of_all",
    "viirs_det_primary_any",
    "viirs_det_primary_per100km2_burnable_union_ba2001",
    "viirs_det_primary_per100km2_burnable_annual_ba2001",
    "viirs_det_primary_per100km2_burnable_union_ba2012",
    "viirs_det_primary_per100km2_burnable_annual_ba2012",
    "viirs_frp_sum_daily_max_mw_per_km2_burnable_union_ba2001",
    "viirs_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2001",
    "viirs_frp_sum_daily_max_mw_per_km2_burnable_union_ba2012",
    "viirs_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2012",
    "viirs_det_primary_per_active_day",
    "viirs_frp_sum_daily_max_mw_per_active_day",
    "viirs_frp_sum_daily_max_mw_per_primary_det",
    "ba_any_ba2001_and_viirs_primary_any_flag",
    "ba_any_ba2012_and_viirs_primary_any_flag",
    "ba_any_ba2001_without_viirs_primary_flag",
    "ba_any_ba2012_without_viirs_primary_flag",
    "viirs_primary_without_ba_any_ba2001_flag",
    "viirs_primary_without_ba_any_ba2012_flag",
    "viirs_primary_any_and_modis_primary_any_flag",
]

BA2012_FINAL_COLUMNS = list(
    dict.fromkeys(
        [
            *[col for col in FINAL_OUTPUT_COLUMNS if col.endswith("_ba2012")],
            "modis_ba_km2_per100km2_union_ba2012",
            "modis_ba_km2_per100km2_annual_ba2012",
            "modis_det_primary_per100km2_burnable_union_ba2012",
            "modis_det_primary_per100km2_burnable_annual_ba2012",
            "viirs_det_primary_per100km2_burnable_union_ba2012",
            "viirs_det_primary_per100km2_burnable_annual_ba2012",
            "modis_frp_sum_daily_max_mw_per_km2_burnable_union_ba2012",
            "modis_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2012",
            "viirs_frp_sum_daily_max_mw_per_km2_burnable_union_ba2012",
            "viirs_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2012",
            "ba_any_ba2012_and_viirs_primary_any_flag",
            "ba_any_ba2012_and_modis_primary_any_flag",
            "ba_any_ba2012_without_viirs_primary_flag",
            "viirs_primary_without_ba_any_ba2012_flag",
        ]
    )
)

AF_NUMERIC_INT_COLUMNS = [
    "modis_det_low",
    "modis_det_nominal",
    "modis_det_high",
    "modis_det_all",
    "modis_det_nh",
    "modis_days_active_nh",
    "modis_streak_max_nh",
    "modis_frp_active_days",
    "viirs_det_low",
    "viirs_det_nominal",
    "viirs_det_high",
    "viirs_det_all",
    "viirs_det_nh",
    "viirs_days_active_nh",
    "viirs_streak_max_nh",
    "viirs_frp_active_days",
]

AF_NUMERIC_FLOAT_COLUMNS = [
    "modis_pct_high_conf",
    "modis_frp_sum_daily_max_mw",
    "modis_frp_mean_mw",
    "modis_frp_p95_daily_max_mw",
    "viirs_pct_high_conf",
    "viirs_frp_sum_daily_max_mw",
    "viirs_frp_mean_mw",
    "viirs_frp_p95_daily_max_mw",
]


# =============================================================================
# DATA STRUCTURES
# =============================================================================


@dataclass(frozen=True)
class PathsConfig:
    repo_root: Path
    unit_universe_path: Path
    af_root: Path
    ba2001_root: Path
    ba2012_root: Path
    output_dir: Path
    profile_id: str = "c3"
    profile_contract: Mapping[str, Any] | None = None
    config_path: Path | None = None
    source_lock_path: Path | None = None
    source_lock_entries: tuple[Mapping[str, Any], ...] = ()
    bundle_manifest_path: Path | None = None
    bundle_handoff_path: Path | None = None
    admission_verified: bool = False
    config_sha256: str | None = None


@dataclass(frozen=True)
class FamilySpec:
    family_name: str
    level: str
    source_kind: str
    required_columns: Sequence[str]
    support_start_yyyymm: int
    support_end_yyyymm: int
    root_dir: Path
    filename_required_token: str
    forbidden_filename_tokens: Sequence[str]
    source_present_column: str


@dataclass
class LoadedFamily:
    spec: FamilySpec
    files: list[Path]
    data: pd.DataFrame
    run_ids: list[str]
    schema_version: str
    file_inventory_rows: list[dict[str, Any]]
    qa_sidecars: list[pd.DataFrame] | None = None


# =============================================================================
# EXCEPTIONS AND LOW-LEVEL HELPERS
# =============================================================================


class ValidationError(RuntimeError):
    """Raised when a governed merger contract is violated."""


DATA_ACCESS_DOC_REL = "docs/data_access.md"
ROOT_RUNBOOK_REL = "README.md"


def fail(message: str) -> None:
    """Raise one consistent validation exception for all contract breaches."""
    raise ValidationError(message)


def merge_missing_input_message(*, label: str, detail: str, access_hint: str) -> str:
    return (
        f"Missing required Stage 3 input `{label}`: {detail}. "
        f"See {DATA_ACCESS_DOC_REL} and {ROOT_RUNBOOK_REL} for {access_hint}. "
        "Required by stage: merge_af_ba_panels.py (Stage 3)."
    )


def stable_json_dumps(payload: Any) -> str:
    """Serialize JSON deterministically so written hashes are stable."""
    return json.dumps(payload, indent=2, sort_keys=True)


def sha256_file(path: Path) -> str:
    """Hash a file with chunked reads so large CSVs remain safe to process."""
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def sha256_text(text: str) -> str:
    """Hash a text payload deterministically."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def relative_to_repo(path: Path, repo_root: Path) -> str:
    """Render repository-relative paths in metadata whenever possible."""
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except Exception:
        return path.resolve().as_posix()


def merge_source_access_hint(source_kind: str) -> str:
    if source_kind in {"modis_af", "viirs_af"}:
        return "Stage 2 RP1 active-fire export regeneration and local staging instructions"
    if source_kind in {"ba2001", "ba2012"}:
        return "GEE burned-area export regeneration and local staging instructions"
    return "input acquisition and local staging instructions"


def ensure_directory(path: Path) -> None:
    """Create output directories deterministically and idempotently."""
    path.mkdir(parents=True, exist_ok=True)


def normalize_text_value(value: Any) -> Any:
    """Normalise string-like values so blank strings and NA compare consistently."""
    if pd.isna(value):
        return pd.NA
    if isinstance(value, str):
        value = value.strip()
        return pd.NA if value == "" else value
    return value


def values_equal_or_both_missing(left: Any, right: Any) -> bool:
    """Treat missing-with-missing as equal for identity-contract comparisons."""
    left_n = normalize_text_value(left)
    right_n = normalize_text_value(right)
    if pd.isna(left_n) and pd.isna(right_n):
        return True
    return left_n == right_n


def read_csv_strict(path: Path) -> pd.DataFrame:
    """
    Read CSVs as strings first.

    This deliberately avoids accidental dtype coercion of key and identity fields
    before schema validation and governed numeric parsing.
    """
    # pandas normally disambiguates duplicate headers before they reach the
    # dataframe; inspect the original header so duplicates cannot be hidden.
    try:
        opener = gzip.open if path.name.lower().endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8-sig", newline="") as handle:
            header = next(csv.reader(handle, strict=True))
        normalized = [column.strip() for column in header]
        if not normalized or any(not name for name in normalized):
            fail(f"CSV has an empty header or column name: {path}")
        if len(set(normalized)) != len(normalized):
            fail(f"CSV has duplicate column names: {path}")
    except ValidationError:
        raise
    except (OSError, UnicodeError, csv.Error, StopIteration) as exc:
        fail(f"Failed to read CSV header {path.as_posix()} :: {exc}")
    try:
        return pd.read_csv(
            path,
            dtype=str,
            keep_default_na=True,
            na_values=["", "NA", "NaN", "nan"],
            compression="infer",
        )
    except Exception as exc:  # pragma: no cover
        fail(f"Failed to read CSV {path.as_posix()} :: {exc}")
    raise AssertionError("Unreachable")


def clean_string_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    """Strip surrounding whitespace from governed string columns."""
    out = df.copy()
    for column in columns:
        if column in out.columns:
            out[column] = out[column].map(lambda x: x.strip() if isinstance(x, str) else x)
    return out


def blank_to_na(series: pd.Series) -> pd.Series:
    """Convert blank strings to missing values for stable comparisons."""
    return series.map(lambda x: pd.NA if isinstance(x, str) and x.strip() == "" else x)


def parse_int_series(series: pd.Series, context: str) -> pd.Series:
    """Parse integer-like series with explicit failure on malformed values."""
    numeric = pd.to_numeric(series, errors="coerce")
    bad_mask = series.notna() & numeric.isna()
    if bad_mask.any():
        bad_values = sorted({str(v) for v in series.loc[bad_mask].head(20).tolist()})
        fail(f"{context}: found non-numeric values where integers were required: {bad_values}")
    non_integer_mask = numeric.notna() & ((numeric % 1) != 0)
    if non_integer_mask.any():
        sample = numeric.loc[non_integer_mask].head(20).tolist()
        fail(f"{context}: found non-integer numeric values where integers were required: {sample}")
    return numeric.astype("Int64")


def parse_float_series(series: pd.Series, context: str) -> pd.Series:
    """Parse numeric series with explicit failure on malformed values."""
    numeric = pd.to_numeric(series, errors="coerce")
    bad_mask = series.notna() & numeric.isna()
    if bad_mask.any():
        bad_values = sorted({str(v) for v in series.loc[bad_mask].head(20).tolist()})
        fail(f"{context}: found non-numeric values where numeric values were required: {bad_values}")
    if (numeric.notna() & ~np.isfinite(numeric)).any():
        fail(f"{context}: nonfinite numeric values are not permitted")
    return numeric.astype("float64")


def require_exact_columns(df: pd.DataFrame, expected_columns: Sequence[str], context: str) -> None:
    """
    Enforce exact column set and exact column order.

    This helper is intentionally strict and is used for final governed outputs
    and any input where exact ordered schema is itself part of the contract.
    """
    actual = list(df.columns)
    expected = list(expected_columns)

    duplicated_columns = pd.Index(actual)[pd.Index(actual).duplicated()].tolist()
    if duplicated_columns:
        fail(f"{context}: duplicate column names detected: {duplicated_columns}")

    missing = [column for column in expected if column not in actual]
    extra = [column for column in actual if column not in expected]

    if actual != expected:
        fail(
            f"{context}: schema mismatch.\n"
            f"Expected ({len(expected)}): {expected}\n"
            f"Actual   ({len(actual)}): {actual}\n"
            f"Missing: {missing}\n"
            f"Extra: {extra}"
        )


def require_columns_and_reorder(
    df: pd.DataFrame,
    expected_columns: Sequence[str],
    context: str,
    *,
    allow_extra: bool = False,
) -> pd.DataFrame:
    """
    Validate that all expected columns are present, reject duplicate column
    names, optionally reject extras, and reorder deterministically to the
    governed internal schema.

    Use this for source ingestion. Do not use it for final output validation,
    where exact ordered schema must still be enforced.
    """
    actual = list(df.columns)
    expected = list(expected_columns)

    duplicated_columns = pd.Index(actual)[pd.Index(actual).duplicated()].tolist()
    if duplicated_columns:
        fail(f"{context}: duplicate column names detected: {duplicated_columns}")

    missing = [column for column in expected if column not in actual]
    extra = [column for column in actual if column not in expected]

    if missing:
        fail(
            f"{context}: missing required columns. "
            f"Missing={missing} Actual={actual}"
        )

    if extra and not allow_extra:
        fail(
            f"{context}: unexpected extra columns detected. "
            f"Extra={extra} Expected={expected} Actual={actual}"
        )

    ordered_columns = expected + (
        [column for column in actual if column not in expected] if allow_extra else []
    )
    return df.loc[:, ordered_columns].copy()


def validate_key_uniqueness(df: pd.DataFrame, key_columns: Sequence[str], context: str) -> None:
    """Fail hard on duplicate governed keys."""
    dup_mask = df.duplicated(subset=list(key_columns), keep=False)
    if dup_mask.any():
        sample = df.loc[dup_mask, list(key_columns)].sort_values(list(key_columns)).head(20)
        fail(
            f"{context}: duplicate key rows detected on {list(key_columns)}. "
            f"Sample:\n{sample.to_string(index=False)}"
        )


def month_range(start_yyyymm: int, end_yyyymm: int) -> pd.DataFrame:
    """
    Build the locked inclusive monthly sequence.

    The final panel window is governed here rather than inherited from source
    files. That makes the balanced-panel design explicit and auditable.
    """
    start_year, start_month = divmod(start_yyyymm, 100)
    end_year, end_month = divmod(end_yyyymm, 100)
    if start_month < 1 or start_month > 12 or end_month < 1 or end_month > 12:
        fail(f"Invalid YYYYMM bounds: {start_yyyymm}, {end_yyyymm}")

    rows: list[dict[str, int]] = []
    year = start_year
    month = start_month
    while year < end_year or (year == end_year and month <= end_month):
        rows.append({"yyyymm": year * 100 + month, "year": year, "month": month})
        if month == 12:
            year += 1
            month = 1
        else:
            month += 1

    if not rows:
        fail("Locked month range produced no months.")
    return pd.DataFrame(rows)


def stable_now_iso() -> str:
    """Return an explicit UTC timestamp for manifest provenance."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def is_csv_like(path: Path) -> bool:
    """Accept .csv and .csv.gz source files only."""
    name = path.name.lower()
    return name.endswith(".csv") or name.endswith(".csv.gz")


def contains_forbidden_token(path: Path, forbidden_tokens: Sequence[str]) -> bool:
    """Check filename-level exclusion tokens used to block wrong-family ingestion."""
    lowered = path.name.lower()
    return any(token.lower() in lowered for token in forbidden_tokens)


def extract_partition_code(path: Path, allowed_partition_codes: Sequence[str]) -> str:
    """
    Extract the expected ACZ partition code from a file name.

    Both AF and BA exports are expected to be partitioned by the canonical ACZ
    code, even for district-level files. This is a strong wrong-folder defence.
    """
    matches: list[str] = []
    for code in allowed_partition_codes:
        pattern = rf"(?:^|[_\-.]){re.escape(code)}(?:[_\-.]|$)"
        if re.search(pattern, path.name, flags=re.IGNORECASE):
            matches.append(code)
    matches = sorted(set(matches))
    if len(matches) != 1:
        fail(
            "Could not deterministically extract exactly one canonical partition "
            f"code from {path.as_posix()}. Allowed codes={list(allowed_partition_codes)} "
            f"matched={matches}"
        )
    return matches[0]


# =============================================================================
# CONFIGURATION AND PATH RESOLUTION
# =============================================================================


def _looks_like_umbrella_repo_root(candidate: Path) -> bool:
    """Return True when *candidate* matches the canonical repository root.

    The repository root contains the Stage 1 geography subproject, the RP1
    project subtree and the root package manifest. Checking those markers avoids
    dependence on the caller's working directory.
    """
    required_markers = ("geo_data_prep", "RP1_Project", "pyproject.toml")
    return all((candidate / marker).exists() for marker in required_markers)


def infer_repo_root(explicit_repo_root: str | None) -> Path:
    """Infer the umbrella repository root from CLI input or script location.

    Resolution order is intentionally explicit and deterministic:

    1. Honour ``--repo-root`` exactly when the caller provides it.
    2. Honour ``GHANA_FIRE_RP1_REPO_ROOT`` when set in the environment.
    3. Walk upward from this script's location and choose the nearest parent
       that matches the audited umbrella-repository markers.
    4. Fall back to the parent of ``RP1_Project`` (the current script layout).

    The marker search is preferred because it verifies the expected repository
    structure before applying defaults.
    """
    if explicit_repo_root is not None:
        return Path(explicit_repo_root).expanduser().resolve()

    env_repo_root = os.environ.get("GHANA_FIRE_RP1_REPO_ROOT")
    if env_repo_root:
        return Path(env_repo_root).expanduser().resolve()

    script_path = Path(__file__).resolve()
    for candidate in script_path.parents:
        if _looks_like_umbrella_repo_root(candidate):
            return candidate.resolve()

    # Canonical layout fallback: this script lives at
    # ``<repository_root>/RP1_Project/merge_af_ba_panels.py``.
    return script_path.parent.parent.resolve()


def discover_unique_af_root(repo_root: Path) -> Path | None:
    """
    Discover a unique `rp1_af_exports` root if the default ghana_full path is absent.

    Discovery is limited deliberately to the RP1 AF export subtree
    under ``RP1_Project/rp1_mv_firms_panels/out/runs``. This prevents the merger
    from accidentally ingesting a similarly named directory elsewhere in the
    umbrella repository.

    The function remains deterministic: it prefers ``ghana_full`` when present
    and fails hard when multiple competing candidates exist without a governed
    default.
    """
    candidates = sorted(
        path.resolve()
        for path in repo_root.glob(DEFAULT_AF_DISCOVERY_GLOB)
        if path.is_dir()
    )
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]

    preferred = repo_root / DEFAULT_AF_ROOT_RELATIVE
    if preferred.resolve() in candidates:
        return preferred.resolve()

    fail(
        "Multiple rp1_af_exports roots were found and no deterministic default "
        f"could be chosen: {[relative_to_repo(path, repo_root) for path in candidates]}"
    )
    raise AssertionError("Unreachable")


def configure_study(study: Mapping[str, Any]) -> None:
    """Bind calendar and actual geography counts; empty settings reset helpers."""
    global START_YYYYMM, END_YYYYMM, VIIRS_SUPPORT_START_YYYYMM, BA2012_SUPPORT_START_YYYYMM, ANALYSIS_OVERLAP_START_YYYYMM, EXPECTED_UNITS
    defaults = {"start_yyyymm": 200101, "end_yyyymm": 202412,
                "viirs_support_start_yyyymm": 201201, "ba2012_support_start_yyyymm": 201201,
                "analysis_overlap_start_yyyymm": 201202, "expected_units": None}
    if not isinstance(study, dict) or set(study).difference(defaults):
        fail("study must contain only temporal bounds and expected_units")
    values = defaults | study
    for key in ('start_yyyymm', 'end_yyyymm', 'viirs_support_start_yyyymm', 'ba2012_support_start_yyyymm', 'analysis_overlap_start_yyyymm'):
        value = values[key]
        if type(value) is not int or value < 100001 or not 1 <= value % 100 <= 12:
            fail('study contains invalid YYYYMM: ' + key)
    if values['start_yyyymm'] > values['end_yyyymm']:
        fail('study start exceeds end')
    for key in ('viirs_support_start_yyyymm', 'ba2012_support_start_yyyymm'):
        if values[key] > values['end_yyyymm']:
            fail('sensor/family start exceeds study end')
    units = values['expected_units']
    if units is None:
        units = {'acz': 0, 'district': 0}
    elif not isinstance(units, dict) or set(units) != {'acz','district'} or any(type(v) is not int or v < 1 for v in units.values()):
        fail('study expected_units must declare positive geography-derived counts')
    START_YYYYMM, END_YYYYMM = values['start_yyyymm'], values['end_yyyymm']
    VIIRS_SUPPORT_START_YYYYMM = max(START_YYYYMM, values['viirs_support_start_yyyymm'])
    BA2012_SUPPORT_START_YYYYMM = max(START_YYYYMM, values['ba2012_support_start_yyyymm'])
    ANALYSIS_OVERLAP_START_YYYYMM = values['analysis_overlap_start_yyyymm'] if 'analysis_overlap_start_yyyymm' in study else None
    if ANALYSIS_OVERLAP_START_YYYYMM is not None and ANALYSIS_OVERLAP_START_YYYYMM > END_YYYYMM:
        fail('Paired analysis starts after the study end')
    EXPECTED_UNITS = dict(units)


def build_paths_config(args: argparse.Namespace) -> PathsConfig:
    """Resolve a c3-only configuration through its verified admitted bundle."""
    repo_root = infer_repo_root(args.repo_root)
    config_path = Path(args.config).expanduser().resolve() if getattr(args,'config',None) else repo_root/'RP1_Project/configs/merge_profiles.json'
    try:
        config_bytes = config_path.read_bytes()
        config = json.loads(config_bytes.decode('utf-8'))
    except (OSError, ValueError) as exc:
        fail(f'Cannot read merger configuration {config_path}: {exc}')
    if config.get('version') != 2 or set(config).difference({'version','default_profile','paths','profiles','study'}):
        fail('Merger configuration must use c3 profile contract version 2')
    profile_id = getattr(args,'profile',None) or config.get('default_profile')
    if profile_id != 'c3' or set(config.get('profiles',{})) != {'c3'}:
        fail('Only the c3 burned-area profile is supported')
    profile = config['profiles']['c3']
    if not isinstance(profile,dict) or any(profile.get(k) != v for k,v in c3.PROFILE.items()):
        fail('c3 profile schema/method/admission policy differs from the implemented contract')
    def resolve(value):
        if not isinstance(value,str) or not value.strip():
            fail('Required c3 path is absent; complete consolidate-ba first')
        p = Path(value).expanduser()
        return (p if p.is_absolute() else repo_root/p).resolve()
    settings = config.get('paths',{})
    if set(settings) != {'unit_universe','af_root','output_root'}:
        fail('Configuration paths must specify unit_universe, af_root and output_root')
    universe = resolve(getattr(args,'unit_universe',None) or settings['unit_universe'])
    try:
        with universe.open(encoding='utf-8-sig',newline='') as stream:
            units = list(csv.DictReader(stream))
    except OSError as exc:
        fail(f'Cannot read selected unit universe: {exc}')
    counts = {level:sum(row.get('level') == level for row in units) for level in SUPPORTED_LEVELS}
    study = dict(config.get('study',{}))
    if 'expected_units' in study and study['expected_units'] != counts:
        fail('Configured unit counts disagree with selected geography')
    study['expected_units'] = counts
    configure_study(study)
    handoff_path = resolve(getattr(args,'ba_handoff',None) or profile.get('bundle_handoff'))
    if handoff_path.name != 'handoff.json' or handoff_path.is_symlink():
        fail('c3 requires the admitted bundle handoff.json')
    from RP1_Project.rp1_ba_consolidator.handoff import verify_handoff
    try:
        admitted = verify_handoff(handoff_path.parent, unit_universe=universe, profile_id='c3', study=study)
    except (OSError, ValueError) as exc:
        fail(f'c3 bundle admission verification failed: {exc}')
    roots = {key:Path(admitted[key]).resolve() for key in ('ba2001_root','ba2012_root','source_lock')}
    for key in ('ba2001_root','ba2012_root'):
        override = getattr(args,key,None)
        if override and resolve(override) != roots[key]:
            fail('BA root overrides cannot bypass admitted c3 sources')
    lock = json.loads(roots['source_lock'].read_text(encoding='utf-8'))
    output = resolve(args.output_dir) if getattr(args,'output_dir',None) else resolve(settings['output_root'])/'c3'
    return PathsConfig(repo_root=repo_root,unit_universe_path=universe,
        af_root=resolve(getattr(args,'af_root',None) or settings['af_root']),
        ba2001_root=roots['ba2001_root'],ba2012_root=roots['ba2012_root'],output_dir=output,
        profile_id='c3',profile_contract=dict(c3.PROFILE),config_path=config_path,
        source_lock_path=roots['source_lock'],source_lock_entries=tuple(lock['files']),
        bundle_manifest_path=handoff_path.parent/'manifest.json',bundle_handoff_path=handoff_path,
        admission_verified=True, config_sha256=hashlib.sha256(config_bytes).hexdigest())


# =============================================================================
# CANONICAL GEOGRAPHY
# =============================================================================


def load_unit_universe(paths: PathsConfig) -> pd.DataFrame:
    """
    Load and validate the Stage 1 canonical geography contract.

    The merger uses this table as the sole identity authority. Source files are
    checked against it, but they never override it.
    """
    path = paths.unit_universe_path
    if not path.exists():
        fail(
            merge_missing_input_message(
                label="unit_universe",
                detail=relative_to_repo(path, paths.repo_root),
                access_hint="Stage 1 regeneration and local staging instructions",
            )
        )

    expected_columns = [
        "unit_type",
        "level",
        "unit_id",
        "unit_code",
        "unit_name",
        "parent_level",
        "parent_id",
        "parent_code",
        "parent_name",
        "area_sqkm",
    ]
    unit_universe = read_csv_strict(path)
    unit_universe = require_columns_and_reorder(
        unit_universe,
        expected_columns,
        "unit_universe",
        allow_extra=False,
    )
    unit_universe = clean_string_columns(unit_universe, unit_universe.columns)

    for column in ["parent_level", "parent_id", "parent_code", "parent_name"]:
        unit_universe[column] = blank_to_na(unit_universe[column])

    observed_levels = set(unit_universe["level"].dropna().tolist())
    expected_levels = set(SUPPORTED_LEVELS)
    if observed_levels != expected_levels:
        fail(f"unit_universe: expected levels {sorted(expected_levels)}, got {sorted(observed_levels)}")

    validate_key_uniqueness(unit_universe, ["level", "unit_id"], "unit_universe")

    counts = unit_universe.groupby("level")["unit_id"].nunique().to_dict()
    if counts.get("acz") != EXPECTED_UNITS["acz"]:
        fail(f"unit_universe: expected {EXPECTED_UNITS['acz']} ACZ rows, got {counts.get('acz')}")
    if counts.get("district") != EXPECTED_UNITS["district"]:
        fail(f"unit_universe: expected {EXPECTED_UNITS['district']} district rows, got {counts.get('district')}")

    acz_mask = unit_universe["level"] == "acz"
    for column in ["parent_level", "parent_id", "parent_code", "parent_name"]:
        bad_mask = acz_mask & unit_universe[column].notna()
        if bad_mask.any():
            sample = unit_universe.loc[bad_mask, ["unit_id", column]].head(10)
            fail(f"unit_universe: ACZ rows must have missing {column}. Sample:\n{sample.to_string(index=False)}")

    district_mask = unit_universe["level"] == "district"
    for column in ["parent_level", "parent_id", "parent_code", "parent_name"]:
        bad_mask = district_mask & unit_universe[column].isna()
        if bad_mask.any():
            sample = unit_universe.loc[bad_mask, ["unit_id", column]].head(10)
            fail(
                f"unit_universe: district rows must have populated {column}. "
                f"Sample:\n{sample.to_string(index=False)}"
            )

    return unit_universe[IDENTITY_COLUMNS].copy()


def canonical_partition_codes(unit_universe: pd.DataFrame) -> list[str]:
    """Derive the expected ACZ partition codes from the authoritative geography."""
    codes = (
        unit_universe.loc[unit_universe["level"] == "acz", "unit_code"]
        .dropna()
        .map(str)
        .map(str.strip)
        .tolist()
    )
    codes = sorted(set(codes))
    if len(codes) != EXPECTED_UNITS["acz"]:
        fail(f"Expected {EXPECTED_UNITS['acz']} canonical ACZ partition codes, got {codes}")
    return codes


def expected_panel_rows(level: str) -> int:
    if level not in SUPPORTED_LEVELS:
        fail('Unsupported panel level: '+str(level))
    if EXPECTED_UNITS[level] < 1:
        fail('Expected unit counts are not bound to selected geography')
    return len(month_range(START_YYYYMM,END_YYYYMM))*EXPECTED_UNITS[level]


def build_canonical_spine(unit_universe: pd.DataFrame, level: str) -> pd.DataFrame:
    """
    Build the complete balanced spine for one level.

    This is the heart of the merger design: all sources are left-joined to this
    governed unit-month grid rather than the other way around.
    """
    level_units = unit_universe.loc[unit_universe["level"] == level, IDENTITY_COLUMNS].copy()
    if level_units.empty:
        fail(f"No canonical units found for level={level}")

    months = month_range(START_YYYYMM, END_YYYYMM)
    level_units["_tmp_key"] = 1
    months["_tmp_key"] = 1
    spine = level_units.merge(months, on="_tmp_key", how="inner").drop(columns=["_tmp_key"])

    validate_key_uniqueness(spine, MERGE_KEY, f"canonical spine :: {level}")

    expected_rows = expected_panel_rows(level)
    if len(spine) != expected_rows:
        fail(f"canonical spine :: {level}: expected {expected_rows} rows, got {len(spine)}")

    return spine.sort_values(MERGE_KEY).reset_index(drop=True)


# =============================================================================
# SOURCE FAMILY DISCOVERY AND LOADING
# =============================================================================


def build_family_specs(paths: PathsConfig) -> list[FamilySpec]:
    """Construct the eight governed source families used by the merger."""
    reject_tokens = ("_ext", "_qa", "qa_by_acz", "drop_log", "manifest", "summary", "inventory")
    return [
        FamilySpec(
            family_name="modis_af_acz_base",
            level="acz",
            source_kind="modis_af",
            required_columns=MODIS_AF_REQUIRED_COLUMNS,
            support_start_yyyymm=START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.af_root / "acz" / "modis",
            filename_required_token="rp1_af_acz_",
            forbidden_filename_tokens=reject_tokens,
            source_present_column="af_modis_source_present",
        ),
        FamilySpec(
            family_name="viirs_af_acz_base",
            level="acz",
            source_kind="viirs_af",
            required_columns=VIIRS_AF_REQUIRED_COLUMNS,
            support_start_yyyymm=VIIRS_SUPPORT_START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.af_root / "acz" / "viirs",
            filename_required_token="rp1_af_acz_",
            forbidden_filename_tokens=reject_tokens,
            source_present_column="af_viirs_source_present",
        ),
        FamilySpec(
            family_name="modis_af_district_base",
            level="district",
            source_kind="modis_af",
            required_columns=MODIS_AF_REQUIRED_COLUMNS,
            support_start_yyyymm=START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.af_root / "district" / "modis",
            filename_required_token="rp1_af_district_",
            forbidden_filename_tokens=reject_tokens,
            source_present_column="af_modis_source_present",
        ),
        FamilySpec(
            family_name="viirs_af_district_base",
            level="district",
            source_kind="viirs_af",
            required_columns=VIIRS_AF_REQUIRED_COLUMNS,
            support_start_yyyymm=VIIRS_SUPPORT_START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.af_root / "district" / "viirs",
            filename_required_token="rp1_af_district_",
            forbidden_filename_tokens=reject_tokens,
            source_present_column="af_viirs_source_present",
        ),
        FamilySpec(
            family_name="ba2001_acz_base",
            level="acz",
            source_kind="ba2001",
            required_columns=c3.FIELDS,
            support_start_yyyymm=START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.ba2001_root,
            filename_required_token="rp1_ba_acz_",
            forbidden_filename_tokens=(),
            source_present_column="ba2001_source_present",
        ),
        FamilySpec(
            family_name="ba2012_acz_base",
            level="acz",
            source_kind="ba2012",
            required_columns=c3.FIELDS,
            support_start_yyyymm=BA2012_SUPPORT_START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.ba2012_root,
            filename_required_token="rp1_ba_acz_",
            forbidden_filename_tokens=(),
            source_present_column="ba2012_source_present",
        ),
        FamilySpec(
            family_name="ba2001_district_base",
            level="district",
            source_kind="ba2001",
            required_columns=c3.FIELDS,
            support_start_yyyymm=START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.ba2001_root,
            filename_required_token="rp1_ba_district_",
            forbidden_filename_tokens=(),
            source_present_column="ba2001_source_present",
        ),
        FamilySpec(
            family_name="ba2012_district_base",
            level="district",
            source_kind="ba2012",
            required_columns=c3.FIELDS,
            support_start_yyyymm=BA2012_SUPPORT_START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.ba2012_root,
            filename_required_token="rp1_ba_district_",
            forbidden_filename_tokens=(),
            source_present_column="ba2012_source_present",
        ),
    ]


def discover_family_files(spec: FamilySpec, partition_codes: Sequence[str], repo_root: Path) -> list[Path]:
    """
    Discover exactly one governed base file per canonical partition.

    The discovery logic is intentionally strict because wrong-folder ingestion is
    a major risk in this project. The rules enforced here are:

    - only CSV / CSV.GZ files are considered
    - filenames must contain the expected level-specific family token
    - forbidden substrings reject `_ext`, QA, manifests, summaries, and logs
    - each file must encode exactly one canonical ACZ partition code
    - exactly one file must exist per canonical partition code
    """
    if not spec.root_dir.exists():
        fail(
            merge_missing_input_message(
                label=spec.family_name,
                detail=relative_to_repo(spec.root_dir, repo_root),
                access_hint=merge_source_access_hint(spec.source_kind),
            )
        )
    if not spec.root_dir.is_dir():
        fail(f"{spec.family_name}: root path is not a directory: {relative_to_repo(spec.root_dir, repo_root)}")

    candidate_files = sorted(
        path.resolve()
        for path in spec.root_dir.rglob("*")
        if path.is_file()
        and is_csv_like(path)
        and spec.filename_required_token.lower() in path.name.lower()
        and not contains_forbidden_token(path, spec.forbidden_filename_tokens)
    )
    if not candidate_files:
        fail(
            merge_missing_input_message(
                label=spec.family_name,
                detail=f"no governed base files found under {relative_to_repo(spec.root_dir, repo_root)}",
                access_hint=merge_source_access_hint(spec.source_kind),
            )
        )

    partition_to_file: dict[str, Path] = {}
    for path in candidate_files:
        partition_code = extract_partition_code(path, partition_codes)
        existing = partition_to_file.get(partition_code)
        if existing is not None:
            fail(
                f"{spec.family_name}: multiple candidate files matched partition "
                f"{partition_code}: {relative_to_repo(existing, repo_root)} and "
                f"{relative_to_repo(path, repo_root)}"
            )
        partition_to_file[partition_code] = path

    observed_partitions = sorted(partition_to_file)
    missing = [code for code in partition_codes if code not in partition_to_file]
    extra = [code for code in observed_partitions if code not in partition_codes]
    if missing or extra:
        fail(
            f"{spec.family_name}: expected exactly one file per canonical partition. "
            f"Expected={list(partition_codes)} Observed={observed_partitions} "
            f"Missing={missing} Extra={extra}"
        )

    return [partition_to_file[code] for code in partition_codes]


def validate_time_columns(df: pd.DataFrame, spec: FamilySpec, context: str) -> pd.DataFrame:
    """Validate and coerce governed time columns."""
    out = df.copy()
    out["yyyymm"] = parse_int_series(out["yyyymm"], f"{context} :: yyyymm")
    out["year"] = parse_int_series(out["year"], f"{context} :: year")
    out["month"] = parse_int_series(out["month"], f"{context} :: month")

    if out[["yyyymm", "year", "month"]].isna().any().any():
        fail(f"{context}: time columns must not contain missing values")

    y_from_yyyymm = (out["yyyymm"] // 100).astype("Int64")
    m_from_yyyymm = (out["yyyymm"] % 100).astype("Int64")
    bad_month_mask = ~m_from_yyyymm.between(1, 12)
    if bad_month_mask.any():
        sample = out.loc[bad_month_mask, ["yyyymm"]].head(20)
        fail(f"{context}: invalid YYYYMM values detected. Sample:\n{sample.to_string(index=False)}")

    inconsistent_mask = (out["year"] != y_from_yyyymm) | (out["month"] != m_from_yyyymm)
    if inconsistent_mask.any():
        sample = out.loc[inconsistent_mask, ["yyyymm", "year", "month"]].head(20)
        fail(f"{context}: inconsistent yyyymm/year/month fields. Sample:\n{sample.to_string(index=False)}")

    outside_window = (out["yyyymm"] < spec.support_start_yyyymm) | (out["yyyymm"] > spec.support_end_yyyymm)
    if outside_window.any():
        sample = out.loc[outside_window, ["unit_id", "yyyymm"]].head(20)
        fail(
            f"{context}: rows fall outside family support window "
            f"{spec.support_start_yyyymm}-{spec.support_end_yyyymm}. "
            f"Sample:\n{sample.to_string(index=False)}"
        )

    return out


def validate_source_identity_against_canonical(
    df: pd.DataFrame,
    canonical_units: pd.DataFrame,
    spec: FamilySpec,
    context: str,
) -> None:
    """
    Ensure source identity matches the Stage 1 geography contract exactly.

    The final output always uses canonical identity from the spine. This check is
    still vital because it blocks wrong-level files and stale exports whose
    labels no longer match the governed geography contract.
    """
    source_identity = df[IDENTITY_COLUMNS].drop_duplicates().copy()
    merged = source_identity.merge(
        canonical_units,
        on=["level", "unit_id"],
        how="left",
        suffixes=("_src", "_canon"),
        indicator=True,
    )

    if (merged["_merge"] != "both").any():
        sample = merged.loc[merged["_merge"] != "both", ["level", "unit_id"]].head(20)
        fail(f"{context}: source contains non-canonical units. Sample:\n{sample.to_string(index=False)}")

    for column in ["unit_code", "unit_name", "parent_level", "parent_id", "parent_code", "parent_name"]:
        src_column = f"{column}_src"
        canon_column = f"{column}_canon"
        mismatch_mask = ~merged.apply(
            lambda row: values_equal_or_both_missing(row[src_column], row[canon_column]),
            axis=1,
        )
        if mismatch_mask.any():
            sample = merged.loc[mismatch_mask, ["level", "unit_id", src_column, canon_column]].head(20)
            fail(f"{context}: identity mismatch in {column}. Sample:\n{sample.to_string(index=False)}")

    bad_level_mask = df["level"].isna() | (df["level"].map(str) != spec.level)
    if bad_level_mask.any():
        sample = df.loc[bad_level_mask, ["level", "unit_id"]].head(20)
        fail(f"{context}: wrong level rows detected for family {spec.family_name}. Sample:\n{sample.to_string(index=False)}")


def validate_file_partition(df: pd.DataFrame, level: str, expected_code: str, context: str) -> None:
    """Require each row to belong to the partition named in its source file."""
    if level not in SUPPORTED_LEVELS:
        fail(f"{context}: unsupported level {level}")
    field = "unit_code" if level == "acz" else "parent_code"
    matches = df[field].notna() & df[field].astype("string").eq(expected_code).fillna(False)
    if not matches.all():
        sample = df.loc[~matches, ["unit_id", "yyyymm", field]].head(20)
        fail(f"{context}: file partition {expected_code} does not match row {field}. Sample:\n{sample.to_string(index=False)}")


def verify_locked_file(path: Path, entry: Mapping[str, Any], context: str) -> None:
    """Reject a different file or a modified file even if its schema matches."""
    if path.name != entry["filename"] or not path.is_file():
        fail(f"{context}: input file does not match the reviewed source lock")
    if sha256_file(path) != entry["sha256"]:
        fail(f"{context}: input SHA-256 differs from the reviewed source lock")


def validate_af_content(df: pd.DataFrame, sensor_prefix: str, context: str) -> pd.DataFrame:
    """Validate AF arithmetic, non-negativity, and bounded percentages."""
    out = df.copy()

    int_columns = [
        f"{sensor_prefix}_det_low",
        f"{sensor_prefix}_det_nominal",
        f"{sensor_prefix}_det_high",
        f"{sensor_prefix}_det_all",
        f"{sensor_prefix}_det_nh",
        f"{sensor_prefix}_days_active_nh",
        f"{sensor_prefix}_streak_max_nh",
        f"{sensor_prefix}_frp_active_days",
    ]
    float_columns = [
        f"{sensor_prefix}_pct_high_conf",
        f"{sensor_prefix}_frp_sum_daily_max_mw",
        f"{sensor_prefix}_frp_mean_mw",
        f"{sensor_prefix}_frp_p95_daily_max_mw",
    ]

    for column in int_columns:
        out[column] = parse_int_series(out[column], f"{context} :: {column}")
    for column in float_columns:
        out[column] = parse_float_series(out[column], f"{context} :: {column}")

    for column in int_columns + float_columns:
        bad_mask = out[column].notna() & (out[column] < 0)
        if bad_mask.any():
            sample = out.loc[bad_mask, ["unit_id", "yyyymm", column]].head(20)
            fail(f"{context}: negative values detected in {column}. Sample:\n{sample.to_string(index=False)}")

    pct_column = f"{sensor_prefix}_pct_high_conf"
    pct_bad = out[pct_column].notna() & ~out[pct_column].between(0.0, 100.0)
    if pct_bad.any():
        sample = out.loc[pct_bad, ["unit_id", "yyyymm", pct_column]].head(20)
        fail(f"{context}: {pct_column} must lie within [0, 100]. Sample:\n{sample.to_string(index=False)}")

    det_all_expected = (
        out[f"{sensor_prefix}_det_low"]
        + out[f"{sensor_prefix}_det_nominal"]
        + out[f"{sensor_prefix}_det_high"]
    )
    det_all_bad = out[f"{sensor_prefix}_det_all"] != det_all_expected
    if det_all_bad.any():
        sample = out.loc[
            det_all_bad,
            [
                "unit_id",
                "yyyymm",
                f"{sensor_prefix}_det_low",
                f"{sensor_prefix}_det_nominal",
                f"{sensor_prefix}_det_high",
                f"{sensor_prefix}_det_all",
            ],
        ].head(20)
        fail(
            f"{context}: {sensor_prefix}_det_all must equal low+nominal+high. "
            f"Sample:\n{sample.to_string(index=False)}"
        )

    det_nh_expected = out[f"{sensor_prefix}_det_nominal"] + out[f"{sensor_prefix}_det_high"]
    det_nh_bad = out[f"{sensor_prefix}_det_nh"] != det_nh_expected
    if det_nh_bad.any():
        sample = out.loc[
            det_nh_bad,
            [
                "unit_id",
                "yyyymm",
                f"{sensor_prefix}_det_nominal",
                f"{sensor_prefix}_det_high",
                f"{sensor_prefix}_det_nh",
            ],
        ].head(20)
        fail(
            f"{context}: {sensor_prefix}_det_nh must equal nominal+high. "
            f"Sample:\n{sample.to_string(index=False)}"
        )

    return out


def validate_ba_content(df: pd.DataFrame, context: str) -> pd.DataFrame:
    """Validate all c3 source guards, then type the analytical projection."""
    c3.validate_header(df.columns)
    for record in df.to_dict('records'):
        normalized = {k:('' if pd.isna(v) else str(v)) for k,v in record.items()}
        try:
            c3.validate_row(normalized, allow_technical=True,
                observation_windows=c3.observation_windows(START_YYYYMM//100, END_YYYYMM//100))
        except ValueError as exc:
            fail(f'{context}: {exc}')
    out = df.loc[:,BA_REQUIRED_COLUMNS].copy()
    for name in c3.FIELDS[:13]:
        if name in out:
            out[name] = blank_to_na(out[name])
    for name in ('yyyymm','year','month','modis_burned_pixel_count','modis_ba_any','modis_zero_union_den_flag','modis_zero_annual_den_flag'):
        out[name] = parse_int_series(blank_to_na(out[name]), f'{context} :: {name}')
    for name in BA_ANALYTICAL_COLUMNS:
        if name not in ('modis_burned_pixel_count','modis_ba_any','modis_zero_union_den_flag','modis_zero_annual_den_flag'):
            out[name] = parse_float_series(blank_to_na(out[name]), f'{context} :: {name}')
    return out


def validate_file_lineage(df: pd.DataFrame, context: str) -> tuple[str, str]:
    """Require each source file to declare exactly one non-null run_id and schema_version."""
    if df[["run_id", "schema_version"]].isna().any().any():
        fail(f"{context}: run_id and schema_version must be populated on every row")
    run_ids = sorted({str(v).strip() for v in df["run_id"].dropna().tolist() if str(v).strip()})
    schema_versions = sorted({str(v).strip() for v in df["schema_version"].dropna().tolist() if str(v).strip()})
    if len(run_ids) != 1:
        fail(f"{context}: expected exactly one non-null run_id in the file, got {run_ids}")
    if len(schema_versions) != 1:
        fail(f"{context}: expected exactly one non-null schema_version in the file, got {schema_versions}")
    return run_ids[0], schema_versions[0]


QA_FIELDS = tuple(c3.FIELDS)


def apply_ba_profile(raw, typed=None, ext=None, profile=None, family=None, context='c3'):
    """Project c3 primary values unchanged and retain the full source evidence."""
    if ext is not None:
        fail(f'{context}: c3 has one extended source, not paired base/QA files')
    if not isinstance(profile,Mapping) or any(profile.get(k) != v for k,v in c3.PROFILE.items()):
        fail(f'{context}: only the c3 admission policy is implemented')
    if family not in ('ba2001','ba2012'):
        fail(f'{context}: unknown c3 family')
    projected = validate_ba_content(raw,context)
    # Optional EE transport metadata remains in the immutable original file;
    # the canonical evidence schema contains the 69 documented source fields.
    evidence_fields = list(c3.FIELDS) + (["ba_annual_lc_source_index"] if "ba_annual_lc_source_index" in raw else [])
    evidence = raw.loc[:, evidence_fields].copy()
    if not evidence['ba_domain'].eq(family.upper()).all():
        fail(f'{context}: c3 domain/family mismatch')
    evidence['family'] = family
    return projected,evidence


def expected_supported_keys(spine: pd.DataFrame, support_start_yyyymm: int, support_end_yyyymm: int) -> pd.DataFrame:
    """Return the expected canonical key set for one family support window."""
    mask = spine["yyyymm"].between(support_start_yyyymm, support_end_yyyymm)
    return spine.loc[mask, MERGE_KEY].sort_values(MERGE_KEY).reset_index(drop=True)


def validate_supported_key_coverage(df: pd.DataFrame, expected_keys: pd.DataFrame, context: str) -> None:
    """
    Ensure each supported family is a complete balanced panel over its own window.

    This catches silent missing rows, stray extra rows, wrong partitions, and
    incomplete exports before they reach the merger stage.
    """
    actual_keys = df[MERGE_KEY].drop_duplicates().sort_values(MERGE_KEY).reset_index(drop=True)
    merged = expected_keys.merge(actual_keys, on=MERGE_KEY, how="outer", indicator=True)
    missing_mask = merged["_merge"] == "left_only"
    extra_mask = merged["_merge"] == "right_only"
    if missing_mask.any() or extra_mask.any():
        missing_sample = merged.loc[missing_mask, MERGE_KEY].head(10)
        extra_sample = merged.loc[extra_mask, MERGE_KEY].head(10)
        fail(
            f"{context}: supported key coverage mismatch. "
            f"Expected_rows={len(expected_keys)} Actual_rows={len(actual_keys)} "
            f"Missing_rows={int(missing_mask.sum())} Extra_rows={int(extra_mask.sum())}\n"
            f"Missing sample:\n{missing_sample.to_string(index=False)}\n"
            f"Extra sample:\n{extra_sample.to_string(index=False)}"
        )


def _load_af_family(spec,unit_universe,spine,partition_codes,paths):
    """Retain governed AF discovery, values and method population checks."""
    if spec.source_kind not in ('modis_af','viirs_af'):
        fail('AF loader cannot consume BA sources')
    files=discover_family_files(spec,partition_codes,paths.repo_root)
    frames,inventory,versions,run_ids=[],[],set(),set()
    canonical=unit_universe.loc[unit_universe.level.eq(spec.level),IDENTITY_COLUMNS].copy()
    for path in files:
        context=f'{spec.family_name} :: {relative_to_repo(path,paths.repo_root)}'
        raw=require_columns_and_reorder(read_csv_strict(path),spec.required_columns,context,allow_extra=False)
        raw=clean_string_columns(raw,raw.columns)
        for column in ('parent_level','parent_id','parent_code','parent_name'):
            raw[column]=blank_to_na(raw[column])
        run_id,version=validate_file_lineage(raw,context)
        versions.add(version);run_ids.add(run_id)
        raw=validate_time_columns(raw,spec,context)
        validate_key_uniqueness(raw,MERGE_KEY,context)
        validate_source_identity_against_canonical(raw,canonical,spec,context)
        partition=extract_partition_code(path,partition_codes)
        validate_file_partition(raw,spec.level,partition,context)
        typed=validate_af_content(raw,'modis' if spec.source_kind=='modis_af' else 'viirs',context)
        frames.append(typed)
        inventory.append({'family_name':spec.family_name,'source_kind':spec.source_kind,'level':spec.level,
            'partition_code':partition,'origin_path':relative_to_repo(path,paths.repo_root),
            'staged_path':relative_to_repo(path,paths.repo_root),'sha256':sha256_file(path),
            'row_count':len(typed),'yyyymm_min':int(typed.yyyymm.min()),'yyyymm_max':int(typed.yyyymm.max()),
            'run_id':run_id,'schema_version':version})
    if len(versions)!=1:
        fail(f'{spec.family_name}: inconsistent source schemas')
    data=pd.concat(frames,ignore_index=True)
    validate_key_uniqueness(data,MERGE_KEY,spec.family_name)
    validate_supported_key_coverage(data,expected_supported_keys(spine,spec.support_start_yyyymm,spec.support_end_yyyymm),spec.family_name)
    return LoadedFamily(spec,files,data.sort_values(MERGE_KEY).reset_index(drop=True),sorted(run_ids),next(iter(versions)),inventory,[])



# =============================================================================
# MERGE PREPARATION HELPERS
# =============================================================================


def safe_left_merge(left: pd.DataFrame, right: pd.DataFrame, context: str) -> pd.DataFrame:
    """Perform an audited one-to-one left merge on the governed key."""
    validate_key_uniqueness(left, MERGE_KEY, f"{context} :: left")
    validate_key_uniqueness(right, MERGE_KEY, f"{context} :: right")
    try:
        merged = left.merge(right, on=MERGE_KEY, how="left", validate="one_to_one")
    except Exception as exc:  # pragma: no cover
        fail(f"{context}: merge failed :: {exc}")

    duplicated_columns = pd.Index(merged.columns)[pd.Index(merged.columns).duplicated()].tolist()
    if duplicated_columns:
        fail(f"{context}: duplicate column names detected after merge: {duplicated_columns}")

    validate_key_uniqueness(merged, MERGE_KEY, f"{context} :: merged")
    return merged


def prepare_af_merge_frame(family: LoadedFamily) -> pd.DataFrame:
    """Select AF analytical columns and attach a row-level source-present marker."""
    analytical_columns = MODIS_AF_ANALYTICAL_COLUMNS if family.spec.source_kind == "modis_af" else VIIRS_AF_ANALYTICAL_COLUMNS
    frame = family.data[MERGE_KEY + analytical_columns].copy()
    frame[family.spec.source_present_column] = pd.Series(1, index=frame.index, dtype="Int64")
    return frame


def prepare_ba_merge_frame(family: LoadedFamily) -> pd.DataFrame:
    """
    Rename BA columns to family-specific final names before merge.

    This is a critical scientific safeguard. Renaming before the merge prevents
    silent overwriting and makes it impossible for the two BA families to collapse
    accidentally into one unsuffixed analytical block.
    """
    rename_map = BA_RENAME_2001 if family.spec.source_kind == "ba2001" else BA_RENAME_2012
    frame = family.data[MERGE_KEY + BA_ANALYTICAL_COLUMNS].copy().rename(columns=rename_map)
    frame[family.spec.source_present_column] = pd.Series(1, index=frame.index, dtype="Int64")
    return frame


def safe_divide(numerator: pd.Series, denominator: pd.Series, *, multiplier: float = 1.0) -> pd.Series:
    """
    Protected division used for all derived rates and shares.

    Missing numerators, missing denominators, zero denominators, and negative
    denominators all yield missing rather than unsafe finite values.
    """
    result = pd.Series(np.nan, index=numerator.index, dtype="float64")
    valid = numerator.notna() & denominator.notna() & (denominator > 0)
    result.loc[valid] = multiplier * numerator.loc[valid].astype(float) / denominator.loc[valid].astype(float)
    return result


def binary_from_positive(series: pd.Series, support_mask: pd.Series | None = None) -> pd.Series:
    """Convert positive numeric values to 1/0 while preserving structural missingness."""
    result = pd.Series(pd.NA, index=series.index, dtype="Int64")
    valid = series.notna()
    if support_mask is not None:
        valid &= support_mask
    result.loc[valid] = (series.loc[valid] > 0).astype("Int64")
    return result


def binary_flag_from_inputs(mask: pd.Series, required_inputs: Sequence[pd.Series]) -> pd.Series:
    """Create concordance flags that are missing whenever any required input is missing."""
    result = pd.Series(pd.NA, index=mask.index, dtype="Int64")
    valid = pd.Series(True, index=mask.index)
    for series in required_inputs:
        valid &= series.notna()
    result.loc[valid] = mask.loc[valid].astype("Int64")
    return result


def join_sparse_notes(rows: list[str]) -> str:
    """Join row-level audit notes into a sparse deterministic string."""
    cleaned = [item for item in rows if item]
    return ";".join(cleaned)


def debug_final_schema(df: pd.DataFrame, expected_columns: Sequence[str], context: str) -> None:
    """
    Strict diagnostic helper for final-output schema debugging.

    This does not relax the contract. It provides a clearer failure message for:
    - duplicate column labels
    - missing columns
    - extra columns
    - same-set but wrong-order mismatches
    """
    actual = list(df.columns)
    expected = list(expected_columns)

    duplicated_columns = pd.Index(actual)[pd.Index(actual).duplicated()].tolist()
    if duplicated_columns:
        fail(f"{context}: duplicate final column names detected: {duplicated_columns}")

    missing = [column for column in expected if column not in actual]
    extra = [column for column in actual if column not in expected]

    if missing or extra:
        fail(
            f"{context}: final schema set mismatch. "
            f"Missing={missing} Extra={extra}\n"
            f"Expected={expected}\n"
            f"Actual={actual}"
        )

    if actual != expected:
        first_diff_idx = next(
            idx for idx, (act, exp) in enumerate(zip(actual, expected))
            if act != exp
        )
        fail(
            f"{context}: final schema order mismatch at position {first_diff_idx}. "
            f"Expected '{expected[first_diff_idx]}' but got '{actual[first_diff_idx]}'.\n"
            f"Expected={expected}\n"
            f"Actual={actual}"
        )


# =============================================================================
# DERIVATIONS
# =============================================================================


def derive_final_fields(panel: pd.DataFrame, merge_run_id: str) -> pd.DataFrame:
    """
    Compute the final governed 111-column schema.

    All derivations are computed after every base family has been joined to the
    canonical spine. That ordering matters because many downstream variables are
    family-specific and must use the already-renamed BA columns.
    """
    out = panel.copy()

    # The final output run metadata describes the merger product itself, not any
    # individual source family.
    out["run_id"] = merge_run_id
    out["schema_version"] = MERGE_SCHEMA_VERSION

    # Support windows are encoded explicitly so downstream analysis can separate
    # unsupported time from observed structural zero.
    viirs_supported = out["yyyymm"] >= VIIRS_SUPPORT_START_YYYYMM
    ba2012_supported = out["yyyymm"] >= BA2012_SUPPORT_START_YYYYMM
    out["viirs_supported_flag"] = viirs_supported.astype("Int64")
    out["ba2012_supported_flag"] = ba2012_supported.astype("Int64")
    out["full_overlap_supported_flag"] = (viirs_supported & ba2012_supported).astype("Int64")
    out["viirs_structural_missing_flag"] = (~viirs_supported).astype("Int64")
    out["ba2012_structural_missing_flag"] = (~ba2012_supported).astype("Int64")

    # The science-facing AF primary count is locked to nominal+high.
    out["modis_det_primary"] = out["modis_det_nh"].astype("Int64")
    out["viirs_det_primary"] = out["viirs_det_nh"].astype("Int64")
    out["modis_det_nh_share_of_all"] = safe_divide(out["modis_det_nh"], out["modis_det_all"])
    out["viirs_det_nh_share_of_all"] = safe_divide(out["viirs_det_nh"], out["viirs_det_all"])
    out["modis_det_primary_any"] = binary_from_positive(out["modis_det_primary"])
    out["viirs_det_primary_any"] = binary_from_positive(out["viirs_det_primary"], support_mask=viirs_supported)

    # BA area-rate derivations are always family-matched. Mixing BA families would
    # be scientifically indefensible because the family-specific support mask
    # changes the realised BA numerator itself.
    out["modis_ba_km2_per100km2_union_ba2001"] = safe_divide(
        out["modis_ba_km2_ba2001"], out["modis_burnable_km2_union_ba2001"], multiplier=100.0
    )
    out["modis_ba_km2_per100km2_annual_ba2001"] = safe_divide(
        out["modis_ba_km2_ba2001"], out["modis_burnable_km2_annual_ba2001"], multiplier=100.0
    )
    out["modis_ba_km2_per100km2_union_ba2012"] = safe_divide(
        out["modis_ba_km2_ba2012"], out["modis_burnable_km2_union_ba2012"], multiplier=100.0
    )
    out["modis_ba_km2_per100km2_annual_ba2012"] = safe_divide(
        out["modis_ba_km2_ba2012"], out["modis_burnable_km2_annual_ba2012"], multiplier=100.0
    )

    # AF density derivations.
    out["modis_det_primary_per100km2_burnable_union_ba2001"] = safe_divide(
        out["modis_det_primary"], out["modis_burnable_km2_union_ba2001"], multiplier=100.0
    )
    out["modis_det_primary_per100km2_burnable_annual_ba2001"] = safe_divide(
        out["modis_det_primary"], out["modis_burnable_km2_annual_ba2001"], multiplier=100.0
    )
    out["modis_det_primary_per100km2_burnable_union_ba2012"] = safe_divide(
        out["modis_det_primary"], out["modis_burnable_km2_union_ba2012"], multiplier=100.0
    )
    out["modis_det_primary_per100km2_burnable_annual_ba2012"] = safe_divide(
        out["modis_det_primary"], out["modis_burnable_km2_annual_ba2012"], multiplier=100.0
    )

    out["viirs_det_primary_per100km2_burnable_union_ba2001"] = safe_divide(
        out["viirs_det_primary"], out["modis_burnable_km2_union_ba2001"], multiplier=100.0
    )
    out["viirs_det_primary_per100km2_burnable_annual_ba2001"] = safe_divide(
        out["viirs_det_primary"], out["modis_burnable_km2_annual_ba2001"], multiplier=100.0
    )
    out["viirs_det_primary_per100km2_burnable_union_ba2012"] = safe_divide(
        out["viirs_det_primary"], out["modis_burnable_km2_union_ba2012"], multiplier=100.0
    )
    out["viirs_det_primary_per100km2_burnable_annual_ba2012"] = safe_divide(
        out["viirs_det_primary"], out["modis_burnable_km2_annual_ba2012"], multiplier=100.0
    )

    # FRP density derivations.
    out["modis_frp_sum_daily_max_mw_per_km2_burnable_union_ba2001"] = safe_divide(
        out["modis_frp_sum_daily_max_mw"], out["modis_burnable_km2_union_ba2001"]
    )
    out["modis_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2001"] = safe_divide(
        out["modis_frp_sum_daily_max_mw"], out["modis_burnable_km2_annual_ba2001"]
    )
    out["modis_frp_sum_daily_max_mw_per_km2_burnable_union_ba2012"] = safe_divide(
        out["modis_frp_sum_daily_max_mw"], out["modis_burnable_km2_union_ba2012"]
    )
    out["modis_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2012"] = safe_divide(
        out["modis_frp_sum_daily_max_mw"], out["modis_burnable_km2_annual_ba2012"]
    )

    out["viirs_frp_sum_daily_max_mw_per_km2_burnable_union_ba2001"] = safe_divide(
        out["viirs_frp_sum_daily_max_mw"], out["modis_burnable_km2_union_ba2001"]
    )
    out["viirs_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2001"] = safe_divide(
        out["viirs_frp_sum_daily_max_mw"], out["modis_burnable_km2_annual_ba2001"]
    )
    out["viirs_frp_sum_daily_max_mw_per_km2_burnable_union_ba2012"] = safe_divide(
        out["viirs_frp_sum_daily_max_mw"], out["modis_burnable_km2_union_ba2012"]
    )
    out["viirs_frp_sum_daily_max_mw_per_km2_burnable_annual_ba2012"] = safe_divide(
        out["viirs_frp_sum_daily_max_mw"], out["modis_burnable_km2_annual_ba2012"]
    )

    # Within-sensor intensity derivations.
    out["modis_det_primary_per_active_day"] = safe_divide(out["modis_det_primary"], out["modis_days_active_nh"])
    out["modis_frp_sum_daily_max_mw_per_active_day"] = safe_divide(out["modis_frp_sum_daily_max_mw"], out["modis_frp_active_days"])
    out["modis_frp_sum_daily_max_mw_per_primary_det"] = safe_divide(out["modis_frp_sum_daily_max_mw"], out["modis_det_primary"])

    out["viirs_det_primary_per_active_day"] = safe_divide(out["viirs_det_primary"], out["viirs_days_active_nh"])
    out["viirs_frp_sum_daily_max_mw_per_active_day"] = safe_divide(out["viirs_frp_sum_daily_max_mw"], out["viirs_frp_active_days"])
    # VIIRS numerator and denominator are independently deduplicated streams.
    # A recovered FRP record can coexist with a zero primary count.
    out["viirs_frp_sum_daily_max_mw_per_primary_det"] = safe_divide(out["viirs_frp_sum_daily_max_mw"], out["viirs_det_primary"])

    # Concordance flags remain family-specific for the same reason the BA fields
    # remain family-specific: the realised monthly BA numerator may differ across
    # families over the overlap period.
    out["ba_any_ba2001_and_viirs_primary_any_flag"] = binary_flag_from_inputs(
        (out["modis_ba_any_ba2001"] == 1) & (out["viirs_det_primary_any"] == 1),
        [out["modis_ba_any_ba2001"], out["viirs_det_primary_any"]],
    )
    out["ba_any_ba2012_and_viirs_primary_any_flag"] = binary_flag_from_inputs(
        (out["modis_ba_any_ba2012"] == 1) & (out["viirs_det_primary_any"] == 1),
        [out["modis_ba_any_ba2012"], out["viirs_det_primary_any"]],
    )
    out["ba_any_ba2001_and_modis_primary_any_flag"] = binary_flag_from_inputs(
        (out["modis_ba_any_ba2001"] == 1) & (out["modis_det_primary_any"] == 1),
        [out["modis_ba_any_ba2001"], out["modis_det_primary_any"]],
    )
    out["ba_any_ba2012_and_modis_primary_any_flag"] = binary_flag_from_inputs(
        (out["modis_ba_any_ba2012"] == 1) & (out["modis_det_primary_any"] == 1),
        [out["modis_ba_any_ba2012"], out["modis_det_primary_any"]],
    )
    out["ba_any_ba2001_without_viirs_primary_flag"] = binary_flag_from_inputs(
        (out["modis_ba_any_ba2001"] == 1) & (out["viirs_det_primary_any"] == 0),
        [out["modis_ba_any_ba2001"], out["viirs_det_primary_any"]],
    )
    out["ba_any_ba2012_without_viirs_primary_flag"] = binary_flag_from_inputs(
        (out["modis_ba_any_ba2012"] == 1) & (out["viirs_det_primary_any"] == 0),
        [out["modis_ba_any_ba2012"], out["viirs_det_primary_any"]],
    )
    out["viirs_primary_without_ba_any_ba2001_flag"] = binary_flag_from_inputs(
        (out["viirs_det_primary_any"] == 1) & (out["modis_ba_any_ba2001"] == 0),
        [out["viirs_det_primary_any"], out["modis_ba_any_ba2001"]],
    )
    out["viirs_primary_without_ba_any_ba2012_flag"] = binary_flag_from_inputs(
        (out["viirs_det_primary_any"] == 1) & (out["modis_ba_any_ba2012"] == 0),
        [out["viirs_det_primary_any"], out["modis_ba_any_ba2012"]],
    )
    out["viirs_primary_any_and_modis_primary_any_flag"] = binary_flag_from_inputs(
        (out["viirs_det_primary_any"] == 1) & (out["modis_det_primary_any"] == 1),
        [out["viirs_det_primary_any"], out["modis_det_primary_any"]],
    )

    # Merge/provenance QC fields.
    out["row_in_canonical_spine"] = pd.Series(1, index=out.index, dtype="Int64")
    out["merge_key_complete_flag"] = out[MERGE_KEY].notna().all(axis=1).astype("Int64")

    # This merger fails hard on duplicate keys instead of silently repairing them.
    # The flag is retained for explicit provenance and is always zero in valid
    # outputs.
    out["merge_duplicate_resolved_flag"] = pd.Series(0, index=out.index, dtype="Int64")

    notes: list[str] = []
    for idx in out.index:
        row_notes: list[str] = []
        if out.at[idx, "af_modis_source_present"] != 1:
            row_notes.append("missing_modis_af_source")
        if bool(viirs_supported.loc[idx]) and out.at[idx, "af_viirs_source_present"] != 1:
            row_notes.append("missing_viirs_af_source_in_supported_window")
        if out.at[idx, "ba2001_source_present"] != 1:
            row_notes.append("missing_ba2001_source")
        if bool(ba2012_supported.loc[idx]) and out.at[idx, "ba2012_source_present"] != 1:
            row_notes.append("missing_ba2012_source_in_supported_window")
        notes.append(join_sparse_notes(row_notes))
    out["merge_note"] = pd.Series(notes, index=out.index, dtype="string")

    # Structural-missingness enforcement happens after all derivations so no
    # unsupported month is ever misinterpreted as observed zero activity.
    for column in VIIRS_BASE_FINAL_COLUMNS + VIIRS_DERIVED_FINAL_COLUMNS:
        if column in out.columns:
            out.loc[~viirs_supported, column] = pd.NA

    for column in BA2012_FINAL_COLUMNS:
        if column in out.columns:
            out.loc[~ba2012_supported, column] = pd.NA

    duplicated_columns = pd.Index(out.columns)[pd.Index(out.columns).duplicated()].tolist()
    if duplicated_columns:
        fail(f"derive_final_fields: duplicate column names detected before final selection: {duplicated_columns}")

    missing_columns = [column for column in FINAL_OUTPUT_COLUMNS if column not in out.columns]
    if missing_columns:
        fail(f"derive_final_fields: missing final columns after derivation: {missing_columns}")

    out = out.loc[:, FINAL_OUTPUT_COLUMNS].copy()
    return out.sort_values(MERGE_KEY).reset_index(drop=True)


# =============================================================================
# FINAL PANEL VALIDATION
# =============================================================================


def validate_binary_or_missing(series: pd.Series, context: str) -> None:
    """Ensure a flag column contains only 0, 1, or missing."""
    bad_mask = series.notna() & ~series.isin([0, 1])
    if bad_mask.any():
        sample = series.loc[bad_mask].head(20).tolist()
        fail(f"{context}: expected binary-or-missing values, got sample {sample}")


def validate_final_support_logic(final_panel: pd.DataFrame, level: str) -> None:
    """Validate that unsupported windows remain analytically missing."""
    pre_viirs = final_panel["yyyymm"] < VIIRS_SUPPORT_START_YYYYMM
    pre_ba2012 = final_panel["yyyymm"] < BA2012_SUPPORT_START_YYYYMM

    for column in VIIRS_BASE_FINAL_COLUMNS + VIIRS_DERIVED_FINAL_COLUMNS:
        bad_mask = pre_viirs & final_panel[column].notna()
        if bad_mask.any():
            sample = final_panel.loc[bad_mask, ["unit_id", "yyyymm", column]].head(20)
            fail(
                f"final_panel :: {level}: VIIRS column {column} must be missing before "
                f"{VIIRS_SUPPORT_START_YYYYMM}. Sample:\n{sample.to_string(index=False)}"
            )

    for column in BA2012_FINAL_COLUMNS:
        bad_mask = pre_ba2012 & final_panel[column].notna()
        if bad_mask.any():
            sample = final_panel.loc[bad_mask, ["unit_id", "yyyymm", column]].head(20)
            fail(
                f"final_panel :: {level}: BA-2012 column {column} must be missing before "
                f"{BA2012_SUPPORT_START_YYYYMM}. Sample:\n{sample.to_string(index=False)}"
            )

    expected_viirs_supported = (final_panel["yyyymm"] >= VIIRS_SUPPORT_START_YYYYMM).astype("Int64")
    expected_ba2012_supported = (final_panel["yyyymm"] >= BA2012_SUPPORT_START_YYYYMM).astype("Int64")
    expected_overlap = (
        (final_panel["yyyymm"] >= VIIRS_SUPPORT_START_YYYYMM)
        & (final_panel["yyyymm"] >= BA2012_SUPPORT_START_YYYYMM)
    ).astype("Int64")

    if not final_panel["viirs_supported_flag"].equals(expected_viirs_supported):
        fail(f"final_panel :: {level}: viirs_supported_flag mismatch")
    if not final_panel["ba2012_supported_flag"].equals(expected_ba2012_supported):
        fail(f"final_panel :: {level}: ba2012_supported_flag mismatch")
    if not final_panel["full_overlap_supported_flag"].equals(expected_overlap):
        fail(f"final_panel :: {level}: full_overlap_supported_flag mismatch")
    if not final_panel["viirs_structural_missing_flag"].equals((~(final_panel["yyyymm"] >= VIIRS_SUPPORT_START_YYYYMM)).astype("Int64")):
        fail(f"final_panel :: {level}: viirs_structural_missing_flag mismatch")
    if not final_panel["ba2012_structural_missing_flag"].equals((~(final_panel["yyyymm"] >= BA2012_SUPPORT_START_YYYYMM)).astype("Int64")):
        fail(f"final_panel :: {level}: ba2012_structural_missing_flag mismatch")


def validate_final_panel(final_panel: pd.DataFrame, level: str) -> None:
    """Audit the final output against the exact 111-column contract."""
    debug_final_schema(final_panel, FINAL_OUTPUT_COLUMNS, f"final_panel :: {level}")
    require_exact_columns(final_panel, FINAL_OUTPUT_COLUMNS, f"final_panel :: {level}")
    validate_key_uniqueness(final_panel, MERGE_KEY, f"final_panel :: {level}")

    expected_rows = expected_panel_rows(level)
    if len(final_panel) != expected_rows:
        fail(f"final_panel :: {level}: expected {expected_rows} rows, got {len(final_panel)}")

    if int(final_panel["yyyymm"].min()) != START_YYYYMM or int(final_panel["yyyymm"].max()) != END_YYYYMM:
        fail(
            f"final_panel :: {level}: expected locked month window "
            f"{START_YYYYMM}-{END_YYYYMM}, got "
            f"{int(final_panel['yyyymm'].min())}-{int(final_panel['yyyymm'].max())}"
        )

    forbidden_unsuffixed = {
        "modis_ba_km2",
        "modis_burned_pixel_count",
        "modis_ba_any",
        "modis_aoi_area_land_km2",
        "modis_burnable_km2_union",
        "modis_burnable_km2_annual",
        "modis_burned_frac_union",
        "modis_burned_frac_annual",
    }
    leaked = forbidden_unsuffixed & set(final_panel.columns)
    if leaked:
        fail(
            f"final_panel :: {level}: forbidden unsuffixed BA fields leaked into final output: "
            f"{sorted(leaked)}"
        )
    if any(column.endswith("_preferred") for column in final_panel.columns):
        fail(f"final_panel :: {level}: forbidden *_preferred field leaked into final output")

    validate_final_support_logic(final_panel, level)

    for column in AF_NUMERIC_INT_COLUMNS:
        bad_mask = final_panel[column].notna() & (pd.to_numeric(final_panel[column], errors="coerce") < 0)
        if bad_mask.any():
            sample = final_panel.loc[bad_mask, ["unit_id", "yyyymm", column]].head(20)
            fail(f"final_panel :: {level}: negative values detected in {column}. Sample:\n{sample.to_string(index=False)}")

    binary_ba_columns = {
        "modis_ba_any_ba2001",
        "modis_zero_union_den_flag_ba2001",
        "modis_zero_annual_den_flag_ba2001",
        "modis_ba_any_ba2012",
        "modis_zero_union_den_flag_ba2012",
        "modis_zero_annual_den_flag_ba2012",
    }

    for column in AF_NUMERIC_FLOAT_COLUMNS + ALL_FINAL_BA_COLUMNS:
        if column in binary_ba_columns:
            continue
        bad_mask = final_panel[column].notna() & (pd.to_numeric(final_panel[column], errors="coerce") < 0)
        if bad_mask.any():
            sample = final_panel.loc[bad_mask, ["unit_id", "yyyymm", column]].head(20)
            fail(f"final_panel :: {level}: negative values detected in {column}. Sample:\n{sample.to_string(index=False)}")

    for column in [
        "modis_det_nh_share_of_all",
        "viirs_det_nh_share_of_all",
        "modis_burned_frac_union_ba2001",
        "modis_burned_frac_union_ba2012",
    ]:
        coerced = pd.to_numeric(final_panel[column], errors="coerce")
        bad_mask = final_panel[column].notna() & ~coerced.between(0.0, 1.0)
        if bad_mask.any():
            sample = final_panel.loc[bad_mask, ["unit_id", "yyyymm", column]].head(20)
            fail(
                f"final_panel :: {level}: fraction/share column {column} outside [0, 1]. "
                f"Sample:\n{sample.to_string(index=False)}"
            )

    for column in [
        "modis_ba_any_ba2001",
        "modis_zero_union_den_flag_ba2001",
        "modis_zero_annual_den_flag_ba2001",
        "modis_ba_any_ba2012",
        "modis_zero_union_den_flag_ba2012",
        "modis_zero_annual_den_flag_ba2012",
        "modis_det_primary_any",
        "viirs_det_primary_any",
        "viirs_supported_flag",
        "ba2012_supported_flag",
        "full_overlap_supported_flag",
        "af_modis_source_present",
        "af_viirs_source_present",
        "ba2001_source_present",
        "ba2012_source_present",
        "row_in_canonical_spine",
        "merge_key_complete_flag",
        "merge_duplicate_resolved_flag",
        "viirs_structural_missing_flag",
        "ba2012_structural_missing_flag",
        "ba_any_ba2001_and_viirs_primary_any_flag",
        "ba_any_ba2012_and_viirs_primary_any_flag",
        "ba_any_ba2001_and_modis_primary_any_flag",
        "ba_any_ba2012_and_modis_primary_any_flag",
        "ba_any_ba2001_without_viirs_primary_flag",
        "ba_any_ba2012_without_viirs_primary_flag",
        "viirs_primary_without_ba_any_ba2001_flag",
        "viirs_primary_without_ba_any_ba2012_flag",
        "viirs_primary_any_and_modis_primary_any_flag",
    ]:
        validate_binary_or_missing(final_panel[column], f"final_panel :: {level} :: {column}")

    if not final_panel["af_modis_source_present"].eq(1).all():
        sample = final_panel.loc[final_panel["af_modis_source_present"] != 1, ["unit_id", "yyyymm"]].head(20)
        fail(
            f"final_panel :: {level}: MODIS AF source must be present for all rows. "
            f"Sample:\n{sample.to_string(index=False)}"
        )
    if not final_panel["ba2001_source_present"].eq(1).all():
        sample = final_panel.loc[final_panel["ba2001_source_present"] != 1, ["unit_id", "yyyymm"]].head(20)
        fail(
            f"final_panel :: {level}: BA-2001 source must be present for all rows. "
            f"Sample:\n{sample.to_string(index=False)}"
        )

    expected_viirs_present = (final_panel["yyyymm"] >= VIIRS_SUPPORT_START_YYYYMM).astype("Int64")
    expected_ba2012_present = (final_panel["yyyymm"] >= BA2012_SUPPORT_START_YYYYMM).astype("Int64")
    if not final_panel["af_viirs_source_present"].equals(expected_viirs_present):
        fail(f"final_panel :: {level}: af_viirs_source_present does not match expected support window")
    if not final_panel["ba2012_source_present"].equals(expected_ba2012_present):
        fail(f"final_panel :: {level}: ba2012_source_present does not match expected support window")


# =============================================================================
# PER-LEVEL PANEL CONSTRUCTION
# =============================================================================


def build_level_panel(
    level: str,
    spine: pd.DataFrame,
    families_by_name: Mapping[str, LoadedFamily],
    merge_run_id: str,
) -> pd.DataFrame:
    """Merge all four families for one level, derive metrics, and validate output."""
    working = spine.copy().sort_values(MERGE_KEY).reset_index(drop=True)

    modis_af = families_by_name[f"modis_af_{level}_base"]
    viirs_af = families_by_name[f"viirs_af_{level}_base"]
    ba2001 = families_by_name[f"ba2001_{level}_base"]
    ba2012 = families_by_name[f"ba2012_{level}_base"]

    # AF families are merged first, then BA families. Every source has already
    # passed strict uniqueness and coverage checks, so each join must be one-to-one.
    working = safe_left_merge(working, prepare_af_merge_frame(modis_af), f"{level} :: modis_af merge")
    working = safe_left_merge(working, prepare_af_merge_frame(viirs_af), f"{level} :: viirs_af merge")
    working = safe_left_merge(working, prepare_ba_merge_frame(ba2001), f"{level} :: ba2001 merge")
    working = safe_left_merge(working, prepare_ba_merge_frame(ba2012), f"{level} :: ba2012 merge")

    # Unsupported months correctly merge as absent for VIIRS and BA-2012. That
    # raw absence is retained here as provenance before structural-missingness is
    # enforced downstream.
    for column in ["af_modis_source_present", "af_viirs_source_present", "ba2001_source_present", "ba2012_source_present"]:
        if column not in working.columns:
            fail(f"{level}: missing expected source-presence column after merge: {column}")
        working[column] = working[column].fillna(0).astype("Int64")

    final_panel = derive_final_fields(working, merge_run_id)
    validate_final_panel(final_panel, level)
    return final_panel


# =============================================================================
# METADATA WRITERS
# =============================================================================


def build_key_audit(acz_panel: pd.DataFrame, district_panel: pd.DataFrame) -> pd.DataFrame:
    """Build a compact deterministic key audit for the two final outputs."""
    rows: list[dict[str, Any]] = []
    for level, panel, expected_rows in [
        ("acz", acz_panel, expected_panel_rows("acz")),
        ("district", district_panel, expected_panel_rows("district")),
    ]:
        rows.append(
            {
                "level": level,
                "expected_rows": expected_rows,
                "actual_rows": int(len(panel)),
                "unique_keys": int(panel.drop_duplicates(MERGE_KEY).shape[0]),
                "duplicate_key_rows": int(panel.duplicated(MERGE_KEY, keep=False).sum()),
                "yyyymm_min": int(panel["yyyymm"].min()),
                "yyyymm_max": int(panel["yyyymm"].max()),
                "column_count": int(panel.shape[1]),
                "passes_key_audit": bool(
                    len(panel) == expected_rows
                    and panel.drop_duplicates(MERGE_KEY).shape[0] == expected_rows
                    and panel.shape[1] == len(FINAL_OUTPUT_COLUMNS)
                ),
            }
        )
    return pd.DataFrame(rows).sort_values("level").reset_index(drop=True)


def verified_active_fire_method(paths: PathsConfig, loaded_families: Sequence[LoadedFamily]) -> dict[str, Any]:
    """Verify the aggregation-policy-to-export chain before admitting FRP inputs."""
    receipt_path = paths.af_root.parent / "qa" / "combine_panels_manifest.json"
    if not receipt_path.is_file():
        fail("Active-fire combine receipt missing; generate panels with the current workflow")
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        fail(f"Invalid active-fire combine receipt: {exc}")
    method = receipt.get("active_fire_method", {})
    if method.get("status") != "VERIFIED_AGGREGATION_INPUTS" or method.get("method_version") != "viirs_frp_dual_stream_v1" or method.get("frp_selection_stage") != "before_independent_deduplication" or method.get("frp_population_viirs") != "nominal_high_independently_deduplicated" or method.get("frp_confidence_categories") != ["n", "h"] or method.get("frp_aggregation") != "mean_of_daily_maxima_over_eligible_utc_days":
        fail("Active-fire inputs lack verified nominal/high FRP aggregation evidence")
    dedup = method.get("deduplication")
    if (not isinstance(method.get("config_sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", method["config_sha256"]) or
        not isinstance(dedup, dict) or not isinstance(dedup.get("tie_break"), list) or not dedup["tie_break"] or
        not isinstance(dedup.get("latlon_round_decimals"), int) or not isinstance(dedup.get("include_satellite_in_key"), bool) or
        not isinstance(method.get("frp_min_mw"), (int, float)) or not math.isfinite(method["frp_min_mw"]) or method["frp_min_mw"] < 0):
        fail("Active-fire configuration, deduplication or FRP threshold evidence is missing")
    # FIRMS writes all receipt paths relative to its own subproject root.
    # Resolve only within that root and normalize the verified paths for the
    # project-level merger manifest. Never modify or re-hash the source receipt.
    project_root = paths.repo_root.resolve()
    firms_root = (project_root / "RP1_Project" / "rp1_mv_firms_panels").resolve()
    if not firms_root.is_relative_to(project_root) or not paths.af_root.resolve().is_relative_to(firms_root):
        fail("Active-fire export root is outside the FIRMS subproject")

    def receipt_path_for(value: Any) -> Path:
        if not isinstance(value, str) or not value or Path(value).is_absolute():
            fail("Invalid active-fire receipt path")
        source = (firms_root / value).resolve()
        if not source.is_relative_to(firms_root):
            fail("Active-fire receipt path escapes FIRMS subproject")
        return source

    evidence = method.get("evidence_files")
    if not isinstance(evidence, list) or len(evidence) != 6:
        fail("Active-fire aggregation evidence is incomplete")
    normalized = []
    for entry in evidence:
        if not isinstance(entry, dict):
            fail("Invalid active-fire aggregation evidence")
        source = receipt_path_for(entry.get("path"))
        if not source.is_file() or sha256_file(source) != entry.get("sha256"):
            fail("Active-fire aggregation evidence missing or hash mismatch: " + str(source))
        normalized.append({"path": relative_to_repo(source, project_root), "sha256": entry["sha256"]})
    preparation_evidence = method.get("viirs_preparation_evidence")
    if not isinstance(preparation_evidence, list) or len(preparation_evidence) < 5 or method.get("frp_deduplication_independent") is not True or method.get("frp_finite_values_rank_first") is not True:
        fail("VIIRS independent preparation evidence is incomplete")
    normalized_preparation = []
    for entry in preparation_evidence:
        if not isinstance(entry, dict):
            fail("Invalid VIIRS preparation evidence")
        if entry.get("scope") == "workspace":
            value = entry.get("path")
            if not isinstance(value, str) or not value or Path(value).is_absolute():
                fail("Invalid workspace geography evidence path")
            source = (project_root / value).resolve()
            if not source.is_relative_to(project_root):
                fail("Geography evidence escapes project workspace")
        else:
            source = receipt_path_for(entry.get("path"))
        if not source.is_file() or sha256_file(source) != entry.get("sha256"):
            fail("VIIRS preparation evidence missing or changed: " + str(source))
        normalized_preparation.append({"path": relative_to_repo(source, project_root), "sha256": entry["sha256"]})
    profiles = method.get("input_profiles")
    source_preparation = method.get("source_preparation_evidence", [])
    normalized_sources = []
    if profiles is not None:
        allowed_profiles = {"native_firms_v1", "ghana_firms_archive_sp_v1"}
        if (not isinstance(profiles, dict) or set(profiles) != {"modis", "viirs"}
                or any(not isinstance(value, str) or value not in allowed_profiles for value in profiles.values())):
            fail("Invalid active-fire input profile declarations")
        if (not isinstance(source_preparation, list)
                or ("ghana_firms_archive_sp_v1" in profiles.values() and not source_preparation)):
            fail("Archive SP source preparation evidence is incomplete")
        for entry in source_preparation:
            if not isinstance(entry, dict):
                fail("Invalid active-fire source preparation evidence")
            if entry.get("scope") == "workspace":
                value = entry.get("path")
                if not isinstance(value, str) or not value or Path(value).is_absolute():
                    fail("Invalid source preparation workspace path")
                source = (project_root / value).resolve()
                if not source.is_relative_to(project_root):
                    fail("Source preparation evidence escapes project workspace")
            else:
                source = receipt_path_for(entry.get("path"))
            if not source.is_file() or sha256_file(source) != entry.get("sha256"):
                fail("Active-fire source preparation evidence missing or changed: " + str(source))
            normalized_sources.append({"path": relative_to_repo(source, project_root), "sha256": entry["sha256"]})
    elif source_preparation:
        fail("Source preparation evidence requires explicit input profiles")
    recorded: dict[Path, str] = {}
    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "path" in node and "sha256" in node:
                source = receipt_path_for(node["path"])
                digest = str(node["sha256"])
                if source in recorded and recorded[source] != digest:
                    fail("Conflicting active-fire export receipt entries")
                recorded[source] = digest
            for child in node.values(): walk(child)
        elif isinstance(node, list):
            for child in node: walk(child)
    walk(receipt.get("rp1_af_exports", {}))
    for family in loaded_families:
        if family.spec.source_kind not in {"modis_af", "viirs_af"}: continue
        for entry in family.file_inventory_rows:
            source_rel = str(entry["origin_path"])
            source = (project_root / source_rel).resolve()
            if not source.is_relative_to(paths.af_root.resolve()) or not source.is_file() or recorded.get(source) != sha256_file(source):
                fail("Active-fire export is not bound to its combine receipt: " + source_rel)
    result = dict(method) | {"evidence_files": normalized, "viirs_preparation_evidence": normalized_preparation, "combine_receipt": {"path": relative_to_repo(receipt_path, project_root), "sha256": sha256_file(receipt_path)}}
    if profiles is not None:
        result["source_preparation_evidence"] = normalized_sources
    return result



def build_manifest(
    paths: PathsConfig,
    merge_run_id: str,
    loaded_families: Sequence[LoadedFamily],
    output_paths: Mapping[str, Path],
) -> dict[str, Any]:
    """Build the stable manifest JSON written alongside the outputs."""
    family_payloads: list[dict[str, Any]] = []
    for family in sorted(loaded_families, key=lambda item: item.spec.family_name):
        family_payloads.append(
            {
                "family_name": family.spec.family_name,
                "source_kind": family.spec.source_kind,
                "level": family.spec.level,
                "support_start_yyyymm": family.spec.support_start_yyyymm,
                "support_end_yyyymm": family.spec.support_end_yyyymm,
                "root": {
                    "origin_path": relative_to_repo(family.spec.root_dir, paths.repo_root),
                    "staged_path": relative_to_repo(family.spec.root_dir, paths.repo_root),
                },
                "schema_version": family.schema_version,
                "run_ids": family.run_ids,
                "files": sorted(
                    family.file_inventory_rows,
                    key=lambda row: (
                        row["level"],
                        row["family_name"],
                        row["partition_code"],
                        row["origin_path"],
                    ),
                ),
            }
        )

    outputs_payload: dict[str, Any] = {}
    for name, path in sorted(output_paths.items()):
        relative = relative_to_repo(path, paths.repo_root)
        entry: dict[str, Any] = {
            "origin_path": relative,
            "staged_path": relative,
        }

        # The manifest intentionally avoids trying to hash itself before it has
        # been written. Files that already exist get hashes; the manifest entry
        # therefore carries a path only at write time.
        if path.exists():
            entry["sha256"] = sha256_file(path)

        outputs_payload[name] = entry

    return {
        "merge_run_id": merge_run_id,
        "study": {"start_yyyymm": START_YYYYMM, "end_yyyymm": END_YYYYMM,
                  "viirs_support_start_yyyymm": VIIRS_SUPPORT_START_YYYYMM,
                  "ba2012_support_start_yyyymm": BA2012_SUPPORT_START_YYYYMM,
                  **({'analysis_overlap_start_yyyymm': ANALYSIS_OVERLAP_START_YYYYMM}
                     if ANALYSIS_OVERLAP_START_YYYYMM is not None else {})},
        "active_fire_method": verified_active_fire_method(paths, loaded_families),
        "merge_schema_version": MERGE_SCHEMA_VERSION,
        "written_at_utc": stable_now_iso(),
        "repo_root": ".",
        "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
        "path_semantics": PROVENANCE_PATH_SEMANTICS,
        "profile_id": paths.profile_id,
        "profile_contract": dict(paths.profile_contract or {}),
        "configuration": {
            "path": relative_to_repo(paths.config_path, paths.repo_root) if paths.config_path else None,
            "sha256": paths.config_sha256,
        },
        "ba_bundle": {
            "manifest_sha256": sha256_file(paths.bundle_manifest_path),
            "handoff_sha256": sha256_file(paths.bundle_handoff_path),
            "scope": json.loads(paths.bundle_manifest_path.read_text(encoding="utf-8"))["scope"],
        },
        "ba_source_lock": {
            "path": relative_to_repo(paths.source_lock_path, paths.repo_root) if paths.source_lock_path else None,
            "sha256": sha256_file(paths.source_lock_path) if paths.source_lock_path else None,
            "identity_scope": "Lock binds selected CSV bytes only; historical GEE script and live asset identity remain unverified.",
        },
        "ba_observation_support": {
            "schema_version": "rp1-ba-c3-evidence-v1",
            "profile_id": paths.profile_id,
            "quality_policy": c3.POLICY,
            "method_version": c3.METHOD,
            "source_schema_version": c3.SCHEMA,
            "sidecar_output": "ba_observation_support.csv",
            "source_values_preserved": True,
            "provenance_limitation": "File hashes and declared metadata do not prove historical GEE script or live asset identity.",
        },
        "source_roots": {
            "unit_universe": {
                "origin_path": relative_to_repo(paths.unit_universe_path, paths.repo_root),
                "staged_path": relative_to_repo(paths.unit_universe_path, paths.repo_root),
                "sha256": sha256_file(paths.unit_universe_path),
            },
            "active_fire": {
                "origin_path": relative_to_repo(paths.af_root, paths.repo_root),
                "staged_path": relative_to_repo(paths.af_root, paths.repo_root),
            },
            "ba2001": {
                "origin_path": relative_to_repo(paths.ba2001_root, paths.repo_root),
                "staged_path": relative_to_repo(paths.ba2001_root, paths.repo_root),
            },
            "ba2012": {
                "origin_path": relative_to_repo(paths.ba2012_root, paths.repo_root),
                "staged_path": relative_to_repo(paths.ba2012_root, paths.repo_root),
            },
        },
        "final_schema_columns": FINAL_OUTPUT_COLUMNS,
        "final_schema_sha256": sha256_text("\n".join(FINAL_OUTPUT_COLUMNS)),
        "families": family_payloads,
        "outputs": outputs_payload,
    }


def build_merge_summary(merge_run_id,acz_panel,district_panel,evidence=None):
    """Keep dimensions separate from c3 result/evidence admission counts."""
    def level_block(panel):
        return {'row_count':len(panel),'column_count':panel.shape[1],
            'yyyymm_min':int(panel.yyyymm.min()),'yyyymm_max':int(panel.yyyymm.max()),
            'unique_units':int(panel.unit_id.nunique()),
            'viirs_structural_missing_rows':int(panel.viirs_structural_missing_flag.sum()),
            'ba2012_structural_missing_rows':int(panel.ba2012_structural_missing_flag.sum()),
            'viirs_supported_rows':int(panel.viirs_supported_flag.sum()),
            'ba2012_supported_rows':int(panel.ba2012_supported_flag.sum())}
    result={'merge_run_id':merge_run_id,'merge_schema_version':MERGE_SCHEMA_VERSION,
        'acz':level_block(acz_panel),'district':level_block(district_panel)}
    if evidence is not None:
        result['c3_evidence']={'schema_version':'rp1-ba-c3-evidence-v1','method_version':c3.METHOD,
            'quality_policy':c3.POLICY,'records':evidence.groupby(
                ['family','level','ba_status','ba_coverage_status'],dropna=False).size().rename('rows').reset_index().to_dict('records')}
    return result


# =============================================================================
# WRITE HELPERS
# =============================================================================


def write_csv(df: pd.DataFrame, path: Path) -> None:
    """Write CSV deterministically with no index column."""
    df.to_csv(path, index=False)


def write_json(payload: Any, path: Path) -> None:
    """Write stable sorted JSON for deterministic manifests and summaries."""
    path.write_text(stable_json_dumps(payload) + "\n", encoding="utf-8")


# =============================================================================
# ORCHESTRATION
# =============================================================================


def default_merge_run_id() -> str:
    """Create a deterministic-format merger run identifier."""
    return datetime.now(timezone.utc).strftime("merge_fire_panel_%Y%m%dT%H%M%SZ")


def publish_directory_no_replace(staging: Path, target: Path) -> None:
    """Publish through the shared local utility, retaining the merger error API."""
    try:
        _local_io.publish_directory_no_replace(staging, target)
    except _local_io.PublicationError as exc:
        fail(str(exc))


def preflight_directory_publication(target: Path) -> None:
    """Probe the shared primitive on the selected output filesystem."""
    def publish(staging, destination):
        try:
            publish_directory_no_replace(staging, destination)
        except ValidationError as exc:
            raise _local_io.PublicationError(str(exc)) from exc
    try:
        _local_io.preflight_directory_publication(target, publisher=publish)
    except _local_io.PublicationError as exc:
        fail(str(exc))


def verify_c3_admission(paths: PathsConfig) -> None:
    """Recheck admission at execution, including callers constructing PathsConfig."""
    if (not paths.admission_verified or paths.bundle_manifest_path is None
            or paths.bundle_handoff_path is None or paths.source_lock_path is None):
        fail("A verified admitted c3 handoff is required before merge")
    if paths.config_path is not None and (
            not paths.config_sha256 or sha256_file(paths.config_path) != paths.config_sha256):
        fail("Merger configuration changed after input resolution")
    from RP1_Project.rp1_ba_consolidator.handoff import verify_handoff
    study = {"start_yyyymm": START_YYYYMM, "end_yyyymm": END_YYYYMM,
             "viirs_support_start_yyyymm": VIIRS_SUPPORT_START_YYYYMM,
             "ba2012_support_start_yyyymm": BA2012_SUPPORT_START_YYYYMM,
             "expected_units": dict(EXPECTED_UNITS)}
    if ANALYSIS_OVERLAP_START_YYYYMM is not None:
        study['analysis_overlap_start_yyyymm'] = ANALYSIS_OVERLAP_START_YYYYMM
    try:
        admitted = verify_handoff(paths.bundle_handoff_path.parent,
            unit_universe=paths.unit_universe_path, profile_id="c3", study=study)
    except (ValueError, OSError) as exc:
        fail(f"c3 admission changed before execution: {exc}")
    for name in ("ba2001_root", "ba2012_root"):
        if Path(admitted[name]).resolve() != getattr(paths, name).resolve():
            fail("c3 execution sources differ from the admitted bundle")
    if Path(admitted["source_lock"]).resolve() != paths.source_lock_path.resolve():
        fail("c3 execution source lock differs from admission")
    locked = json.loads(paths.source_lock_path.read_text(encoding="utf-8"))
    if list(paths.source_lock_entries) != locked.get("files"):
        fail("c3 in-memory source records differ from the admitted source lock")
    if Path(admitted["bundle_manifest"]).resolve() != paths.bundle_manifest_path.resolve():
        fail("c3 execution manifest differs from admission")


def run(paths: PathsConfig, merge_run_id: str) -> dict[str, Path]:
    """Execute the full merger workflow and write all primary outputs."""
    if paths.output_dir.exists() or paths.output_dir.is_symlink():
        fail(f"Output directory already exists; choose a new --output-dir: {paths.output_dir}")

    preflight_directory_publication(paths.output_dir)
    verify_c3_admission(paths)

    unit_universe = load_unit_universe(paths)
    partition_codes = canonical_partition_codes(unit_universe)
    spines = {level: build_canonical_spine(unit_universe, level) for level in SUPPORTED_LEVELS}

    family_specs = build_family_specs(paths)
    if not paths.admission_verified or paths.bundle_manifest_path is None or paths.bundle_handoff_path is None:
        fail("A verified admitted c3 handoff is required before merge")
    initial_binding = {p:sha256_file(p) for p in (paths.bundle_manifest_path,paths.bundle_handoff_path,paths.source_lock_path,paths.unit_universe_path)}
    if paths.config_path is not None:
        initial_binding[paths.config_path] = paths.config_sha256
    loaded_families = [
        load_family(spec, unit_universe, spines[spec.level], partition_codes, paths)
        for spec in family_specs
    ]
    families_by_name = {family.spec.family_name: family for family in loaded_families}

    acz_panel = build_level_panel("acz", spines["acz"], families_by_name, merge_run_id)
    district_panel = build_level_panel("district", spines["district"], families_by_name, merge_run_id)

    output_paths = {
        "fire_panel_acz": paths.output_dir / f"fire_panel_acz_monthly_consolidated_{START_YYYYMM // 100}_{END_YYYYMM // 100}.csv",
        "fire_panel_district": paths.output_dir / f"fire_panel_district_monthly_consolidated_{START_YYYYMM // 100}_{END_YYYYMM // 100}.csv",
        "key_audit": paths.output_dir / "fire_panel_key_audit.csv",
        "manifest": paths.output_dir / "fire_panel_manifest.json",
        "merge_summary": paths.output_dir / "fire_panel_merge_summary.json",
        "ba_observation_support": paths.output_dir / "ba_observation_support.csv",
    }
    sidecars = [item for family in loaded_families for item in (family.qa_sidecars or [])]
    if not sidecars:
        fail("BA observation-support sidecar is missing")
    sidecar = pd.concat(sidecars, ignore_index=True).sort_values(MERGE_KEY + ["family"]).reset_index(drop=True)
    optional = ['ba_annual_lc_source_index'] if 'ba_annual_lc_source_index' in sidecar else []
    sidecar = sidecar[list(c3.FIELDS) + optional + ['family', 'source_path', 'source_sha256', 'source_row']]
    validate_key_uniqueness(sidecar, MERGE_KEY + ["family"], "BA observation support")
    paths.output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + paths.output_dir.name + ".staging-", dir=paths.output_dir.parent))
    staged = {key: staging / path.name for key, path in output_paths.items()}
    try:
        write_csv(acz_panel, staged["fire_panel_acz"])
        write_csv(district_panel, staged["fire_panel_district"])
        write_csv(build_key_audit(acz_panel, district_panel), staged["key_audit"])
        write_csv(sidecar, staged["ba_observation_support"])
        write_json(build_merge_summary(merge_run_id, acz_panel, district_panel, sidecar), staged["merge_summary"])
        manifest = build_manifest(paths, merge_run_id, loaded_families, output_paths)
        for key, path in staged.items():
            if key != "manifest":
                manifest["outputs"][key]["sha256"] = sha256_file(path)
        write_json(manifest, staged["manifest"])
        for bound_path,digest in initial_binding.items():
            if sha256_file(bound_path) != digest:
                fail("c3 source/geography/admission changed during merge")
        for family in loaded_families:
            if family.spec.source_kind in ("ba2001","ba2012"):
                for entry,path in zip(sorted([e for e in paths.source_lock_entries if e["family"]==family.spec.source_kind and e["level"]==family.spec.level], key=lambda x:(x["partition"],x["year"])),family.files):
                    verify_locked_file(path,entry,"prepublication c3 source")
        publish_directory_no_replace(staging, paths.output_dir)
    finally:
        if staging.exists():
            shutil.rmtree(staging)

    return output_paths


# =============================================================================
# CLI
# =============================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line interface for the standalone merger script."""
    parser = argparse.ArgumentParser(
        description="Merge governed AF and BA source families into final consolidated RP1 fire panels."
    )
    parser.add_argument("--config", default=None, help="Merger profile configuration JSON (paths relative to repository root).")
    parser.add_argument("--profile", default="c3", choices=["c3"], help="The sole operational BA source profile.")
    parser.add_argument("--ba-handoff", default=None, help="Verified c3 bundle handoff.json; preparation is required.")
    parser.add_argument(
        "--repo-root",
        default=None,
        help="Umbrella repository root. Defaults to the root inferred from this script location or GHANA_FIRE_RP1_REPO_ROOT.",
    )
    parser.add_argument(
        "--unit-universe",
        default=None,
        help="Explicit path to unit_universe.csv.",
    )
    parser.add_argument(
        "--af-root",
        default=None,
        help="Root directory of rp1_af_exports.",
    )
    parser.add_argument(
        "--ba2001-root",
        default=None,
        help="Admitted c3 sources directory; cannot override bundle identity.",
    )
    parser.add_argument(
        "--ba2012-root",
        default=None,
        help="Admitted c3 sources directory; cannot override bundle identity.",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Directory for consolidated outputs and audit artefacts.",
    )
    parser.add_argument(
        "--run-id",
        default=None,
        help="Explicit merger run_id. Defaults to a UTC timestamped identifier.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    merge_run_id = args.run_id or default_merge_run_id()
    try:
        paths = build_paths_config(args)
        run(paths, merge_run_id)
    except (ValidationError, c3.C3ValidationError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0




def load_family(spec, unit_universe, spine, partition_codes, paths):
    """Load AF unchanged or a complete locked set of annual c3 partitions."""
    if spec.source_kind not in ('ba2001','ba2012'):
        return _load_af_family(spec,unit_universe,spine,partition_codes,paths)
    if paths.profile_id != 'c3' or any((paths.profile_contract or {}).get(k) != v for k,v in c3.PROFILE.items()):
        fail('Only the c3 burned-area profile is supported')
    entries = [entry for entry in paths.source_lock_entries if entry['family'] == spec.source_kind and entry['level'] == spec.level]
    expected = {(code,year) for code in partition_codes for year in range(spec.support_start_yyyymm//100,spec.support_end_yyyymm//100+1)}
    observed = {(entry['partition'],entry['year']) for entry in entries}
    if observed != expected or len(entries) != len(expected):
        fail(f'{spec.family_name}: source lock does not exactly cover annual zone/year identities')
    if paths.bundle_manifest_path is None:
        fail('c3 source bundle manifest is required')
    bundle = paths.bundle_manifest_path.parent.resolve()
    units = unit_universe.loc[unit_universe.level.eq(spec.level),IDENTITY_COLUMNS].copy()
    canonical = {str(row['unit_id']):row for row in units.to_dict('records')}
    frames,evidence_frames,inventory,files,run_ids = [],[],[],[],set()
    for entry in sorted(entries,key=lambda x:(x['partition'],x['year'])):
        relative = entry.get('path','')
        path = (bundle/relative).resolve()
        if not relative or path == bundle or not path.is_relative_to(bundle) or path.is_symlink() or not path.is_file():
            fail('Unsafe or missing c3 source path: ' + str(relative))
        observation_windows = c3.observation_windows(START_YYYYMM//100, END_YYYYMM//100)
        identity = c3.parse_filename(path.name, observation_windows=observation_windows)
        if any(identity[key] != entry[key] for key in ('family','level','partition','year','role')):
            fail('c3 lock identity disagrees with filename')
        verify_locked_file(path,entry,spec.family_name)
        if path.stat().st_size != entry.get('size_bytes'):
            fail('c3 source byte size differs from source lock')
        with path.open(encoding='utf-8-sig',newline='') as stream:
            reader = csv.DictReader(stream,strict=True)
            c3.validate_header(reader.fieldnames or [])
            rows = list(reader)
        if not rows:
            fail('Empty c3 annual source: ' + path.name)
        for row in rows:
            if None in row or any(value is None for value in row.values()):
                fail('Malformed c3 CSV row width: ' + path.name)
            unit = canonical.get(row.get('unit_id',''))
            if unit is None:
                fail('Unexpected c3 unit: ' + row.get('unit_id',''))
            unit = {key:('' if pd.isna(value) else value) for key,value in unit.items()}
            try:
                c3.validate_row(row,identity=identity,unit=unit,allow_technical=True,
                    observation_windows=observation_windows)
            except ValueError as exc:
                fail(f'{path.name}: {exc}')
        raw = pd.DataFrame(rows)
        typed,evidence = apply_ba_profile(raw,profile=paths.profile_contract,family=spec.source_kind,context=path.name)
        typed = validate_time_columns(typed,spec,path.name)
        validate_key_uniqueness(typed,MERGE_KEY,path.name)
        expected_units = {str(row['unit_id']) for row in canonical.values() if str(row['unit_code'] if spec.level=='acz' else row['parent_code']) == identity['partition']}
        expected_keys = {(unit,identity['year']*100+month) for unit in expected_units for month in range(1,13)}
        if set(zip(typed.unit_id.astype(str),typed.yyyymm.astype(int))) != expected_keys:
            fail(f'{path.name}: incomplete annual unit/month coverage')
        evidence['source_path'] = relative
        evidence['source_sha256'] = entry['sha256']
        evidence['source_row'] = range(1,len(evidence)+1)
        source_ids = sorted(set(raw.run_id))
        run_ids.update(source_ids)
        frames.append(typed); evidence_frames.append(evidence); files.append(path)
        inventory.append({'family_name':spec.family_name,'source_kind':spec.source_kind,'level':spec.level,
            'partition_code':identity['partition'],'year':identity['year'],'domain':identity['domain'],
            'origin_path':relative_to_repo(path,paths.repo_root),'staged_path':relative_to_repo(path,paths.repo_root),
            'source_path':relative,'sha256':entry['sha256'],'size_bytes':entry['size_bytes'],'row_count':len(raw),
            'yyyymm_min':int(typed.yyyymm.min()),'yyyymm_max':int(typed.yyyymm.max()),
            'run_id':source_ids[0] if len(source_ids)==1 else None,'run_ids':source_ids,'schema_version':c3.SCHEMA})
    data = pd.concat(frames,ignore_index=True)
    validate_key_uniqueness(data,MERGE_KEY,spec.family_name)
    validate_supported_key_coverage(data,expected_supported_keys(spine,spec.support_start_yyyymm,spec.support_end_yyyymm),spec.family_name)
    evidence = pd.concat(evidence_frames,ignore_index=True)
    for field,keys in [('ba_known_union_area_km2',['unit_id']),('modis_burnable_km2_union',['unit_id']),('modis_burnable_km2_annual',['unit_id','year'])]:
        values = pd.to_numeric(blank_to_na(evidence[field]),errors='raise')
        audit = evidence[keys].copy(); audit[field] = values
        spread = audit.groupby(keys,observed=True)[field].agg(['min','max'])
        if ((spread['max']-spread['min']) > 1e-9).any():
            fail(f'{spec.family_name}: nonconstant c3 domain/annual denominator {field}')
    return LoadedFamily(spec=spec,files=files,data=data.sort_values(MERGE_KEY).reset_index(drop=True),
        run_ids=sorted(run_ids),schema_version=c3.SCHEMA,file_inventory_rows=inventory,qa_sidecars=evidence_frames)

if __name__ == "__main__":
    raise SystemExit(main())
