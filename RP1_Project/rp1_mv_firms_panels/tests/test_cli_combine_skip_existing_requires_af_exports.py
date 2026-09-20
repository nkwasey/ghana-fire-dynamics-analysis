# file: tests/test_cli_combine_skip_existing_requires_af_exports.py
"""AF-aware combine skip-existing regressions.

These tests lock in the command-layer safety rules after the dual-sensor RP1 AF
contract:
- `combine --skip-existing` must not silently accept stale manifests that predate
  the RP1 AF family
- `combine --skip-existing` must rerun if a referenced RP1 AF file is missing
- `combine --skip-existing` must rerun if a configured sensor branch is missing
- manifest traversal must follow the generic `sensor_modes -> levels -> partitions`
  structure rather than hard-coded ACZ assumptions
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import yaml
from mv_firms_panels.cli.commands import cmd_combine
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


def _read_manifest(*, tmp_repo: Path, run_id: str) -> dict[str, object]:
    return json.loads(
        _combine_manifest_path(tmp_repo=tmp_repo, run_id=run_id).read_text(encoding="utf-8")
    )


def _af_output_paths_from_manifest(*, tmp_repo: Path, run_id: str) -> list[Path]:
    manifest = _read_manifest(tmp_repo=tmp_repo, run_id=run_id)
    af_manifest = manifest["rp1_af_exports"]

    out: list[Path] = []
    for sensor_manifest in af_manifest["sensor_modes"].values():
        levels = sensor_manifest.get("levels", {})
        if not isinstance(levels, dict):
            continue
        for level_manifest in levels.values():
            if not isinstance(level_manifest, dict):
                continue
            for key in ["base_partitions", "ext_partitions"]:
                for entry in level_manifest.get(key, {}).values():
                    out.append((tmp_repo / entry["path"]).resolve())
    return out


def test_combine_skip_existing_repairs_stale_manifest_missing_af_exports(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)
    run_id = "testrun"
    _write_sensor_inputs(tmp_repo=tmp_repo, cfg_path=cfg_path, run_id=run_id)

    assert cmd_combine(repo_root=tmp_repo, config_path=cfg_path, run_id=run_id) == 0

    sentinel = _combine_manifest_path(tmp_repo=tmp_repo, run_id=run_id)
    stale_manifest = _read_manifest(tmp_repo=tmp_repo, run_id=run_id)
    stale_manifest.pop("rp1_af_exports", None)
    sentinel.write_text(json.dumps(stale_manifest, indent=2, sort_keys=True), encoding="utf-8")

    assert (
        cmd_combine(repo_root=tmp_repo, config_path=cfg_path, run_id=run_id, skip_existing=True)
        == 0
    )

    repaired = _read_manifest(tmp_repo=tmp_repo, run_id=run_id)
    assert "rp1_af_exports" in repaired
    assert set(repaired["rp1_af_exports"]["sensor_modes"].keys()) == {"viirs", "modis"}
    af_paths = _af_output_paths_from_manifest(tmp_repo=tmp_repo, run_id=run_id)
    assert af_paths
    assert all(path.exists() for path in af_paths)


def test_combine_skip_existing_repairs_missing_af_export_file(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)
    run_id = "testrun"
    _write_sensor_inputs(tmp_repo=tmp_repo, cfg_path=cfg_path, run_id=run_id)

    assert cmd_combine(repo_root=tmp_repo, config_path=cfg_path, run_id=run_id) == 0

    af_paths = _af_output_paths_from_manifest(tmp_repo=tmp_repo, run_id=run_id)
    assert af_paths
    missing_path = af_paths[0]
    missing_path.unlink()
    assert not missing_path.exists()

    assert (
        cmd_combine(repo_root=tmp_repo, config_path=cfg_path, run_id=run_id, skip_existing=True)
        == 0
    )

    repaired_manifest = _read_manifest(tmp_repo=tmp_repo, run_id=run_id)
    assert "rp1_af_exports" in repaired_manifest
    assert set(repaired_manifest["rp1_af_exports"]["sensor_modes"].keys()) == {"viirs", "modis"}
    assert missing_path.exists()


def test_combine_skip_existing_repairs_manifest_missing_modis_sensor_branch(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)
    run_id = "testrun"
    _write_sensor_inputs(tmp_repo=tmp_repo, cfg_path=cfg_path, run_id=run_id)

    assert cmd_combine(repo_root=tmp_repo, config_path=cfg_path, run_id=run_id) == 0

    sentinel = _combine_manifest_path(tmp_repo=tmp_repo, run_id=run_id)
    stale_manifest = _read_manifest(tmp_repo=tmp_repo, run_id=run_id)
    stale_manifest["rp1_af_exports"]["sensor_modes"].pop("modis", None)
    sentinel.write_text(json.dumps(stale_manifest, indent=2, sort_keys=True), encoding="utf-8")

    assert (
        cmd_combine(repo_root=tmp_repo, config_path=cfg_path, run_id=run_id, skip_existing=True)
        == 0
    )

    repaired = _read_manifest(tmp_repo=tmp_repo, run_id=run_id)
    assert set(repaired["rp1_af_exports"]["sensor_modes"].keys()) == {"viirs", "modis"}
    af_paths = _af_output_paths_from_manifest(tmp_repo=tmp_repo, run_id=run_id)
    assert af_paths
    assert all(path.exists() for path in af_paths)
