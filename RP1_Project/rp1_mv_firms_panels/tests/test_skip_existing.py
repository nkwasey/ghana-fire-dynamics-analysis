# file: tests/test_skip_existing.py
"""Tests for sentinel gating, schema-aware CSV checks, and combine output stability.

These tests lock in the command-layer safety contract for combine:
- a complete dual-sensor RP1 AF manifest allows `combine --skip-existing` to
  return early without rerunning `combine_panels`
- sentinel gating still fails fast when outputs exist without provenance
- fast schema checks preserve string columns such as `acq_time_utc`
- combine manifests must reference on-disk RP1 AF exports for every configured
  sensor branch
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import pytest
import yaml
from mv_firms_panels.cli import commands as cli_commands
from mv_firms_panels.cli.commands import (
    CliError,
    _fast_schema_check_csv,
    _gate_stage_execution,
    cmd_combine,
)
from mv_firms_panels.core.config import load_config
from mv_firms_panels.core.hashing import sha256_file
from mv_firms_panels.io.paths import build_run_dir, sensor_panel_monthly_path


def _write_minimal_repo(tmp_repo: Path) -> Path:
    tmp_repo.mkdir(parents=True, exist_ok=True)

    here = Path(__file__).resolve()
    repo_root = here.parents[1]

    (tmp_repo / "configs" / "schemas").mkdir(parents=True, exist_ok=True)
    (tmp_repo / "data" / "metadata").mkdir(parents=True, exist_ok=True)

    shutil.copy(
        repo_root / "configs" / "example_project.yaml",
        tmp_repo / "configs" / "example_project.yaml",
    )
    for name in [
        "fires_canonical.schema.json",
        "panel_monthly.schema.json",
        "rp1_af_monthly_base.schema.json",
        "rp1_af_monthly_ext.schema.json",
        "rp1_af_monthly_base_viirs.schema.json",
        "rp1_af_monthly_base_modis.schema.json",
        "rp1_af_monthly_ext_viirs.schema.json",
        "rp1_af_monthly_ext_modis.schema.json",
    ]:
        shutil.copy(
            repo_root / "configs" / "schemas" / name, tmp_repo / "configs" / "schemas" / name
        )

    cfg_path = tmp_repo / "configs" / "example_project.yaml"
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg.setdefault("processing", {}).setdefault("time_range", {})
    cfg["processing"]["time_range"]["start_yyyymm"] = 202401
    cfg["processing"]["time_range"]["end_yyyymm"] = 202402
    cfg_path.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    uu = pd.DataFrame(
        {
            "level": ["acz", "district"],
            "unit_id": ["zone_1", "U1"],
            "unit_code": ["Z1", pd.NA],
            "unit_name": ["Zone 1", "Unit 1"],
            "parent_level": [pd.NA, "acz"],
            "parent_id": [pd.NA, "zone_1"],
            "parent_code": [pd.NA, "Z1"],
            "parent_name": [pd.NA, "Zone 1"],
        }
    )
    (tmp_repo / "data" / "metadata" / "unit_universe.csv").write_text(
        uu.to_csv(index=False), encoding="utf-8"
    )

    return cfg_path


def _write_sensor_inputs(*, tmp_repo: Path, cfg_path: Path, run_id: str) -> None:
    cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg["outputs"]["base_dir"], run_id=run_id
    )

    months = [202401, 202402]
    keys = pd.DataFrame(
        {"level": ["district", "district"], "unit_id": ["U1", "U1"], "yyyymm": months}
    )

    viirs = keys.copy()
    viirs["viirs_det_low"] = [0, 1]
    viirs["viirs_det_nominal"] = [2, 3]
    viirs["viirs_det_high"] = [0, 1]
    viirs["viirs_det_nh"] = viirs["viirs_det_nominal"] + viirs["viirs_det_high"]
    viirs["viirs_frp_active_days"] = [1, 1]
    viirs["viirs_frp_sum_daily_max_mw"] = [10.0, 20.0]
    viirs["viirs_frp_mean_mw"] = (
        viirs["viirs_frp_sum_daily_max_mw"] / viirs["viirs_frp_active_days"]
    )
    viirs["viirs_pct_high_conf"] = [0.0, 25.0]
    viirs["viirs_days_active_nh"] = [1, 1]
    viirs["viirs_streak_max_nh"] = [1, 1]
    viirs["viirs_frp_p95_daily_max_mw"] = [10.0, 20.0]

    modis = keys.copy()
    modis["modis_det_low"] = [0, 0]
    modis["modis_det_nominal"] = [1, 1]
    modis["modis_det_high"] = [0, 0]
    modis["modis_det_nh"] = modis["modis_det_nominal"] + modis["modis_det_high"]
    modis["modis_frp_active_days"] = [1, 1]
    modis["modis_frp_sum_daily_max_mw"] = [5.0, 7.5]
    modis["modis_frp_mean_mw"] = (
        modis["modis_frp_sum_daily_max_mw"] / modis["modis_frp_active_days"]
    )
    modis["modis_pct_high_conf"] = [0.0, 0.0]
    modis["modis_days_active_nh"] = [1, 1]
    modis["modis_streak_max_nh"] = [1, 1]
    modis["modis_frp_p95_daily_max_mw"] = [5.0, 7.5]

    for sensor, df in [("viirs", viirs), ("modis", modis)]:
        p = sensor_panel_monthly_path(run_dir=run_dir, sensor=sensor, fmt="csv")
        p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(p, index=False)


def _combine_manifest_path(*, tmp_repo: Path, run_id: str) -> Path:
    run_dir = build_run_dir(repo_root=tmp_repo, outputs_base_dir="out/runs", run_id=run_id)
    return run_dir / "qa" / "combine_panels_manifest.json"


def _af_output_paths_from_manifest(manifest: dict[str, object], *, repo_root: Path) -> list[Path]:
    af_manifest = manifest["rp1_af_exports"]
    out: list[Path] = []
    for sensor_manifest in af_manifest["sensor_modes"].values():
        levels = sensor_manifest.get("levels", {})
        if not isinstance(levels, dict):
            continue
        for level_manifest in levels.values():
            if not isinstance(level_manifest, dict):
                continue
            for family in ["base_partitions", "ext_partitions"]:
                for entry in level_manifest.get(family, {}).values():
                    out.append((repo_root / entry["path"]).resolve())
    return out


def test_combine_skip_existing_returns_early_when_dual_sensor_manifest_is_complete(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)
    loaded = load_config(cfg_path, validate_paths=False, repo_root=tmp_repo)

    run_id = "testrun"
    _write_sensor_inputs(tmp_repo=tmp_repo, cfg_path=cfg_path, run_id=run_id)

    assert cmd_combine(repo_root=tmp_repo, config_path=cfg_path, run_id=run_id) == 0

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=loaded.config.outputs.base_dir, run_id=run_id
    )
    manifest_path = _combine_manifest_path(tmp_repo=tmp_repo, run_id=run_id)
    panel_path = run_dir / "panel_monthly" / "panel_monthly.csv"

    manifest_hash_before = sha256_file(manifest_path)
    panel_hash_before = sha256_file(panel_path)

    def _unexpected_rerun(**kwargs):  # pragma: no cover - exercised only on regression
        raise AssertionError(
            "combine_panels should not run when skip-existing contract is complete"
        )

    monkeypatch.setattr(cli_commands, "combine_panels", _unexpected_rerun)

    assert (
        cmd_combine(repo_root=tmp_repo, config_path=cfg_path, run_id=run_id, skip_existing=True)
        == 0
    )

    assert sha256_file(manifest_path) == manifest_hash_before
    assert sha256_file(panel_path) == panel_hash_before


def test_gate_stage_execution_raises_when_outputs_exist_but_sentinel_missing(
    tmp_path: Path,
) -> None:
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir(parents=True, exist_ok=True)

    cfg_path = _write_minimal_repo(tmp_repo)
    loaded = load_config(cfg_path, validate_paths=False, repo_root=tmp_repo)
    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=loaded.config.outputs.base_dir, run_id="abc"
    )
    out_path = run_dir / "panel_monthly" / "panel_monthly.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("dummy", encoding="utf-8")

    with pytest.raises(CliError, match="outputs exist but sentinel is missing"):
        _gate_stage_execution(
            stage="combine_panels",
            repo_root=tmp_repo,
            cfg=loaded.config,
            sentinel_path=run_dir / "qa" / "combine_panels_manifest.json",
            output_candidates=[out_path],
            contracted_schema_checks=[],
            skip_existing=False,
            force=False,
        )


def test_fast_schema_check_reads_string_columns_as_strings(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)
    loaded = load_config(cfg_path, validate_paths=False, repo_root=tmp_repo)

    run_id = "testrun"
    run_dir = build_run_dir(repo_root=tmp_repo, outputs_base_dir="out/runs", run_id=run_id)

    df = pd.DataFrame(
        [
            {
                "run_id": "r1",
                "source_file": "x.csv",
                "sensor": "viirs",
                "level": "district",
                "unit_id": "U1",
                "acq_datetime_utc": "2014-01-01T13:44:00Z",
                "acq_date": "2014-01-01",
                "acq_time_utc": "1344",
                "yyyymm": 201401,
                "date_utc": "2014-01-01",
                "latitude": 0.0,
                "longitude": 0.0,
                "conf_cat": "n",
                "frp_mw": 1.0,
                "daynight": "D",
                "satellite": "N",
                "type": 0,
                "dedup_key": "k",
                "was_dedup_kept": True,
            }
        ]
    )
    csv_path = run_dir / "fires_canonical" / "viirs" / "fires_canonical_viirs_2014.csv"
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(csv_path, index=False)

    _fast_schema_check_csv(
        repo_root=tmp_repo,
        cfg=loaded.config,
        schema_key="fires_canonical",
        csv_rel_path=csv_path.relative_to(tmp_repo).as_posix(),
    )

    reread = pd.read_csv(csv_path, dtype={"acq_time_utc": "string"})
    assert reread.loc[0, "acq_time_utc"] == "1344"


def test_skip_existing_manifest_contains_referenced_dual_sensor_af_outputs(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)
    run_id = "testrun"
    _write_sensor_inputs(tmp_repo=tmp_repo, cfg_path=cfg_path, run_id=run_id)

    assert cmd_combine(repo_root=tmp_repo, config_path=cfg_path, run_id=run_id) == 0
    manifest = json.loads(
        _combine_manifest_path(tmp_repo=tmp_repo, run_id=run_id).read_text(encoding="utf-8")
    )

    sensor_modes = manifest["rp1_af_exports"]["sensor_modes"]
    assert set(sensor_modes.keys()) == {"viirs", "modis"}

    af_paths = _af_output_paths_from_manifest(manifest, repo_root=tmp_repo)
    assert af_paths
    assert all(path.exists() for path in af_paths)
