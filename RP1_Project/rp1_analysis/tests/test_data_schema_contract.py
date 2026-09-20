from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

from rp1_analysis_v1.config import ConfigurationError, load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.validation import validate_data_authorities

SUBPROJECT = Path(__file__).resolve().parents[1]
PATHS = ProjectPaths.discover(SUBPROJECT)
BUNDLE = load_configuration_bundle(SUBPROJECT / "config")
SCHEMA = BUNDLE.data_schema


def test_complete_111_field_authority_matches_both_panels_and_manifest() -> None:
    assert SCHEMA.field_count == 111
    assert len(SCHEMA.fields) == 111
    names = list(SCHEMA.field_order)
    assert len(names) == len(set(names)) == 111
    for panel_id in ("acz_monthly", "district_monthly"):
        panel = SCHEMA.panel(panel_id)
        header = pd.read_csv(PATHS.resolve_inside(panel.path), nrows=0).columns.tolist()
        assert header == names
        assert panel.column_count == 111
    manifest = json.loads(PATHS.resolve_inside(SCHEMA.auxiliary_inputs["panel_manifest"]["path"]).read_text())
    assert manifest["final_schema_columns"] == names


def test_every_field_has_complete_physical_semantic_metadata() -> None:
    allowed_dtype = {"string", "integer", "number"}
    for field in SCHEMA.fields:
        assert field.dtype in allowed_dtype
        assert field.semantic_type
        assert field.unit
        assert field.structural_support in SCHEMA.source_supports
        assert isinstance(field.nullable, bool)
        assert isinstance(field.required_when_supported, bool)
        assert field.source_family
        if field.minimum is not None and field.maximum is not None:
            assert field.minimum <= field.maximum
        if field.categorical_domain is not None:
            assert field.categorical_domain in SCHEMA.categorical_domains
            assert SCHEMA.categorical_domains[field.categorical_domain]


def test_data_schema_does_not_duplicate_rq_role_authority() -> None:
    raw = yaml.safe_load((SUBPROJECT / "config/data_schema_contract.yml").read_text())
    assert "research_questions" not in raw
    assert "field_roles" not in raw
    assert "scientific_exclusions" not in raw
    assert all("rq" not in field for field in raw["fields"])


def test_panel_authorities_are_exact_and_monthly() -> None:
    expected = {
        "acz_monthly": (1440, 5, "2001-01", "2024-12"),
        "district_monthly": (74880, 260, "2001-01", "2024-12"),
    }
    for panel_id, values in expected.items():
        spec = SCHEMA.panel(panel_id)
        assert (spec.expected_rows, spec.expected_units, spec.start, spec.end) == values
        assert spec.temporal_frequency == "monthly"
        assert spec.primary_key == ("unit_id", "yyyymm")


def test_geometry_members_and_identity_relationships_are_governed() -> None:
    for geometry_id in ("acz", "district"):
        spec = SCHEMA.geometry(geometry_id)
        assert spec.required_members
        assert all(PATHS.resolve_inside(member).is_file() for member in spec.required_members)
        assert PATHS.resolve_inside(spec.path).is_file()
    rels = {r.relationship_id: r for r in SCHEMA.relationships}
    parent_id = rels["district_panel_parent_id_to_acz_unit_id"]
    assert (parent_id.from_field, parent_id.to_field, parent_id.cardinality) == (
        "parent_id", "unit_id", "many_to_one"
    )
    parent_code = rels["district_panel_parent_code_to_acz_unit_code"]
    assert (parent_code.from_field, parent_code.to_field) == ("parent_code", "unit_code")


def test_declared_panel_relationships_hold_in_actual_data() -> None:
    authorities = load_data_authorities(PATHS, SCHEMA)
    acz = authorities.acz_panel[["unit_id", "unit_code"]].drop_duplicates()
    district = authorities.district_panel[["parent_id", "parent_code"]].drop_duplicates()
    assert set(district["parent_id"]) <= set(acz["unit_id"])
    assert set(district["parent_code"]) <= set(acz["unit_code"])


def test_additive_reconciliation_authority_declares_only_additive_fields() -> None:
    assert len(SCHEMA.additive_fields) == 8
    assert all(SCHEMA.field(name).additive for name in SCHEMA.additive_fields)


def test_exact_analytical_population_contracts_are_proved_from_data() -> None:
    authorities = load_data_authorities(PATHS, SCHEMA)
    summary = validate_data_authorities(authorities, BUNDLE.analysis, SCHEMA)
    assert summary.acz_monthly_rows == 1440
    assert summary.district_monthly_rows == 74880
    assert summary.district_spatial_universe_count == 260
    assert summary.long_run_eligible_count == 250
    assert summary.paired_eligible_count == 249
    assert summary.paired_rows == 38595
    assert summary.rq3_gee_units == 249
    assert summary.rq3_gee_rows == 22939
    assert summary.reconciliation["passed"].all()


def test_schema_documentation_is_deterministically_derived() -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SUBPROJECT / "src")
    env["RP1_ANALYSIS_V1_ROOT"] = str(SUBPROJECT)
    result = subprocess.run(
        [sys.executable, str(SUBPROJECT / "scripts/render_data_schema_contract.py"), "--check"],
        cwd=SUBPROJECT, env=env, text=True, capture_output=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "DATA_SCHEMA_DOCUMENTATION_FIELDS=111" in result.stdout


def _temporary_config(tmp_path: Path) -> Path:
    target = tmp_path / "config"
    shutil.copytree(SUBPROJECT / "config", target)
    shutil.copy2(SUBPROJECT / "pyproject.toml", tmp_path / "pyproject.toml")
    return target


def test_unknown_relationship_field_is_rejected_at_configuration_load(tmp_path: Path) -> None:
    target = _temporary_config(tmp_path)
    path = target / "data_schema_contract.yml"
    raw = yaml.safe_load(path.read_text())
    raw["relationships"][0]["from_field"] = "not_a_governed_field"
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(ConfigurationError, match="unknown source field"):
        load_configuration_bundle(target)


def test_nonadditive_field_cannot_enter_additive_reconciliation(tmp_path: Path) -> None:
    target = _temporary_config(tmp_path)
    path = target / "data_schema_contract.yml"
    raw = yaml.safe_load(path.read_text())
    raw["additive_reconciliation"]["district_to_acz"]["fields"].append(
        "modis_ba_km2_per100km2_union_ba2001"
    )
    path.write_text(yaml.safe_dump(raw, sort_keys=False))
    with pytest.raises(ConfigurationError, match="not declared additive"):
        load_configuration_bundle(target)
