from __future__ import annotations

from pathlib import Path

import pytest
from geo_data_prep.core.config import ConfigError, load_config
from geo_data_prep.core.runtime import run_from_config


def test_valid_example_config_loads() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    cfg_path = repo_root / "configs" / "example.yaml"
    cfg = load_config(cfg_path)
    assert cfg.schema_version.startswith("1")
    assert cfg.inputs.zones.label_field != ""
    assert cfg.outputs.out_dir != ""


def test_missing_required_keys_fails_with_readable_message(tmp_path: Path) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        """
schema_version: "1.0"
inputs:
  zones:
    path: "data/raw/zones/zones_input.shp"
    label_field: "zone_name"
  districts:
    path: "data/raw/districts/districts_input.shp"
    label_field: "district_name"
levels:
  zone:
    level: "acz"
  district:
    level: "district"
crs:
  working_crs: "EPSG:32630"
  plot_crs: "EPSG:4326"
# outputs is missing on purpose
derivations:
  zone_code:
    mapping: {}
    fallback:
      method: "initials"
      collision: "suffix"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as ei:
        load_config(bad)

    msg = str(ei.value)
    assert "Config validation failed" in msg
    assert "outputs" in msg  # required section should be called out


def test_missing_label_field_fails(tmp_path: Path) -> None:
    bad = tmp_path / "bad_label.yaml"
    bad.write_text(
        """
schema_version: "1.0"
inputs:
  zones:
    path: "data/raw/zones/zones_input.shp"
    # label_field intentionally missing
  districts:
    path: "data/raw/districts/districts_input.shp"
    label_field: "district_name"
levels:
  zone:
    level: "acz"
  district:
    level: "district"
crs:
  working_crs: "EPSG:32630"
  plot_crs: "EPSG:4326"
outputs:
  out_dir: "out"
  toggles:
    splits: false
    plots: false
  basenames:
    zones: "zones_stage1"
    districts: "districts_stage1"
derivations:
  zone_code:
    mapping: {}
    fallback:
      method: "initials"
      collision: "suffix"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as ei:
        load_config(bad)

    msg = str(ei.value)
    assert "inputs.zones.label_field" in msg


def test_run_from_config_missing_stage1_input_reports_access_guidance(tmp_path: Path) -> None:
    cfg = tmp_path / "missing_inputs.yaml"
    cfg.write_text(
        """
schema_version: "1.0"
inputs:
  zones:
    path: "data/raw/zones/zones.shp"
    label_field: "zone_name"
  districts:
    path: "data/raw/districts/districts.shp"
    label_field: "district_name"
  aoi:
    enabled: false
    path: "data/raw/aoi/aoi.shp"
levels:
  zone:
    level: "acz"
  district:
    level: "district"
crs:
  working_crs: "EPSG:32630"
  plot_crs: "EPSG:4326"
outputs:
  out_dir: "out"
  toggles:
    splits: false
    plots: false
  basenames:
    zones: "zones_stage1"
    districts: "districts_stage1"
derivations:
  zone_code:
    mapping: {}
    fallback:
      method: "initials"
      collision: "suffix"
""".lstrip(),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError) as excinfo:
        run_from_config(cfg, run_id="missing_stage1_inputs")

    msg = str(excinfo.value)
    assert "Missing required Stage 1 input `zones`" in msg
    assert "docs/data_access.md" in msg
    assert "README.md" in msg
    assert "Required by stage: geo_data_prep (Stage 1)." in msg
