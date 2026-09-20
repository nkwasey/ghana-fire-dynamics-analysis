# file: tests/test_af_exports.py
"""Tests for the merger-ready RP1 AF export family.

These tests lock the dual-sensor execution behaviour:
- generic Stage 1 identity fields in the canonical CSV schema
- sensor-specific analytical blocks for both VIIRS and MODIS
- base vs `_ext` ordering guarantees
- generic top-level partitioning derived from unit_universe rather than ACZ-only logic
- sensor-specific RP1 window reporting and deterministic `*_det_all` derivation
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import yaml
from mv_firms_panels.core.config import load_config
from mv_firms_panels.io.paths import build_run_dir, rp1_af_export_path
from mv_firms_panels.stages.af_exports import af_base_column_order, af_ext_column_order
from mv_firms_panels.stages.combine_panels import combine_panels

FORBIDDEN_CANONICAL_COLUMNS = {
    "sensor_mode",
    "acz_id",
    "acz_code",
    "acz_name",
    "parent_unit_id",
    "parent_unit_code",
    "parent_unit_name",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_cfg(tmp_repo: Path):
    src_repo = _repo_root()
    (tmp_repo / "configs" / "schemas").mkdir(parents=True, exist_ok=True)

    shutil.copy(
        src_repo / "configs" / "example_project.yaml", tmp_repo / "configs" / "example_project.yaml"
    )
    for name in [
        "panel_monthly.schema.json",
        "rp1_af_monthly_base_viirs.schema.json",
        "rp1_af_monthly_ext_viirs.schema.json",
        "rp1_af_monthly_base_modis.schema.json",
        "rp1_af_monthly_ext_modis.schema.json",
    ]:
        shutil.copy(
            src_repo / "configs" / "schemas" / name, tmp_repo / "configs" / "schemas" / name
        )

    cfg_path = tmp_repo / "configs" / "example_project.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    raw["outputs"]["base_dir"] = "out/runs"
    raw["outputs"]["write_formats"]["monthly_panels"] = ["csv"]
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return load_config(cfg_path, validate_paths=False, repo_root=tmp_repo).config


def _unit_universe() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "level": "acz",
                "unit_id": "coastal_zone",
                "unit_code": "CZ",
                "unit_name": "COASTAL ZONE",
                "parent_level": pd.NA,
                "parent_id": pd.NA,
                "parent_code": pd.NA,
                "parent_name": pd.NA,
            },
            {
                "level": "acz",
                "unit_id": "forest_zone",
                "unit_code": "FZ",
                "unit_name": "FOREST ZONE",
                "parent_level": pd.NA,
                "parent_id": pd.NA,
                "parent_code": pd.NA,
                "parent_name": pd.NA,
            },
            {
                "level": "district",
                "unit_id": "D1",
                "unit_code": pd.NA,
                "unit_name": "District 1",
                "parent_level": "acz",
                "parent_id": "coastal_zone",
                "parent_code": "CZ",
                "parent_name": "COASTAL ZONE",
            },
            {
                "level": "district",
                "unit_id": "D2",
                "unit_code": pd.NA,
                "unit_name": "District 2",
                "parent_level": "acz",
                "parent_id": "forest_zone",
                "parent_code": "FZ",
                "parent_name": "FOREST ZONE",
            },
        ]
    )


def _sensor_rows(prefix: str) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "level": "district",
                "unit_id": "D1",
                "yyyymm": 202401,
                f"{prefix}_det_low": 1,
                f"{prefix}_det_nominal": 2,
                f"{prefix}_det_high": 1,
                f"{prefix}_det_nh": 3,
                f"{prefix}_frp_active_days": 1,
                f"{prefix}_frp_sum_daily_max_mw": 9.0,
                f"{prefix}_frp_mean_mw": 9.0,
                f"{prefix}_pct_high_conf": 25.0,
                f"{prefix}_days_active_nh": 1,
                f"{prefix}_streak_max_nh": 1,
                f"{prefix}_frp_p95_daily_max_mw": 9.0,
            },
            {
                "level": "acz",
                "unit_id": "coastal_zone",
                "yyyymm": 202401,
                f"{prefix}_det_low": 3,
                f"{prefix}_det_nominal": 4,
                f"{prefix}_det_high": 1,
                f"{prefix}_det_nh": 5,
                f"{prefix}_frp_active_days": 2,
                f"{prefix}_frp_sum_daily_max_mw": 14.0,
                f"{prefix}_frp_mean_mw": 7.0,
                f"{prefix}_pct_high_conf": 20.0,
                f"{prefix}_days_active_nh": 2,
                f"{prefix}_streak_max_nh": 2,
                f"{prefix}_frp_p95_daily_max_mw": 8.5,
            },
        ]
    )


def test_rp1_af_exports_use_locked_dual_sensor_base_and_ext_contract(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir(parents=True, exist_ok=True)
    cfg = _load_cfg(tmp_repo)
    run_id = "af_exports"

    res = combine_panels(
        cfg=cfg,
        repo_root=tmp_repo,
        run_id=run_id,
        unit_universe_df=_unit_universe(),
        viirs_monthly_df=_sensor_rows("viirs"),
        modis_monthly_df=_sensor_rows("modis"),
        start_yyyymm=202401,
        end_yyyymm=202402,
        write_outputs=True,
        validate_schema=True,
        write_extended_metrics=True,
    )
    assert res.manifest_path is not None

    manifest = yaml.safe_load(res.manifest_path.read_text(encoding="utf-8"))
    af_manifest = manifest["rp1_af_exports"]
    assert af_manifest["family_name"] == "rp1_af_exports"
    assert af_manifest["source"] == ["panel_monthly_ext", "panel_monthly_qc", "unit_universe"]
    assert af_manifest["merge_keys"] == ["level", "unit_id", "yyyymm"]
    assert af_manifest["families"] == ["base", "ext"]
    assert af_manifest["schema_version"] == "rp1_af_monthly_v2"
    assert set(af_manifest["sensor_modes"].keys()) == {"viirs", "modis"}
    assert af_manifest["sensor_modes"]["viirs"]["window"] == {
        "start_yyyymm": 201201,
        "end_yyyymm": 202412,
    }
    assert af_manifest["sensor_modes"]["modis"]["window"] == {
        "start_yyyymm": 200101,
        "end_yyyymm": 202412,
    }

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
    )

    viirs_base_acz_path = rp1_af_export_path(
        run_dir=run_dir,
        level="acz",
        sensor_mode="viirs",
        partition_key="acz_code",
        partition_value="CZ",
        fmt="csv",
        family="base",
    )
    viirs_base_district_path = rp1_af_export_path(
        run_dir=run_dir,
        level="district",
        sensor_mode="viirs",
        partition_key="acz_code",
        partition_value="CZ",
        fmt="csv",
        family="base",
    )
    viirs_ext_district_path = rp1_af_export_path(
        run_dir=run_dir,
        level="district",
        sensor_mode="viirs",
        partition_key="acz_code",
        partition_value="CZ",
        fmt="csv",
        family="ext",
    )
    modis_base_acz_path = rp1_af_export_path(
        run_dir=run_dir,
        level="acz",
        sensor_mode="modis",
        partition_key="acz_code",
        partition_value="CZ",
        fmt="csv",
        family="base",
    )
    modis_base_district_path = rp1_af_export_path(
        run_dir=run_dir,
        level="district",
        sensor_mode="modis",
        partition_key="acz_code",
        partition_value="CZ",
        fmt="csv",
        family="base",
    )
    modis_ext_district_path = rp1_af_export_path(
        run_dir=run_dir,
        level="district",
        sensor_mode="modis",
        partition_key="acz_code",
        partition_value="CZ",
        fmt="csv",
        family="ext",
    )

    for path in [
        viirs_base_acz_path,
        viirs_base_district_path,
        viirs_ext_district_path,
        modis_base_acz_path,
        modis_base_district_path,
        modis_ext_district_path,
    ]:
        assert path.exists()

    viirs_base_acz_df = pd.read_csv(viirs_base_acz_path)
    viirs_base_district_df = pd.read_csv(viirs_base_district_path)
    viirs_ext_district_df = pd.read_csv(viirs_ext_district_path)
    modis_base_acz_df = pd.read_csv(modis_base_acz_path)
    modis_base_district_df = pd.read_csv(modis_base_district_path)
    modis_ext_district_df = pd.read_csv(modis_ext_district_path)

    assert list(viirs_base_acz_df.columns) == af_base_column_order("viirs")
    assert list(viirs_base_district_df.columns) == af_base_column_order("viirs")
    assert list(viirs_ext_district_df.columns) == af_ext_column_order("viirs")
    assert list(
        viirs_ext_district_df.columns[: len(af_base_column_order("viirs"))]
    ) == af_base_column_order("viirs")

    assert list(modis_base_acz_df.columns) == af_base_column_order("modis")
    assert list(modis_base_district_df.columns) == af_base_column_order("modis")
    assert list(modis_ext_district_df.columns) == af_ext_column_order("modis")
    assert list(
        modis_ext_district_df.columns[: len(af_base_column_order("modis"))]
    ) == af_base_column_order("modis")

    assert not viirs_ext_district_df.duplicated(["level", "unit_id", "yyyymm"]).any()
    assert not modis_ext_district_df.duplicated(["level", "unit_id", "yyyymm"]).any()

    assert not (FORBIDDEN_CANONICAL_COLUMNS & set(viirs_base_district_df.columns))
    assert not (FORBIDDEN_CANONICAL_COLUMNS & set(modis_base_district_df.columns))
    assert set(viirs_base_acz_df["level"].unique().tolist()) == {"acz"}
    assert set(viirs_base_district_df["level"].unique().tolist()) == {"district"}
    assert set(modis_base_acz_df["level"].unique().tolist()) == {"acz"}
    assert set(modis_base_district_df["level"].unique().tolist()) == {"district"}

    # Top-level rows preserve blank parent fields from Stage 1 rather than self-parenting.
    top_row = viirs_base_acz_df.loc[viirs_base_acz_df["unit_id"] == "coastal_zone"].iloc[0]
    assert pd.isna(top_row["parent_level"])
    assert pd.isna(top_row["parent_id"])
    assert pd.isna(top_row["parent_code"])
    assert pd.isna(top_row["parent_name"])

    # Child rows carry non-blank parent linkage and blank unit_code when upstream metadata is blank.
    viirs_child_row = viirs_base_district_df.loc[viirs_base_district_df["yyyymm"] == 202401].iloc[0]
    assert viirs_child_row["parent_level"] == "acz"
    assert viirs_child_row["parent_id"] == "coastal_zone"
    assert viirs_child_row["parent_code"] == "CZ"
    assert viirs_child_row["parent_name"] == "COASTAL ZONE"
    assert pd.isna(viirs_child_row["unit_code"])

    modis_child_row = modis_base_district_df.loc[modis_base_district_df["yyyymm"] == 202401].iloc[0]
    assert modis_child_row["parent_level"] == "acz"
    assert modis_child_row["parent_id"] == "coastal_zone"
    assert modis_child_row["parent_code"] == "CZ"
    assert modis_child_row["parent_name"] == "COASTAL ZONE"
    assert pd.isna(modis_child_row["unit_code"])

    # Rich analytical fields are present and det_all is derived deterministically for both sensors.
    assert viirs_child_row["viirs_det_low"] == 1
    assert viirs_child_row["viirs_det_nominal"] == 2
    assert viirs_child_row["viirs_det_high"] == 1
    assert viirs_child_row["viirs_det_all"] == 4
    assert viirs_child_row["viirs_pct_high_conf"] == 25.0
    assert viirs_child_row["viirs_days_active_nh"] == 1
    assert viirs_child_row["viirs_streak_max_nh"] == 1
    assert viirs_child_row["viirs_frp_p95_daily_max_mw"] == 9.0

    assert modis_child_row["modis_det_low"] == 1
    assert modis_child_row["modis_det_nominal"] == 2
    assert modis_child_row["modis_det_high"] == 1
    assert modis_child_row["modis_det_all"] == 4
    assert modis_child_row["modis_pct_high_conf"] == 25.0
    assert modis_child_row["modis_days_active_nh"] == 1
    assert modis_child_row["modis_streak_max_nh"] == 1
    assert modis_child_row["modis_frp_p95_daily_max_mw"] == 9.0

    # Balanced-combined provenance: 202402 is absent in sparse inputs but present in both RP1 export families.
    viirs_balanced_row = viirs_ext_district_df.loc[viirs_ext_district_df["yyyymm"] == 202402].iloc[
        0
    ]
    assert viirs_balanced_row["unit_id"] == "D1"
    assert viirs_balanced_row["viirs_det_low"] == 0
    assert viirs_balanced_row["viirs_det_nominal"] == 0
    assert viirs_balanced_row["viirs_det_high"] == 0
    assert viirs_balanced_row["viirs_det_all"] == 0
    assert viirs_balanced_row["viirs_det_nh"] == 0
    assert pd.isna(viirs_balanced_row["viirs_pct_high_conf"])
    assert bool(viirs_balanced_row["viirs_in_coverage_flag"]) is True
    assert bool(viirs_balanced_row["viirs_structural_missing_flag"]) is False

    modis_balanced_row = modis_ext_district_df.loc[modis_ext_district_df["yyyymm"] == 202402].iloc[
        0
    ]
    assert modis_balanced_row["unit_id"] == "D1"
    assert modis_balanced_row["modis_det_low"] == 0
    assert modis_balanced_row["modis_det_nominal"] == 0
    assert modis_balanced_row["modis_det_high"] == 0
    assert modis_balanced_row["modis_det_all"] == 0
    assert modis_balanced_row["modis_det_nh"] == 0
    assert pd.isna(modis_balanced_row["modis_pct_high_conf"])
    assert bool(modis_balanced_row["modis_in_coverage_flag"]) is True
    assert bool(modis_balanced_row["modis_structural_missing_flag"]) is False


def test_rp1_af_forest_partition_is_written_generically_for_both_sensors(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir(parents=True, exist_ok=True)
    cfg = _load_cfg(tmp_repo)

    combine_panels(
        cfg=cfg,
        repo_root=tmp_repo,
        run_id="forest_partition",
        unit_universe_df=_unit_universe(),
        viirs_monthly_df=_sensor_rows("viirs"),
        modis_monthly_df=_sensor_rows("modis"),
        start_yyyymm=202401,
        end_yyyymm=202402,
        write_outputs=True,
        validate_schema=True,
        write_extended_metrics=True,
    )

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg.outputs.base_dir, run_id="forest_partition"
    )
    for sensor_mode in ["viirs", "modis"]:
        forest_path = rp1_af_export_path(
            run_dir=run_dir,
            level="district",
            sensor_mode=sensor_mode,
            partition_key="acz_code",
            partition_value="FZ",
            fmt="csv",
            family="ext",
        )
        assert forest_path.exists()
        forest_df = pd.read_csv(forest_path)
        assert set(forest_df["unit_id"].unique().tolist()) == {"D2"}
        assert set(forest_df["yyyymm"].tolist()) == {202401, 202402}
        assert set(forest_df["parent_code"].unique().tolist()) == {"FZ"}
