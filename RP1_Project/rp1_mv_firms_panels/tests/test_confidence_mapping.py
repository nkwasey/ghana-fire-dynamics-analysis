# file: tests/test_confidence_mapping.py
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from mv_firms_panels.core.config import load_config
from mv_firms_panels.sensors.modis import modis_conf_cat_from_confidence
from mv_firms_panels.sensors.viirs import viirs_conf_cat_from_confidence


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_viirs_confidence_mapping_case_insensitive() -> None:
    cfg_path = _repo_root() / "configs" / "example_project.yaml"
    loaded = load_config(cfg_path, validate_paths=False)

    s = pd.Series(["low", "Nominal", " HIGH "])
    out = viirs_conf_cat_from_confidence(
        s, viirs_map=loaded.config.processing.confidence_model.viirs_map, strict=True
    )
    assert out.tolist() == ["l", "n", "h"]


def test_viirs_confidence_mapping_unmappable_raises() -> None:
    cfg_path = _repo_root() / "configs" / "example_project.yaml"
    loaded = load_config(cfg_path, validate_paths=False)

    s = pd.Series(["low", "unknown_label"])
    with pytest.raises(ValueError):
        _ = viirs_conf_cat_from_confidence(
            s, viirs_map=loaded.config.processing.confidence_model.viirs_map, strict=True
        )


def test_modis_confidence_threshold_mapping_defaults() -> None:
    cfg_path = _repo_root() / "configs" / "example_project.yaml"
    loaded = load_config(cfg_path, validate_paths=False)

    thresholds = loaded.config.processing.confidence_model.modis_thresholds_pct
    s = pd.Series([0, 29.9, 30, 79.999, 80, 100])
    out = modis_conf_cat_from_confidence(s, thresholds_pct=thresholds, strict=True)
    assert out.tolist() == ["l", "l", "n", "n", "h", "h"]


def test_modis_confidence_missing_or_non_numeric_raises_when_strict() -> None:
    cfg_path = _repo_root() / "configs" / "example_project.yaml"
    loaded = load_config(cfg_path, validate_paths=False)

    thresholds = loaded.config.processing.confidence_model.modis_thresholds_pct
    s = pd.Series([50, None])
    with pytest.raises(ValueError):
        _ = modis_conf_cat_from_confidence(s, thresholds_pct=thresholds, strict=True)
