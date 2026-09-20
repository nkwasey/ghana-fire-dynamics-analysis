# file: tests/test_config_validation_mv_firms.py
from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml
from mv_firms_panels.core.config import LOCKED_RP1_EXPORT_WINDOWS, load_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _example_config_dict() -> dict:
    cfg_path = _repo_root() / "configs" / "example_project.yaml"
    return yaml.safe_load(cfg_path.read_text(encoding="utf-8"))


def _write_tmp_config(tmp_path: Path, payload: dict, filename: str = "config.yaml") -> Path:
    out = tmp_path / filename
    out.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return out


def test_example_project_config_loads_and_validates_dual_sensor_rp1_contract() -> None:
    cfg_path = _repo_root() / "configs" / "example_project.yaml"
    loaded = load_config(cfg_path, validate_paths=False)
    cfg = loaded.config

    assert cfg.project.name == "mv_firms_panels"
    assert "viirs" in cfg.processing.sensors_enabled
    assert "modis" in cfg.processing.sensors_enabled
    assert "fires_canonical" in cfg.determinism.column_order
    assert "panel_monthly" in cfg.determinism.column_order

    assert cfg.outputs.rp1_exports.family_name == "rp1_af_exports"
    assert set(cfg.outputs.rp1_exports.sensors.keys()) == {"viirs", "modis"}

    viirs_contract = cfg.outputs.rp1_exports.sensors["viirs"]
    modis_contract = cfg.outputs.rp1_exports.sensors["modis"]

    assert (
        viirs_contract.window.start_yyyymm,
        viirs_contract.window.end_yyyymm,
    ) == LOCKED_RP1_EXPORT_WINDOWS["viirs"]
    assert (
        modis_contract.window.start_yyyymm,
        modis_contract.window.end_yyyymm,
    ) == LOCKED_RP1_EXPORT_WINDOWS["modis"]

    # Transitional compatibility: the legacy flat keys remain aligned to the
    # VIIRS-specific RP1 schemas until exporter execution logic is generalised.
    assert cfg.outputs.schemas["rp1_af_monthly_base"] == viirs_contract.schemas.base
    assert cfg.outputs.schemas["rp1_af_monthly_ext"] == viirs_contract.schemas.ext


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    bad_cfg = _example_config_dict()
    bad_cfg["unexpected_key"] = 123

    p = _write_tmp_config(tmp_path, bad_cfg, filename="bad.yaml")
    with pytest.raises(ValueError):
        load_config(p, validate_paths=False)


def test_modis_thresholds_must_be_ordered(tmp_path: Path) -> None:
    bad_cfg = _example_config_dict()
    bad_cfg["processing"]["confidence_model"]["modis_thresholds_pct"] = {
        "low_lt": 90,
        "high_ge": 80,
    }

    p = _write_tmp_config(tmp_path, bad_cfg, filename="bad2.yaml")
    with pytest.raises(ValueError):
        load_config(p, validate_paths=False)


def test_rp1_exports_rejects_unsupported_sensor_key(tmp_path: Path) -> None:
    bad_cfg = _example_config_dict()
    bad_cfg["outputs"]["rp1_exports"]["sensors"]["landsat"] = copy.deepcopy(
        bad_cfg["outputs"]["rp1_exports"]["sensors"]["viirs"]
    )

    p = _write_tmp_config(tmp_path, bad_cfg, filename="bad_sensor.yaml")
    with pytest.raises(ValueError, match="Invalid sensor key"):
        load_config(p, validate_paths=False)


def test_rp1_exports_requires_both_supported_sensor_contracts(tmp_path: Path) -> None:
    bad_cfg = _example_config_dict()
    del bad_cfg["outputs"]["rp1_exports"]["sensors"]["modis"]

    p = _write_tmp_config(tmp_path, bad_cfg, filename="missing_modis.yaml")
    with pytest.raises(ValueError, match="must define contracts for all supported sensors"):
        load_config(p, validate_paths=False)


def test_rp1_exports_rejects_wrong_locked_window(tmp_path: Path) -> None:
    bad_cfg = _example_config_dict()
    bad_cfg["outputs"]["rp1_exports"]["sensors"]["modis"]["window"]["start_yyyymm"] = 200011

    p = _write_tmp_config(tmp_path, bad_cfg, filename="bad_window.yaml")
    with pytest.raises(ValueError, match="locked RP1 export window"):
        load_config(p, validate_paths=False)


def test_rp1_exports_rejects_missing_schema_path(tmp_path: Path) -> None:
    bad_cfg = _example_config_dict()
    bad_cfg["outputs"]["rp1_exports"]["sensors"]["modis"]["schemas"]["ext"] = ""

    p = _write_tmp_config(tmp_path, bad_cfg, filename="missing_schema.yaml")
    with pytest.raises(ValueError, match="schema paths must be non-empty"):
        load_config(p, validate_paths=False)


def test_legacy_viirs_schema_alias_must_match_explicit_rp1_contract(tmp_path: Path) -> None:
    bad_cfg = _example_config_dict()
    bad_cfg["outputs"]["schemas"][
        "rp1_af_monthly_base"
    ] = "configs/schemas/rp1_af_monthly_base_modis.schema.json"

    p = _write_tmp_config(tmp_path, bad_cfg, filename="legacy_alias_mismatch.yaml")
    with pytest.raises(ValueError, match="must match"):
        load_config(p, validate_paths=False)


def test_validate_paths_missing_unit_universe_reports_access_guidance(tmp_path: Path) -> None:
    cfg = _example_config_dict()
    p = _write_tmp_config(tmp_path, cfg, filename="missing_stage2_inputs.yaml")

    with pytest.raises(FileNotFoundError) as excinfo:
        load_config(p, validate_paths=True, repo_root=tmp_path)

    msg = str(excinfo.value)
    assert "Missing required Stage 2 input `unit_universe_csv`" in msg
    assert "docs/data_access.md" in msg
    assert "README.md" in msg
    assert "Required by stage: rp1_mv_firms_panels (Stage 2)." in msg
