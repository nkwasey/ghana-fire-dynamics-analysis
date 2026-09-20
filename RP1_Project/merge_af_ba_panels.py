#!/usr/bin/env python3
"""
# merge_af_ba_panels.py

Audit-grade merger for the final consolidated RP1 Ghana fire panels.

## Purpose

This module builds one final monthly fire panel per level by merging four
scientifically governed upstream families onto one canonical balanced monthly
spine derived from the Stage 1 geography contract:

1. MODIS active-fire (AF) base exports
2. VIIRS active-fire (AF) base exports
3. MODIS burned-area (BA) base exports using the BA-2001 family
4. MODIS burned-area (BA) base exports using the BA-2012 family

It writes one consolidated CSV for:

- `acz` / zonal level
- `district` level

The merged outputs span the locked window `200101` through `202412` inclusive.

## Why this rewrite exists

Earlier merger logic treated the BA-2001 and BA-2012 families as if they shared
one common realised BA numerator during the overlap period. That assumption is
scientifically unsafe for this project.

The audited GEE BA export scripts use different fixed burnable-union support
windows for the two BA families:

- BA-2001 family support window: `200101–202412`
- BA-2012 family support window: `201201–202412`

Crucially, that family-specific union mask is not only used for denominator
construction. It is also applied to the realised monthly BA numerator. As a
result, the following fields can legitimately differ between BA families during
`201201–202412`:

- `modis_ba_km2`
- `modis_burned_pixel_count`
- `modis_ba_any`
- `modis_burned_frac_union`
- `modis_burned_frac_annual`

Accordingly, this merger intentionally preserves both BA families throughout
the final output and never collapses them into unsuffixed shared BA fields.

## Locked scientific decisions implemented here

### 1. Canonical balanced spine

The final panel is built from `unit_universe.csv` and not from source-row
presence. The governing key is:

- `level`
- `unit_id`
- `yyyymm`

The canonical spine is balanced over:

- all governed units in the Stage 1 geography contract
- every month from `200101` to `202412`

Expected row counts are locked and audited:

- `acz`: `5 × 288 = 1440`
- `district`: `260 × 288 = 74880`

### 2. Both BA families are preserved explicitly

This merger does not emit unsuffixed BA analytical fields in the final
output. Instead, it writes family-specific versions using the suffixes:

- `_ba2001`
- `_ba2012`

### 3. No `*_preferred` BA fields

The merger does not choose a preferred BA family. Any downstream selection
between BA-2001 and BA-2012 must be done explicitly by the analysis consumer.

### 4. AF primary count rule

The main science-facing AF count is locked to nominal-plus-high detections:

- `modis_det_primary = modis_det_nh`
- `viirs_det_primary = viirs_det_nh`

### 5. Structural missingness is preserved

Unsupported months are not silently converted to zero:

- VIIRS is structurally unsupported before `201201`
- BA-2012 is structurally unsupported before `201201`

These months remain missing in the corresponding analytical columns and are
tracked explicitly by support and structural-missingness flags.

## Input contracts

### Canonical geography

Default path:

- `geo_data_prep/out/example_acz/unit_universe.csv`

Stage 1 geography is the sole authority for:

- `level`
- `unit_id`
- `unit_code`
- `unit_name`
- `parent_level`
- `parent_id`
- `parent_code`
- `parent_name`

Source files are validated against this contract but never allowed to redefine
identity.

### AF base exports

Default root:

- `RP1_Project/rp1_mv_firms_panels/out/runs/ghana_full/rp1_af_exports`

Expected family branches:

- `<af_root>/acz/modis`
- `<af_root>/acz/viirs`
- `<af_root>/district/modis`
- `<af_root>/district/viirs`

Only governed base exports are accepted. `_ext` files, manifests,
summaries, QA files, and unrelated CSVs are rejected.

### BA base exports

Default roots:

- `RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2001`
- `RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2012`

Only governed base exports for the requested level are accepted. `_ext`
files, QA files, drop logs, manifests, and wrong-level files are rejected.

## Output contract

Primary outputs:

- `fire_panel_acz_monthly_consolidated_2001_2024.csv`
- `fire_panel_district_monthly_consolidated_2001_2024.csv`

Companion audit artefacts:

- `fire_panel_manifest.json`
- `fire_panel_merge_summary.json`
- `fire_panel_key_audit.csv`

## Validation philosophy

This module is intentionally strict. It fails hard on integrity breaches that
would make the final panel ambiguous, non-deterministic, or scientifically
unsafe, including:

- missing source families
- wrong-folder ingestion
- duplicate keys
- wrong level values
- support-window violations
- schema drift
- non-canonical source identity
- missing supported rows
- unexpected extra rows
- impossible AF logic
- impossible BA logic
- final schema mismatch
- final row-count mismatch

## Usage

From the umbrella repository root:

    python RP1_Project/merge_af_ba_panels.py

Optional explicit paths can be supplied when needed:

    python RP1_Project/merge_af_ba_panels.py \
      --repo-root . \
      --af-root RP1_Project/rp1_mv_firms_panels/out/runs/ghana_full/rp1_af_exports \
      --ba2001-root RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2001 \
      --ba2012-root RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2012 \
      --output-dir RP1_Project/rp1_analysis/data/raw

The implementation uses only the standard library plus `pandas` and `numpy`.
All file writes are deterministic and all metadata JSON outputs are serialized in
stable sorted order.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pandas as pd


# =============================================================================
# LOCKED CONTRACT CONSTANTS
# =============================================================================

MERGE_SCHEMA_VERSION = "rp1_fire_panel_consolidated_v2"
START_YYYYMM = 200101
END_YYYYMM = 202412
VIIRS_SUPPORT_START_YYYYMM = 201201
BA2012_SUPPORT_START_YYYYMM = 201201
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
DEFAULT_BA2001_ROOT_RELATIVE = Path("RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2001")
DEFAULT_BA2012_ROOT_RELATIVE = Path("RP1_Project/rp1_gee_ba_scripts/RP1_Project_MODIS_BA_c1_2012")
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


def build_paths_config(args: argparse.Namespace) -> PathsConfig:
    """Resolve all default and CLI-overridden paths used by the merger.

    All built-in defaults are interpreted relative to the canonical repository
    root while explicit path overrides remain available for reproducible batch
    or CI runs.
    """
    repo_root = infer_repo_root(args.repo_root)

    unit_universe_path = (
        Path(args.unit_universe).expanduser().resolve()
        if args.unit_universe
        else (repo_root / DEFAULT_UNIT_UNIVERSE_RELATIVE).resolve()
    )

    if args.af_root:
        af_root = Path(args.af_root).expanduser().resolve()
    else:
        default_af_root = (repo_root / DEFAULT_AF_ROOT_RELATIVE).resolve()
        af_root = default_af_root if default_af_root.exists() else (discover_unique_af_root(repo_root) or default_af_root)

    ba2001_root = (
        Path(args.ba2001_root).expanduser().resolve()
        if args.ba2001_root
        else (repo_root / DEFAULT_BA2001_ROOT_RELATIVE).resolve()
    )
    ba2012_root = (
        Path(args.ba2012_root).expanduser().resolve()
        if args.ba2012_root
        else (repo_root / DEFAULT_BA2012_ROOT_RELATIVE).resolve()
    )
    output_dir = (
        Path(args.output_dir).expanduser().resolve()
        if args.output_dir
        else (repo_root / DEFAULT_OUTPUT_DIR_RELATIVE).resolve()
    )

    return PathsConfig(
        repo_root=repo_root,
        unit_universe_path=unit_universe_path,
        af_root=af_root,
        ba2001_root=ba2001_root,
        ba2012_root=ba2012_root,
        output_dir=output_dir,
    )


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
    if counts.get("acz") != 5:
        fail(f"unit_universe: expected 5 ACZ rows, got {counts.get('acz')}")
    if counts.get("district") != 260:
        fail(f"unit_universe: expected 260 district rows, got {counts.get('district')}")

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
    if len(codes) != 5:
        fail(f"Expected 5 canonical ACZ partition codes, got {codes}")
    return codes


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

    expected_rows = 1440 if level == "acz" else 74880
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
            required_columns=BA_REQUIRED_COLUMNS,
            support_start_yyyymm=START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.ba2001_root,
            filename_required_token="rp1_ba_acz_",
            forbidden_filename_tokens=reject_tokens,
            source_present_column="ba2001_source_present",
        ),
        FamilySpec(
            family_name="ba2012_acz_base",
            level="acz",
            source_kind="ba2012",
            required_columns=BA_REQUIRED_COLUMNS,
            support_start_yyyymm=BA2012_SUPPORT_START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.ba2012_root,
            filename_required_token="rp1_ba_acz_",
            forbidden_filename_tokens=reject_tokens,
            source_present_column="ba2012_source_present",
        ),
        FamilySpec(
            family_name="ba2001_district_base",
            level="district",
            source_kind="ba2001",
            required_columns=BA_REQUIRED_COLUMNS,
            support_start_yyyymm=START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.ba2001_root,
            filename_required_token="rp1_ba_district_",
            forbidden_filename_tokens=reject_tokens,
            source_present_column="ba2001_source_present",
        ),
        FamilySpec(
            family_name="ba2012_district_base",
            level="district",
            source_kind="ba2012",
            required_columns=BA_REQUIRED_COLUMNS,
            support_start_yyyymm=BA2012_SUPPORT_START_YYYYMM,
            support_end_yyyymm=END_YYYYMM,
            root_dir=paths.ba2012_root,
            filename_required_token="rp1_ba_district_",
            forbidden_filename_tokens=reject_tokens,
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
    """Validate BA logic, denominator flags, fractions, and non-negativity."""
    out = df.copy()
    out["modis_burned_pixel_count"] = parse_int_series(out["modis_burned_pixel_count"], f"{context} :: modis_burned_pixel_count")
    out["modis_ba_any"] = parse_int_series(out["modis_ba_any"], f"{context} :: modis_ba_any")
    out["modis_zero_union_den_flag"] = parse_int_series(out["modis_zero_union_den_flag"], f"{context} :: modis_zero_union_den_flag")
    out["modis_zero_annual_den_flag"] = parse_int_series(out["modis_zero_annual_den_flag"], f"{context} :: modis_zero_annual_den_flag")

    for column in [
        "modis_ba_km2",
        "modis_aoi_area_land_km2",
        "modis_burnable_km2_union",
        "modis_burnable_km2_annual",
        "modis_burned_frac_union",
        "modis_burned_frac_annual",
    ]:
        out[column] = parse_float_series(out[column], f"{context} :: {column}")

    for column in [
        "modis_ba_km2",
        "modis_aoi_area_land_km2",
        "modis_burnable_km2_union",
        "modis_burnable_km2_annual",
        "modis_burned_frac_union",
        "modis_burned_frac_annual",
        "modis_burned_pixel_count",
    ]:
        bad_mask = out[column].notna() & (out[column] < 0)
        if bad_mask.any():
            sample = out.loc[bad_mask, ["unit_id", "yyyymm", column]].head(20)
            fail(f"{context}: negative values detected in {column}. Sample:\n{sample.to_string(index=False)}")

    for column in ["modis_ba_any", "modis_zero_union_den_flag", "modis_zero_annual_den_flag"]:
        bad_mask = out[column].notna() & ~out[column].isin([0, 1])
        if bad_mask.any():
            sample = out.loc[bad_mask, ["unit_id", "yyyymm", column]].head(20)
            fail(f"{context}: {column} must be binary 0/1. Sample:\n{sample.to_string(index=False)}")

    union_valid = out["modis_burnable_km2_union"].notna() & (out["modis_burnable_km2_union"] > 0)
    annual_valid = out["modis_burnable_km2_annual"].notna() & (out["modis_burnable_km2_annual"] > 0)
    union_frac_bad = union_valid & out["modis_burned_frac_union"].notna() & ~out["modis_burned_frac_union"].between(0.0, 1.0)
    annual_frac_bad = annual_valid & out["modis_burned_frac_annual"].notna() & ~out["modis_burned_frac_annual"].between(0.0, 1.0)
    if union_frac_bad.any():
        sample = out.loc[union_frac_bad, ["unit_id", "yyyymm", "modis_burned_frac_union"]].head(20)
        fail(
            f"{context}: modis_burned_frac_union outside [0, 1] when denominator is valid. "
            f"Sample:\n{sample.to_string(index=False)}"
        )
    if annual_frac_bad.any():
        sample = out.loc[annual_frac_bad, ["unit_id", "yyyymm", "modis_burned_frac_annual"]].head(20)
        fail(
            f"{context}: modis_burned_frac_annual outside [0, 1] when denominator is valid. "
            f"Sample:\n{sample.to_string(index=False)}"
        )

    ba_any_bad = ((out["modis_ba_km2"] > 0) & (out["modis_ba_any"] != 1)) | (
        (out["modis_ba_km2"] == 0) & (out["modis_ba_any"] != 0)
    )
    if ba_any_bad.any():
        sample = out.loc[ba_any_bad, ["unit_id", "yyyymm", "modis_ba_km2", "modis_ba_any"]].head(20)
        fail(f"{context}: modis_ba_any is inconsistent with modis_ba_km2. Sample:\n{sample.to_string(index=False)}")

    return out


def validate_file_lineage(df: pd.DataFrame, context: str) -> tuple[str, str]:
    """Require each source file to declare exactly one non-null run_id and schema_version."""
    run_ids = sorted({str(v).strip() for v in df["run_id"].dropna().tolist() if str(v).strip()})
    schema_versions = sorted({str(v).strip() for v in df["schema_version"].dropna().tolist() if str(v).strip()})
    if len(run_ids) != 1:
        fail(f"{context}: expected exactly one non-null run_id in the file, got {run_ids}")
    if len(schema_versions) != 1:
        fail(f"{context}: expected exactly one non-null schema_version in the file, got {schema_versions}")
    return run_ids[0], schema_versions[0]


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


def load_family(
    spec: FamilySpec,
    unit_universe: pd.DataFrame,
    spine: pd.DataFrame,
    partition_codes: Sequence[str],
    paths: PathsConfig,
) -> LoadedFamily:
    """
    Load, validate, and concatenate one source family.

    Each family is validated in isolation before merge. This is where schema
    drift, wrong folders, duplicate keys, and support-window confusion are
    stopped early with clear errors.
    """
    files = discover_family_files(spec, partition_codes, paths.repo_root)
    frames: list[pd.DataFrame] = []
    inventory_rows: list[dict[str, Any]] = []
    family_schema_versions: list[str] = []
    family_run_ids: list[str] = []

    canonical_units = unit_universe.loc[unit_universe["level"] == spec.level, IDENTITY_COLUMNS].copy()

    for path in files:
        context = f"{spec.family_name} :: {relative_to_repo(path, paths.repo_root)}"
        raw = read_csv_strict(path)
        raw = require_columns_and_reorder(raw, spec.required_columns, context, allow_extra=False)
        raw = clean_string_columns(raw, raw.columns)
        for column in ["parent_level", "parent_id", "parent_code", "parent_name"]:
            raw[column] = blank_to_na(raw[column])

        run_id, schema_version = validate_file_lineage(raw, context)
        family_run_ids.append(run_id)
        family_schema_versions.append(schema_version)

        raw = validate_time_columns(raw, spec, context)
        validate_key_uniqueness(raw, MERGE_KEY, context)
        validate_source_identity_against_canonical(raw, canonical_units, spec, context)

        if spec.source_kind == "modis_af":
            typed = validate_af_content(raw, "modis", context)
        elif spec.source_kind == "viirs_af":
            typed = validate_af_content(raw, "viirs", context)
        else:
            typed = validate_ba_content(raw, context)

        inventory_rows.append(
            {
                "family_name": spec.family_name,
                "source_kind": spec.source_kind,
                "level": spec.level,
                "partition_code": extract_partition_code(path, partition_codes),
                "origin_path": relative_to_repo(path, paths.repo_root),
                "staged_path": relative_to_repo(path, paths.repo_root),
                "sha256": sha256_file(path),
                "row_count": int(len(typed)),
                "yyyymm_min": int(typed["yyyymm"].min()),
                "yyyymm_max": int(typed["yyyymm"].max()),
                "run_id": run_id,
                "schema_version": schema_version,
            }
        )
        frames.append(typed)

    data = pd.concat(frames, ignore_index=True)
    validate_key_uniqueness(data, MERGE_KEY, f"{spec.family_name} :: concatenated family")

    family_schema_versions = sorted(set(family_schema_versions))
    if len(family_schema_versions) != 1:
        fail(f"{spec.family_name}: inconsistent schema_version across files: {family_schema_versions}")

    validate_supported_key_coverage(
        data,
        expected_supported_keys(spine, spec.support_start_yyyymm, spec.support_end_yyyymm),
        f"{spec.family_name} :: supported-key audit",
    )

    return LoadedFamily(
        spec=spec,
        files=files,
        data=data.sort_values(MERGE_KEY).reset_index(drop=True),
        run_ids=sorted(set(family_run_ids)),
        schema_version=family_schema_versions[0],
        file_inventory_rows=inventory_rows,
    )


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

    expected_rows = 1440 if level == "acz" else 74880
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
        "modis_burned_frac_annual_ba2001",
        "modis_burned_frac_union_ba2012",
        "modis_burned_frac_annual_ba2012",
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
        ("acz", acz_panel, 1440),
        ("district", district_panel, 74880),
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
        "merge_schema_version": MERGE_SCHEMA_VERSION,
        "written_at_utc": stable_now_iso(),
        "repo_root": ".",
        "provenance_schema_version": PROVENANCE_SCHEMA_VERSION,
        "path_semantics": PROVENANCE_PATH_SEMANTICS,
        "source_roots": {
            "unit_universe": {
                "origin_path": relative_to_repo(paths.unit_universe_path, paths.repo_root),
                "staged_path": relative_to_repo(paths.unit_universe_path, paths.repo_root),
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


def build_merge_summary(
    merge_run_id: str,
    acz_panel: pd.DataFrame,
    district_panel: pd.DataFrame,
) -> dict[str, Any]:
    """Build a concise summary JSON for rapid audit review."""
    def level_block(panel: pd.DataFrame) -> dict[str, Any]:
        return {
            "row_count": int(len(panel)),
            "column_count": int(panel.shape[1]),
            "yyyymm_min": int(panel["yyyymm"].min()),
            "yyyymm_max": int(panel["yyyymm"].max()),
            "unique_units": int(panel["unit_id"].nunique()),
            "viirs_structural_missing_rows": int(panel["viirs_structural_missing_flag"].fillna(0).astype(int).sum()),
            "ba2012_structural_missing_rows": int(panel["ba2012_structural_missing_flag"].fillna(0).astype(int).sum()),
            "viirs_supported_rows": int(panel["viirs_supported_flag"].fillna(0).astype(int).sum()),
            "ba2012_supported_rows": int(panel["ba2012_supported_flag"].fillna(0).astype(int).sum()),
        }

    return {
        "merge_run_id": merge_run_id,
        "merge_schema_version": MERGE_SCHEMA_VERSION,
        "acz": level_block(acz_panel),
        "district": level_block(district_panel),
    }


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


def run(paths: PathsConfig, merge_run_id: str) -> dict[str, Path]:
    """Execute the full merger workflow and write all primary outputs."""
    ensure_directory(paths.output_dir)

    unit_universe = load_unit_universe(paths)
    partition_codes = canonical_partition_codes(unit_universe)
    spines = {level: build_canonical_spine(unit_universe, level) for level in SUPPORTED_LEVELS}

    family_specs = build_family_specs(paths)
    loaded_families = [
        load_family(spec, unit_universe, spines[spec.level], partition_codes, paths)
        for spec in family_specs
    ]
    families_by_name = {family.spec.family_name: family for family in loaded_families}

    acz_panel = build_level_panel("acz", spines["acz"], families_by_name, merge_run_id)
    district_panel = build_level_panel("district", spines["district"], families_by_name, merge_run_id)

    output_paths = {
        "fire_panel_acz": paths.output_dir / "fire_panel_acz_monthly_consolidated_2001_2024.csv",
        "fire_panel_district": paths.output_dir / "fire_panel_district_monthly_consolidated_2001_2024.csv",
        "key_audit": paths.output_dir / "fire_panel_key_audit.csv",
        "manifest": paths.output_dir / "fire_panel_manifest.json",
        "merge_summary": paths.output_dir / "fire_panel_merge_summary.json",
    }

    write_csv(acz_panel, output_paths["fire_panel_acz"])
    write_csv(district_panel, output_paths["fire_panel_district"])
    write_csv(build_key_audit(acz_panel, district_panel), output_paths["key_audit"])

    # Write the merge summary first so the manifest can hash it deterministically.
    write_json(build_merge_summary(merge_run_id, acz_panel, district_panel), output_paths["merge_summary"])

    # Write the manifest last. It does not hash itself before write time.
    write_json(build_manifest(paths, merge_run_id, loaded_families, output_paths), output_paths["manifest"])

    return output_paths


# =============================================================================
# CLI
# =============================================================================


def build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line interface for the standalone merger script."""
    parser = argparse.ArgumentParser(
        description="Merge governed AF and BA source families into final consolidated RP1 fire panels."
    )
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
        help="Root directory of BA-2001 base exports.",
    )
    parser.add_argument(
        "--ba2012-root",
        default=None,
        help="Root directory of BA-2012 base exports.",
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
    paths = build_paths_config(args)

    try:
        run(paths, merge_run_id)
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
