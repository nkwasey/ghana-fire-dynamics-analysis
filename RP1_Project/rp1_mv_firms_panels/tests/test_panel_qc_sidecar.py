# file: tests/test_panel_qc_sidecar.py
"""QC sidecar regressions.

Requirements
------------
- Base contracted panel_monthly schema/columns remain unchanged.
- When enabled via config, combine_panels writes:
    out/runs/<run_id>/panel_monthly/panel_monthly_qc.<fmt>
- QC columns include per-sensor flags:
    {sensor}_has_any
    {sensor}_in_coverage_flag
    {sensor}_structural_missing_flag
    {sensor}_low_information_month_flag
    {sensor}_frp_ok_flag
- low_information_month_flag is evaluated only inside coverage; outside coverage it is null.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
import yaml
from mv_firms_panels.core.config import load_config
from mv_firms_panels.io.paths import build_run_dir, panel_monthly_qc_path, panel_monthly_wide_path
from mv_firms_panels.stages.combine_panels import combine_panels


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_minimal_repo(tmp_repo: Path) -> Path:
    here_repo = _repo_root()

    (tmp_repo / "configs" / "schemas").mkdir(parents=True, exist_ok=True)

    shutil.copy(
        here_repo / "configs" / "example_project.yaml",
        tmp_repo / "configs" / "example_project.yaml",
    )
    for name in [
        "panel_monthly.schema.json",
        "rp1_af_monthly_base.schema.json",
        "rp1_af_monthly_ext.schema.json",
    ]:
        shutil.copy(
            here_repo / "configs" / "schemas" / name,
            tmp_repo / "configs" / "schemas" / name,
        )

    cfg_path = tmp_repo / "configs" / "example_project.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    raw["outputs"]["write_formats"]["monthly_panels"] = ["csv"]
    raw.setdefault("qc", {})
    raw["qc"]["write_panel_monthly_qc_sidecar"] = True

    raw.setdefault("processing", {})
    raw["processing"]["time_range"] = {
        "start_yyyymm": 201112,
        "end_yyyymm": 201202,
        "timezone": "UTC",
    }
    raw.setdefault("processing", {}).setdefault("sensor_coverage", {})
    raw["processing"]["sensor_coverage"]["viirs"] = {
        "start_yyyymm": 201201,
        "end_yyyymm": None,
        "timezone": "UTC",
    }
    raw["processing"]["sensor_coverage"]["modis"] = {
        "start_yyyymm": 200001,
        "end_yyyymm": None,
        "timezone": "UTC",
    }

    raw.setdefault("qc", {}).setdefault("sensors", {})
    raw["qc"]["sensors"].setdefault("viirs", {})
    raw["qc"]["sensors"].setdefault("modis", {})
    raw["qc"]["sensors"]["viirs"]["low_information_min_detections"] = 2
    raw["qc"]["sensors"]["viirs"]["frp_ok_min_active_days"] = 1
    raw["qc"]["sensors"]["viirs"]["frp_ok_min_sum_daily_max_mw"] = 0.0
    raw["qc"]["sensors"]["modis"]["low_information_min_detections"] = 2
    raw["qc"]["sensors"]["modis"]["frp_ok_min_active_days"] = 1
    raw["qc"]["sensors"]["modis"]["frp_ok_min_sum_daily_max_mw"] = 0.0

    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return cfg_path


def test_qc_sidecar_written_and_schema_unchanged(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)

    loaded = load_config(cfg_path, validate_paths=False, repo_root=tmp_repo)
    cfg = loaded.config

    unit_universe = pd.DataFrame(
        [
            {"level": "district", "unit_id": "U1", "unit_name": "Unit 1"},
            {"level": "district", "unit_id": "U2", "unit_name": "Unit 2"},
        ]
    )

    viirs_monthly = pd.DataFrame(
        [
            {
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 201201,
                "viirs_det_low": 0,
                "viirs_det_nominal": 2,
                "viirs_det_high": 1,
                "viirs_det_nh": 3,
                "viirs_frp_active_days": 1,
                "viirs_frp_sum_daily_max_mw": 10.0,
                "viirs_frp_mean_mw": 10.0,
            },
            {
                "level": "district",
                "unit_id": "U1",
                "yyyymm": 201202,
                "viirs_det_low": 0,
                "viirs_det_nominal": 2,
                "viirs_det_high": 0,
                "viirs_det_nh": 2,
                "viirs_frp_active_days": 2,
                "viirs_frp_sum_daily_max_mw": 20.0,
                "viirs_frp_mean_mw": 0.0,
            },
        ]
    )

    empty_modis = pd.DataFrame(columns=["level", "unit_id", "yyyymm"])

    res = combine_panels(
        cfg=cfg,
        repo_root=tmp_repo,
        run_id="test_run",
        unit_universe_df=unit_universe,
        viirs_monthly_df=viirs_monthly,
        modis_monthly_df=empty_modis,
        start_yyyymm=201112,
        end_yyyymm=201202,
        write_outputs=True,
        validate_schema=True,
        write_extended_metrics=False,
    )
    assert res.panel_path is not None

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg.outputs.base_dir, run_id="test_run"
    )

    panel_path = panel_monthly_wide_path(run_dir=run_dir, fmt="csv")
    assert panel_path.exists()
    panel = pd.read_csv(panel_path)
    assert not any(c.endswith("_flag") for c in panel.columns)
    assert not any(c.endswith("_has_any") for c in panel.columns)

    qc_path = panel_monthly_qc_path(run_dir=run_dir, fmt="csv")
    assert qc_path.exists()
    qc = pd.read_csv(qc_path)

    expected_cols = [
        "run_id",
        "level",
        "unit_id",
        "yyyymm",
        "year",
        "month",
        "viirs_has_any",
        "viirs_in_coverage_flag",
        "viirs_structural_missing_flag",
        "viirs_low_information_month_flag",
        "viirs_frp_ok_flag",
        "modis_has_any",
        "modis_in_coverage_flag",
        "modis_structural_missing_flag",
        "modis_low_information_month_flag",
        "modis_frp_ok_flag",
    ]
    assert list(qc.columns) == expected_cols

    assert len(qc) == 6

    row = qc[(qc["unit_id"] == "U1") & (qc["yyyymm"] == 201112)].iloc[0]
    assert bool(row["viirs_has_any"]) is False
    assert bool(row["viirs_in_coverage_flag"]) is False
    assert bool(row["viirs_structural_missing_flag"]) is True
    assert pd.isna(row["viirs_low_information_month_flag"])
    assert bool(row["viirs_frp_ok_flag"]) is False

    row = qc[(qc["unit_id"] == "U1") & (qc["yyyymm"] == 201201)].iloc[0]
    assert bool(row["viirs_has_any"]) is True
    assert bool(row["viirs_in_coverage_flag"]) is True
    assert bool(row["viirs_structural_missing_flag"]) is False
    assert bool(row["viirs_low_information_month_flag"]) is False
    assert bool(row["viirs_frp_ok_flag"]) is True

    row = qc[(qc["unit_id"] == "U1") & (qc["yyyymm"] == 201202)].iloc[0]
    assert bool(row["viirs_has_any"]) is True
    assert bool(row["viirs_low_information_month_flag"]) is False
    assert bool(row["viirs_frp_ok_flag"]) is False

    row = qc[(qc["unit_id"] == "U2") & (qc["yyyymm"] == 201201)].iloc[0]
    assert bool(row["viirs_has_any"]) is False
    assert bool(row["viirs_in_coverage_flag"]) is True
    assert bool(row["viirs_structural_missing_flag"]) is False
    assert bool(row["viirs_low_information_month_flag"]) is True
    assert bool(row["viirs_frp_ok_flag"]) is False

    assert qc["modis_in_coverage_flag"].astype(bool).all()
    assert qc["modis_structural_missing_flag"].astype(bool).sum() == 0
    assert qc["modis_has_any"].astype(bool).sum() == 0
    assert qc["modis_frp_ok_flag"].astype(bool).sum() == 0
