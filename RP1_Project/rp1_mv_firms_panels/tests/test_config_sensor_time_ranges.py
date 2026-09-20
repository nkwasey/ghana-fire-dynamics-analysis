# file: tests/test_config_sensor_time_ranges.py
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from mv_firms_panels.core.config import load_config


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_example_cfg_dict() -> dict:
    p = _repo_root() / "configs" / "example_project.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))


def test_config_accepts_optional_sensor_time_ranges_and_coverage(tmp_path: Path) -> None:
    cfg = _load_example_cfg_dict()

    cfg.setdefault("processing", {})
    cfg["processing"]["sensor_time_ranges"] = {
        "modis": {"start_yyyymm": 202401, "end_yyyymm": 202402, "timezone": "UTC"},
        "viirs": {"start_yyyymm": 202401, "end_yyyymm": 202402, "timezone": "UTC"},
    }
    cfg["processing"]["sensor_coverage"] = {
        "modis": {"start_yyyymm": 200001, "end_yyyymm": None, "timezone": "UTC"},
        "viirs": {"start_yyyymm": 201201, "end_yyyymm": None, "timezone": "UTC"},
    }

    p = tmp_path / "cfg.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    loaded = load_config(p, validate_paths=False, repo_root=_repo_root())
    assert loaded.config.processing.sensor_time_ranges is not None
    assert loaded.config.processing.sensor_time_ranges["viirs"].start_yyyymm == 202401
    assert loaded.config.processing.sensor_coverage is not None
    assert loaded.config.processing.sensor_coverage["viirs"].start_yyyymm == 201201


def test_invalid_sensor_keys_rejected(tmp_path: Path) -> None:
    cfg = _load_example_cfg_dict()
    cfg.setdefault("processing", {})
    cfg["processing"]["sensor_time_ranges"] = {
        "noaa": {"start_yyyymm": 202401, "end_yyyymm": 202402, "timezone": "UTC"}
    }

    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    with pytest.raises(
        ValueError, match=r"Invalid sensor key\(s\) in processing\.sensor_time_ranges"
    ):
        load_config(p, validate_paths=False, repo_root=_repo_root())


def test_sensor_time_ranges_require_bounded_ranges(tmp_path: Path) -> None:
    cfg = _load_example_cfg_dict()
    cfg.setdefault("processing", {})
    cfg["processing"]["sensor_time_ranges"] = {
        "viirs": {"start_yyyymm": 202401, "end_yyyymm": None, "timezone": "UTC"}
    }

    p = tmp_path / "bad_bounds.yaml"
    p.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")

    with pytest.raises(
        ValueError,
        match=r"processing\.sensor_time_ranges\.viirs requires both start_yyyymm and end_yyyymm",
    ):
        load_config(p, validate_paths=False, repo_root=_repo_root())


def test_sensor_coverage_requires_start_and_orders_bounds(tmp_path: Path) -> None:
    cfg = _load_example_cfg_dict()
    cfg.setdefault("processing", {})

    # Missing start_yyyymm
    cfg["processing"]["sensor_coverage"] = {
        "viirs": {"start_yyyymm": None, "end_yyyymm": 202402, "timezone": "UTC"}
    }
    p1 = tmp_path / "bad_cov1.yaml"
    p1.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    with pytest.raises(
        ValueError,
        match=r"processing\.sensor_coverage\.viirs requires start_yyyymm when end_yyyymm is set",
    ):
        load_config(p1, validate_paths=False, repo_root=_repo_root())

    # start_yyyymm > end_yyyymm
    cfg = _load_example_cfg_dict()
    cfg.setdefault("processing", {})
    cfg["processing"]["sensor_coverage"] = {
        "viirs": {"start_yyyymm": 202402, "end_yyyymm": 202401, "timezone": "UTC"}
    }
    p2 = tmp_path / "bad_cov2.yaml"
    p2.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    with pytest.raises(
        ValueError, match=r"processing\.sensor_coverage\.viirs requires start_yyyymm <= end_yyyymm"
    ):
        load_config(p2, validate_paths=False, repo_root=_repo_root())
