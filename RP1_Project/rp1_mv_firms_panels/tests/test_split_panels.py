# file: tests/test_split_panels.py
"""Optional split outputs by level.

When outputs.split_panels_by_level is enabled, combine_panels must:
- write the combined contracted panel_monthly artefact, and
- additionally write one per-level file panel_monthly_{level}.*,
  using the same selected format,
- where each per-level file is an exact row subset of the combined file.

Contract note
----------------------
The RP1 AF assertions in this file must not hard-code a specific partition key
such as ``unit_code``. The exporter derives top-level partitioning generically
from the Stage 1 hierarchy, so the realised path token is contractually proven
by the manifest rather than by a guessed helper call.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pandas as pd
import yaml
from mv_firms_panels.core.config import load_config
from mv_firms_panels.io.paths import (
    build_run_dir,
    panel_monthly_ext_level_path,
    panel_monthly_ext_path,
    panel_monthly_wide_level_path,
    panel_monthly_wide_path,
)
from mv_firms_panels.stages.combine_panels import combine_panels


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _write_minimal_repo(tmp_repo: Path) -> Path:
    """Create a minimal repo layout and return config path."""
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
        "rp1_af_monthly_base_viirs.schema.json",
        "rp1_af_monthly_base_modis.schema.json",
        "rp1_af_monthly_ext_viirs.schema.json",
        "rp1_af_monthly_ext_modis.schema.json",
    ]:
        shutil.copy(
            here_repo / "configs" / "schemas" / name,
            tmp_repo / "configs" / "schemas" / name,
        )

    # Patch the copied config: enable split and force csv for easier assertions.
    cfg_path = tmp_repo / "configs" / "example_project.yaml"
    raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    raw["outputs"]["split_panels_by_level"] = True
    raw["outputs"]["write_formats"]["monthly_panels"] = ["csv"]
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    return cfg_path


def _collect_rp1_af_paths_from_manifest(*, manifest: dict, repo_root: Path) -> list[Path]:
    """Return all RP1 AF base/ext file paths referenced by the manifest."""
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
            if not isinstance(level_manifest, dict):
                continue
            for family_key in ["base_partitions", "ext_partitions"]:
                partitions = level_manifest.get(family_key, {})
                if isinstance(partitions, dict):
                    for entry in partitions.values():
                        sensor_paths.append((repo_root / entry["path"]).resolve())

        assert sensor_paths, f"Expected RP1 AF files for sensor={sensor_mode!r}"
        assert all(path.exists() for path in sensor_paths)


def test_split_panels_by_level_writes_exact_subsets_and_preserves_dual_sensor_rp1_exports(
    tmp_path: Path,
) -> None:
    tmp_repo = tmp_path / "repo"
    cfg_path = _write_minimal_repo(tmp_repo)

    loaded = load_config(cfg_path, validate_paths=False, repo_root=tmp_repo)
    cfg = loaded.config

    unit_universe = pd.DataFrame(
        [
            {
                "level": "district",
                "unit_id": "D1",
                "unit_code": "D1",
                "unit_name": "District 1",
                "parent_level": "acz",
                "parent_id": "A1",
                "parent_code": "A1",
                "parent_name": "ACZ 1",
            },
            {
                "level": "district",
                "unit_id": "D2",
                "unit_code": "D2",
                "unit_name": "District 2",
                "parent_level": "acz",
                "parent_id": "A1",
                "parent_code": "A1",
                "parent_name": "ACZ 1",
            },
            {
                "level": "acz",
                "unit_id": "A1",
                "unit_code": "A1",
                "unit_name": "ACZ 1",
                "parent_level": pd.NA,
                "parent_id": pd.NA,
                "parent_code": pd.NA,
                "parent_name": pd.NA,
            },
        ]
    )

    empty_viirs = pd.DataFrame(columns=["level", "unit_id", "yyyymm"])
    empty_modis = pd.DataFrame(columns=["level", "unit_id", "yyyymm"])

    res = combine_panels(
        cfg=cfg,
        repo_root=tmp_repo,
        run_id="test_run",
        unit_universe_df=unit_universe,
        viirs_monthly_df=empty_viirs,
        modis_monthly_df=empty_modis,
        start_yyyymm=202401,
        end_yyyymm=202401,
        write_outputs=True,
        validate_schema=True,
        write_extended_metrics=True,
    )
    assert res.panel_path is not None

    run_dir = build_run_dir(
        repo_root=tmp_repo, outputs_base_dir=cfg.outputs.base_dir, run_id="test_run"
    )
    combined_path = panel_monthly_wide_path(run_dir=run_dir, fmt="csv")
    assert combined_path.exists()

    combined = pd.read_csv(combined_path)
    assert set(combined["level"].unique().tolist()) == {"district", "acz"}

    for lvl in ["district", "acz"]:
        lvl_path = panel_monthly_wide_level_path(run_dir=run_dir, level=lvl, fmt="csv")
        assert lvl_path.exists()

        lvl_df = pd.read_csv(lvl_path)
        expected = combined.loc[combined["level"] == lvl].reset_index(drop=True)
        pd.testing.assert_frame_equal(lvl_df.reset_index(drop=True), expected, check_dtype=True)

    # Extended metrics artefacts should also be split when present.
    ext_path = panel_monthly_ext_path(run_dir=run_dir, fmt="csv")
    assert ext_path.exists()

    ext = pd.read_csv(ext_path)
    for lvl in ["district", "acz"]:
        lvl_ext_path = panel_monthly_ext_level_path(run_dir=run_dir, level=lvl, fmt="csv")
        assert lvl_ext_path.exists()

        lvl_ext_df = pd.read_csv(lvl_ext_path)
        expected_ext = ext.loc[ext["level"] == lvl].reset_index(drop=True)
        pd.testing.assert_frame_equal(
            lvl_ext_df.reset_index(drop=True), expected_ext, check_dtype=True
        )

    manifest = json.loads(res.manifest_path.read_text(encoding="utf-8"))
    _assert_dual_sensor_rp1_exports_exist(manifest=manifest, repo_root=tmp_repo)
