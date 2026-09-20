# file: tests/test_range_tagged_outputs.py
"""Tests for additive range-tagged combined panel outputs.

Contract note
----------------------
These assertions must not hard-code an RP1 AF partition token such as
``unit_code=A1``. The exporter derives partitioning generically from the Stage 1
hierarchy, so the realised token for a top-level ACZ row is typically
``acz_code=A1`` rather than ``unit_code=A1``.

Accordingly, the RP1 AF assertions in this file are manifest-driven:
- require both configured sensor branches
- require at least one referenced RP1 AF path
- require every manifest-referenced RP1 AF file to exist on disk
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import yaml
from mv_firms_panels.core.config import load_config
from mv_firms_panels.io.paths import (
    build_run_dir,
    panel_monthly_ext_path,
    panel_monthly_ext_range_path,
    panel_monthly_qc_path,
    panel_monthly_qc_range_path,
    panel_monthly_wide_path,
    panel_monthly_wide_range_path,
)
from mv_firms_panels.stages.combine_panels import combine_panels


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_cfg(tmp_repo: Path, *, write_range_tagged_panels: bool):
    src = _repo_root() / "configs" / "example_project.yaml"
    raw = yaml.safe_load(src.read_text())
    raw["outputs"]["base_dir"] = "out/runs"
    raw["outputs"]["write_formats"]["monthly_panels"] = ["csv"]
    raw["outputs"]["write_range_tagged_panels"] = bool(write_range_tagged_panels)
    raw["qc"]["write_panel_monthly_qc_sidecar"] = True
    cfg_path = tmp_repo / "configs" / "example_project.yaml"
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False))
    return load_config(cfg_path, validate_paths=False, repo_root=tmp_repo).config


def _unit_universe() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "level": ["acz"],
            "unit_id": ["A1"],
            "unit_code": ["A1"],
            "unit_name": ["Alpha"],
            "parent_level": [pd.NA],
            "parent_id": [pd.NA],
            "parent_code": [pd.NA],
            "parent_name": [pd.NA],
        }
    )


def _sensor_df(sensor: str) -> pd.DataFrame:
    prefix = sensor.lower()
    det_nominal = [1, 0]
    det_high = [0, 0]
    return pd.DataFrame(
        {
            "level": ["acz", "acz"],
            "unit_id": ["A1", "A1"],
            "yyyymm": [201401, 201402],
            f"{prefix}_det_low": [0, 1],
            f"{prefix}_det_nominal": det_nominal,
            f"{prefix}_det_high": det_high,
            f"{prefix}_det_nh": [n + h for n, h in zip(det_nominal, det_high, strict=False)],
            f"{prefix}_frp_active_days": [1, 1],
            f"{prefix}_frp_sum_daily_max_mw": [2.5, 5.0],
            f"{prefix}_frp_mean_mw": [2.5, 5.0],
            f"{prefix}_pct_high_conf": [0.0, 0.0],
            f"{prefix}_days_active_nh": [1, 0],
            f"{prefix}_streak_max_nh": [1, 0],
            f"{prefix}_frp_p95_daily_max_mw": [2.5, 5.0],
        }
    )


def _collect_rp1_af_paths_from_manifest(*, manifest: dict, repo_root: Path) -> list[Path]:
    """Return all RP1 AF base/ext file paths referenced by the manifest.

    The helper is intentionally generic over:
    - sensor branch
    - level
    - partition key/value naming
    """
    af_manifest = manifest["rp1_af_exports"]
    out: list[Path] = []

    for sensor_manifest in af_manifest["sensor_modes"].values():
        levels = sensor_manifest.get("levels", {})
        if not isinstance(levels, dict):
            continue

        for level_manifest in levels.values():
            if not isinstance(level_manifest, dict):
                continue

            for family_key in ["base_partitions", "ext_partitions"]:
                partitions = level_manifest.get(family_key, {})
                if not isinstance(partitions, dict):
                    continue

                for entry in partitions.values():
                    out.append((repo_root / entry["path"]).resolve())

    return out


def _assert_dual_sensor_rp1_exports_exist(*, manifest: dict, repo_root: Path) -> None:
    """Assert that the dual-sensor RP1 AF family is materially present on disk."""
    af_manifest = manifest["rp1_af_exports"]
    sensor_modes = af_manifest["sensor_modes"]
    assert set(sensor_modes.keys()) == {"viirs", "modis"}

    rp1_paths = _collect_rp1_af_paths_from_manifest(manifest=manifest, repo_root=repo_root)
    assert rp1_paths, "Expected at least one RP1 AF export path in the manifest"
    assert all(path.exists() for path in rp1_paths)

    for sensor_mode in ["viirs", "modis"]:
        sensor_manifest = sensor_modes[sensor_mode]
        levels = sensor_manifest.get("levels", {})
        assert (
            isinstance(levels, dict) and levels
        ), f"Expected non-empty levels for sensor={sensor_mode!r}"

        sensor_paths: list[Path] = []
        for level_manifest in levels.values():
            for family_key in ["base_partitions", "ext_partitions"]:
                partitions = level_manifest.get(family_key, {})
                if isinstance(partitions, dict):
                    for entry in partitions.values():
                        sensor_paths.append((repo_root / entry["path"]).resolve())

        assert sensor_paths, f"Expected RP1 AF files for sensor={sensor_mode!r}"
        assert all(path.exists() for path in sensor_paths)


def test_range_tagged_outputs_written_when_enabled(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir(parents=True, exist_ok=True)
    cfg = _load_cfg(tmp_repo, write_range_tagged_panels=True)
    run_id = "range_on"

    res = combine_panels(
        cfg=cfg,
        repo_root=tmp_repo,
        run_id=run_id,
        unit_universe_df=_unit_universe(),
        viirs_monthly_df=_sensor_df("viirs"),
        modis_monthly_df=_sensor_df("modis"),
        start_yyyymm=201401,
        end_yyyymm=201402,
        write_outputs=True,
        validate_schema=False,
        write_extended_metrics=True,
    )

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
    )
    assert panel_monthly_wide_path(run_dir=run_dir, fmt="csv").exists()
    assert panel_monthly_ext_path(run_dir=run_dir, fmt="csv").exists()
    assert panel_monthly_qc_path(run_dir=run_dir, fmt="csv").exists()
    assert panel_monthly_wide_range_path(
        run_dir=run_dir, start_yyyymm=201401, end_yyyymm=201402, fmt="csv"
    ).exists()
    assert panel_monthly_ext_range_path(
        run_dir=run_dir, start_yyyymm=201401, end_yyyymm=201402, fmt="csv"
    ).exists()
    assert panel_monthly_qc_range_path(
        run_dir=run_dir, start_yyyymm=201401, end_yyyymm=201402, fmt="csv"
    ).exists()

    manifest = yaml.safe_load(res.manifest_path.read_text())
    assert manifest["panel_monthly"]["path"].endswith("panel_monthly/panel_monthly.csv")
    assert manifest["rp1_af_exports"]["source"] == [
        "panel_monthly_ext",
        "panel_monthly_qc",
        "unit_universe",
    ]
    _assert_dual_sensor_rp1_exports_exist(manifest=manifest, repo_root=tmp_repo)

    assert manifest["range_tagged_outputs"]["range"] == {
        "start_yyyymm": 201401,
        "end_yyyymm": 201402,
    }
    assert manifest["range_tagged_outputs"]["panel_monthly"]["path"].endswith(
        "panel_monthly/panel_monthly_201401_201402.csv"
    )
    assert manifest["range_tagged_outputs"]["panel_monthly_ext"]["path"].endswith(
        "panel_monthly/panel_monthly_ext_201401_201402.csv"
    )
    assert manifest["range_tagged_outputs"]["panel_monthly_qc"]["path"].endswith(
        "panel_monthly/panel_monthly_qc_201401_201402.csv"
    )


def test_range_tagged_outputs_not_written_when_disabled(tmp_path: Path) -> None:
    tmp_repo = tmp_path / "repo"
    tmp_repo.mkdir(parents=True, exist_ok=True)
    cfg = _load_cfg(tmp_repo, write_range_tagged_panels=False)
    run_id = "range_off"

    res = combine_panels(
        cfg=cfg,
        repo_root=tmp_repo,
        run_id=run_id,
        unit_universe_df=_unit_universe(),
        viirs_monthly_df=_sensor_df("viirs"),
        modis_monthly_df=_sensor_df("modis"),
        start_yyyymm=201401,
        end_yyyymm=201402,
        write_outputs=True,
        validate_schema=False,
        write_extended_metrics=True,
    )

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg.outputs.base_dir, run_id=run_id
    )
    assert panel_monthly_wide_path(run_dir=run_dir, fmt="csv").exists()
    assert panel_monthly_ext_path(run_dir=run_dir, fmt="csv").exists()
    assert panel_monthly_qc_path(run_dir=run_dir, fmt="csv").exists()
    assert not panel_monthly_wide_range_path(
        run_dir=run_dir, start_yyyymm=201401, end_yyyymm=201402, fmt="csv"
    ).exists()
    assert not panel_monthly_ext_range_path(
        run_dir=run_dir, start_yyyymm=201401, end_yyyymm=201402, fmt="csv"
    ).exists()
    assert not panel_monthly_qc_range_path(
        run_dir=run_dir, start_yyyymm=201401, end_yyyymm=201402, fmt="csv"
    ).exists()

    manifest = yaml.safe_load(res.manifest_path.read_text())
    assert "range_tagged_outputs" not in manifest
    assert manifest["rp1_af_exports"]["source"] == [
        "panel_monthly_ext",
        "panel_monthly_qc",
        "unit_universe",
    ]
    _assert_dual_sensor_rp1_exports_exist(manifest=manifest, repo_root=tmp_repo)
