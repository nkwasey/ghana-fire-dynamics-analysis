# file: tests/test_schema_contracts.py
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from mv_firms_panels.core.config import load_config
from mv_firms_panels.core.schema import (
    SchemaValidationError,
    load_json_schema,
    validate_dataframe_against_schema,
)
from mv_firms_panels.stages.af_exports import af_base_column_order, af_ext_column_order


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _sensorise_columns(columns: list[str], sensor_mode: str) -> list[str]:
    prefix = f"{sensor_mode}_"
    return [prefix + c[len("viirs_") :] if c.startswith("viirs_") else c for c in columns]


def test_fires_canonical_schema_validation_passes_minimal_row() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config

    schema = load_json_schema(root / cfg.outputs.schemas["fires_canonical"])
    expected_cols = cfg.determinism.column_order["fires_canonical"]

    df = pd.DataFrame(
        [
            {
                "run_id": "ghana_v1.0",
                "source_file": "VIIRS_2014.shp",
                "sensor": "viirs",
                "level": "admin2",
                "unit_id": "001",
                "acq_datetime_utc": "2014-01-01T12:34:00Z",
                "acq_date": "2014-01-01",
                "acq_time_utc": "1234",
                "yyyymm": 201401,
                "date_utc": "2014-01-01",
                "latitude": 6.123456,
                "longitude": -1.234567,
                "conf_cat": "n",
                "frp_mw": 10.5,
                "daynight": "D",
                "satellite": "N",
                "type": 0,
                "dedup_key": "k1",
                "was_dedup_kept": True,
            }
        ]
    )

    df = df[expected_cols[::-1]]
    out = validate_dataframe_against_schema(
        df, schema, expected_columns=expected_cols, allow_reorder=True
    )
    assert list(out.columns) == list(expected_cols)


def test_panel_monthly_schema_validation_passes_with_null_mean_when_no_days() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config

    schema = load_json_schema(root / cfg.outputs.schemas["panel_monthly"])
    expected_cols = cfg.determinism.column_order["panel_monthly"]

    df = pd.DataFrame(
        [
            {
                "run_id": "ghana_v1.0",
                "level": "admin2",
                "unit_id": "001",
                "unit_name": "Example",
                "yyyymm": 201401,
                "year": 2014,
                "month": 1,
                "viirs_det_low": 0,
                "viirs_det_nominal": 0,
                "viirs_det_high": 0,
                "viirs_det_nh": 0,
                "viirs_frp_active_days": 0,
                "viirs_frp_sum_daily_max_mw": 0.0,
                "viirs_frp_mean_mw": None,
                "modis_det_low": 0,
                "modis_det_nominal": 0,
                "modis_det_high": 0,
                "modis_det_nh": 0,
                "modis_frp_active_days": 0,
                "modis_frp_sum_daily_max_mw": 0.0,
                "modis_frp_mean_mw": None,
            }
        ]
    )

    out = validate_dataframe_against_schema(
        df, schema, expected_columns=expected_cols, allow_reorder=True
    )
    assert list(out.columns) == list(expected_cols)


def test_panel_monthly_schema_accepts_nulls_for_structural_missingness() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config

    schema = load_json_schema(root / cfg.outputs.schemas["panel_monthly"])
    expected_cols = cfg.determinism.column_order["panel_monthly"]

    df = pd.DataFrame(
        [
            {
                "run_id": "ghana_v1.0",
                "level": "admin2",
                "unit_id": "001",
                "unit_name": "Example",
                "yyyymm": 200001,
                "year": 2000,
                "month": 1,
                "viirs_det_low": None,
                "viirs_det_nominal": None,
                "viirs_det_high": None,
                "viirs_det_nh": None,
                "viirs_frp_active_days": None,
                "viirs_frp_sum_daily_max_mw": None,
                "viirs_frp_mean_mw": None,
                "modis_det_low": 0,
                "modis_det_nominal": 0,
                "modis_det_high": 0,
                "modis_det_nh": 0,
                "modis_frp_active_days": 0,
                "modis_frp_sum_daily_max_mw": 0.0,
                "modis_frp_mean_mw": None,
            }
        ]
    )

    out = validate_dataframe_against_schema(
        df, schema, expected_columns=expected_cols, allow_reorder=True
    )
    assert list(out.columns) == list(expected_cols)


def test_rp1_af_monthly_base_viirs_schema_validation_passes() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config

    schema_rel = cfg.outputs.rp1_exports.sensors["viirs"].schemas.base
    schema = load_json_schema(root / schema_rel)
    expected_cols = af_base_column_order()

    df = pd.DataFrame(
        [
            {
                "run_id": "ghana_v1.0",
                "schema_version": "rp1_af_monthly_v2",
                "level": "district",
                "unit_id": "D1",
                "unit_code": None,
                "unit_name": "District 1",
                "parent_level": "acz",
                "parent_id": "coastal_zone",
                "parent_code": "CZ",
                "parent_name": "COASTAL ZONE",
                "yyyymm": 201401,
                "year": 2014,
                "month": 1,
                "viirs_det_low": 1,
                "viirs_det_nominal": 2,
                "viirs_det_high": 1,
                "viirs_det_all": 4,
                "viirs_det_nh": 3,
                "viirs_pct_high_conf": 25.0,
                "viirs_days_active_nh": 1,
                "viirs_streak_max_nh": 1,
                "viirs_frp_active_days": 1,
                "viirs_frp_sum_daily_max_mw": 5.0,
                "viirs_frp_mean_mw": 5.0,
                "viirs_frp_p95_daily_max_mw": 5.0,
            }
        ]
    )

    out = validate_dataframe_against_schema(
        df[expected_cols[::-1]], schema, expected_columns=expected_cols, allow_reorder=True
    )
    assert list(out.columns) == expected_cols


def test_rp1_af_monthly_ext_viirs_schema_validation_passes_with_qc_and_provenance() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config

    schema_rel = cfg.outputs.rp1_exports.sensors["viirs"].schemas.ext
    schema = load_json_schema(root / schema_rel)
    expected_cols = af_ext_column_order()

    df = pd.DataFrame(
        [
            {
                "run_id": "ghana_v1.0",
                "schema_version": "rp1_af_monthly_v2",
                "level": "district",
                "unit_id": "D1",
                "unit_code": None,
                "unit_name": "District 1",
                "parent_level": "acz",
                "parent_id": "coastal_zone",
                "parent_code": "CZ",
                "parent_name": "COASTAL ZONE",
                "yyyymm": 201401,
                "year": 2014,
                "month": 1,
                "viirs_det_low": 0,
                "viirs_det_nominal": 0,
                "viirs_det_high": 0,
                "viirs_det_all": 0,
                "viirs_det_nh": 0,
                "viirs_pct_high_conf": None,
                "viirs_days_active_nh": 0,
                "viirs_streak_max_nh": 0,
                "viirs_frp_active_days": 0,
                "viirs_frp_sum_daily_max_mw": 0.0,
                "viirs_frp_mean_mw": None,
                "viirs_frp_p95_daily_max_mw": None,
                "viirs_has_any": False,
                "viirs_in_coverage_flag": True,
                "viirs_structural_missing_flag": False,
                "viirs_low_information_month_flag": True,
                "viirs_frp_ok_flag": False,
                "sensor_coverage_start_yyyymm": 201201,
                "sensor_coverage_end_yyyymm": None,
                "year_rows_in_panel": 12,
                "year_rows_in_sensor_coverage": 12,
                "year_rows_structural_missing": 0,
                "year_coverage_complete_flag": True,
            }
        ]
    )

    out = validate_dataframe_against_schema(
        df[expected_cols[::-1]], schema, expected_columns=expected_cols, allow_reorder=True
    )
    assert list(out.columns) == expected_cols


def test_rp1_af_monthly_base_modis_schema_validation_passes() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config

    schema_rel = cfg.outputs.rp1_exports.sensors["modis"].schemas.base
    schema = load_json_schema(root / schema_rel)
    expected_cols = _sensorise_columns(af_base_column_order(), sensor_mode="modis")

    df = pd.DataFrame(
        [
            {
                "run_id": "ghana_v1.0",
                "schema_version": "rp1_af_monthly_v2",
                "level": "district",
                "unit_id": "D1",
                "unit_code": None,
                "unit_name": "District 1",
                "parent_level": "acz",
                "parent_id": "coastal_zone",
                "parent_code": "CZ",
                "parent_name": "COASTAL ZONE",
                "yyyymm": 200101,
                "year": 2001,
                "month": 1,
                "modis_det_low": 1,
                "modis_det_nominal": 2,
                "modis_det_high": 1,
                "modis_det_all": 4,
                "modis_det_nh": 3,
                "modis_pct_high_conf": 25.0,
                "modis_days_active_nh": 1,
                "modis_streak_max_nh": 1,
                "modis_frp_active_days": 1,
                "modis_frp_sum_daily_max_mw": 5.0,
                "modis_frp_mean_mw": 5.0,
                "modis_frp_p95_daily_max_mw": 5.0,
            }
        ]
    )

    out = validate_dataframe_against_schema(
        df[expected_cols[::-1]], schema, expected_columns=expected_cols, allow_reorder=True
    )
    assert list(out.columns) == expected_cols


def test_rp1_af_monthly_ext_modis_schema_validation_passes_with_qc_and_provenance() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config

    schema_rel = cfg.outputs.rp1_exports.sensors["modis"].schemas.ext
    schema = load_json_schema(root / schema_rel)
    expected_cols = _sensorise_columns(af_ext_column_order(), sensor_mode="modis")

    df = pd.DataFrame(
        [
            {
                "run_id": "ghana_v1.0",
                "schema_version": "rp1_af_monthly_v2",
                "level": "district",
                "unit_id": "D1",
                "unit_code": None,
                "unit_name": "District 1",
                "parent_level": "acz",
                "parent_id": "coastal_zone",
                "parent_code": "CZ",
                "parent_name": "COASTAL ZONE",
                "yyyymm": 200101,
                "year": 2001,
                "month": 1,
                "modis_det_low": 0,
                "modis_det_nominal": 0,
                "modis_det_high": 0,
                "modis_det_all": 0,
                "modis_det_nh": 0,
                "modis_pct_high_conf": None,
                "modis_days_active_nh": 0,
                "modis_streak_max_nh": 0,
                "modis_frp_active_days": 0,
                "modis_frp_sum_daily_max_mw": 0.0,
                "modis_frp_mean_mw": None,
                "modis_frp_p95_daily_max_mw": None,
                "modis_has_any": False,
                "modis_in_coverage_flag": True,
                "modis_structural_missing_flag": False,
                "modis_low_information_month_flag": True,
                "modis_frp_ok_flag": False,
                "sensor_coverage_start_yyyymm": 200101,
                "sensor_coverage_end_yyyymm": None,
                "year_rows_in_panel": 12,
                "year_rows_in_sensor_coverage": 12,
                "year_rows_structural_missing": 0,
                "year_coverage_complete_flag": True,
            }
        ]
    )

    out = validate_dataframe_against_schema(
        df[expected_cols[::-1]], schema, expected_columns=expected_cols, allow_reorder=True
    )
    assert list(out.columns) == expected_cols


def test_rp1_af_viirs_schema_rejects_forbidden_acz_specific_column() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config

    schema_rel = cfg.outputs.rp1_exports.sensors["viirs"].schemas.base
    schema = load_json_schema(root / schema_rel)
    expected_cols = af_base_column_order()

    df = pd.DataFrame([{c: None for c in expected_cols}])
    df["run_id"] = "ghana_v1.0"
    df["schema_version"] = "rp1_af_monthly_v2"
    df["level"] = "acz"
    df["unit_id"] = "zone_1"
    df["unit_name"] = "Zone 1"
    df["yyyymm"] = 201401
    df["year"] = 2014
    df["month"] = 1
    df["acz_code"] = "CZ"

    with pytest.raises(SchemaValidationError):
        validate_dataframe_against_schema(
            df, schema, expected_columns=expected_cols, allow_reorder=True
        )


def test_rp1_af_modis_schema_rejects_viirs_prefixed_column() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config

    schema_rel = cfg.outputs.rp1_exports.sensors["modis"].schemas.base
    schema = load_json_schema(root / schema_rel)
    expected_cols = _sensorise_columns(af_base_column_order(), sensor_mode="modis")

    df = pd.DataFrame([{c: None for c in expected_cols}])
    df["run_id"] = "ghana_v1.0"
    df["schema_version"] = "rp1_af_monthly_v2"
    df["level"] = "acz"
    df["unit_id"] = "zone_1"
    df["unit_name"] = "Zone 1"
    df["yyyymm"] = 200101
    df["year"] = 2001
    df["month"] = 1
    df["viirs_det_nh"] = 1

    with pytest.raises(SchemaValidationError):
        validate_dataframe_against_schema(
            df, schema, expected_columns=expected_cols, allow_reorder=True
        )


def test_extra_column_rejected() -> None:
    root = _repo_root()
    cfg = load_config(root / "configs" / "example_project.yaml", validate_paths=False).config
    schema = load_json_schema(root / cfg.outputs.schemas["fires_canonical"])
    expected_cols = cfg.determinism.column_order["fires_canonical"]

    df = pd.DataFrame([{c: None for c in expected_cols}])
    df["extra"] = 1

    with pytest.raises(SchemaValidationError):
        validate_dataframe_against_schema(
            df, schema, expected_columns=expected_cols, allow_reorder=True
        )
