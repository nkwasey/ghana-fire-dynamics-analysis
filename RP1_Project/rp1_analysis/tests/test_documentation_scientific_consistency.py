from __future__ import annotations

from pathlib import Path
import re
import subprocess
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "Data_Contract.md"
VARIABLE_MAP = ROOT / "docs" / "Variable_Map.md"
METHODS_DOC = ROOT / "docs" / "Analysis_Methods_Contract.md"
README = ROOT / "README.md"


def _yaml(name: str) -> dict:
    return yaml.safe_load((ROOT / "config" / name).read_text(encoding="utf-8"))


def _analysis() -> dict:
    return _yaml("analysis_contract.yml")


def _resolve(field_roles: dict, role: str) -> str:
    group, key = role.split(".", 1)
    return str(field_roles[group][key])


def _section(text: str, heading: str) -> str:
    marker = f"## {heading}"
    assert marker in text
    tail = text.split(marker, 1)[1]
    return tail.split("\n## ", 1)[0]


def test_data_contract_config_projection_is_deterministic() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/render_data_contract_roles.py", "--check"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "RP1_DATA_CONTRACT_ROLE_PROJECTION=PASS" in result.stdout


def test_rq2_documentation_matches_executable_contract() -> None:
    analysis = _analysis()
    rq2 = analysis["research_questions"]["rq2"]
    fr = analysis["field_roles"]
    doc = DOC.read_text(encoding="utf-8")
    projection = _section(doc, "Executable scientific-role projection")

    assert rq2["effect_estimator"] == "sens_slope"
    assert rq2["inferential_test"]["method"] == "studentized_global_mann_kendall_permutation"
    assert rq2["rate"]["denominator_support"] == "fixed_ba2001_burnable_union"
    assert rq2["inferential_test"]["permutations"] == 9999
    assert rq2["multiple_testing"]["family_size"] == 5
    assert _resolve(fr, rq2["rate"]["numerator_role"]) in projection
    assert _resolve(fr, rq2["rate"]["denominator_role"]) in projection
    assert rq2["inferential_test"]["method"] in projection
    assert rq2["effect_estimator"] in projection
    assert "Additional denominator analysis | `none`" in projection


def test_rq2_documentation_does_not_reactivate_annual_denominator() -> None:
    doc = DOC.read_text(encoding="utf-8").lower()
    assert "required sensitivity denominator" not in doc
    assert "annual-denominator sensitivity" not in doc
    annual_field_line = next(line for line in doc.splitlines() if "modis_burnable_km2_annual_ba2001" in line)
    assert "not used by final rq2" in annual_field_line


def test_rq3_role_classes_match_configured_design() -> None:
    analysis = _analysis()
    rq3 = analysis["research_questions"]["rq3"]
    fr = analysis["field_roles"]
    doc = DOC.read_text(encoding="utf-8")
    rq3_doc = _section(doc, "RQ3 fields")
    projection = _section(doc, "Executable scientific-role projection")

    focal = [_resolve(fr, p["field_role"]) for p in rq3["predictors"] if p["role"] == "focal"]
    adjustment = [_resolve(fr, p["field_role"]) for p in rq3["predictors"] if p["role"] == "adjustment"]
    factors = [_resolve(fr, f["field_role"]) for f in rq3["factors"]]
    support = [fr["rq3"]["viirs_support"], fr["rq3"]["ba2012_support"], fr["rq3"]["viirs_presence"]]
    outcome = _resolve(fr, rq3["outcome"]["burned_area_presence_role"])

    for field in support + [outcome] + focal + adjustment + factors:
        assert f"`{field}`" in rq3_doc
    for field in focal + adjustment + factors:
        assert f"`{field}`" in projection

    assert rq3["estimator"] == "firth_penalized_gee"
    assert rq3["covariance"] == "morel_bokossa_neerchal"
    assert rq3["reference_distribution"] == "standard_normal_wald"
    assert rq3["excluded_predictor_roles"] == ["rq3.active_days", "rq3.modis_af_presence"]
    assert "31 columns" in projection


def test_rq3_reference_categories_are_config_owned_and_documented() -> None:
    rq3 = _analysis()["research_questions"]["rq3"]
    factors = {f["factor_id"]: f for f in rq3["factors"]}
    projection = _section(DOC.read_text(encoding="utf-8"), "Executable scientific-role projection")
    assert (factors["month"]["reference"], factors["month"]["reference_label"]) == (1, "January")
    assert factors["year"]["reference"] == 2013
    assert (factors["acz"]["reference"], factors["acz"]["reference_label"]) == ("CZ", "Coastal Zone")
    for token in ("January", "2013", "Coastal Zone", "CZ"):
        assert token in projection


def test_excluded_rq3_source_fields_are_explicitly_excluded_not_predictors() -> None:
    rq3_doc = _section(DOC.read_text(encoding="utf-8"), "RQ3 fields")
    excluded_row = next(line for line in rq3_doc.splitlines() if "Governed source fields excluded from production RQ3" in line)
    assert "`viirs_days_active_nh`" in excluded_row
    assert "`modis_det_primary_any`" in excluded_row
    assert "excluded from the final regression design" in excluded_row
    lower = rq3_doc.lower()
    assert "modis active-fire corroboration:" not in lower
    assert "active days:" not in lower
    assert "independent validation/corroboration authority" in lower


def test_secondary_and_publication_documentation_match_contracts() -> None:
    analysis = _analysis()
    sec = analysis["secondary_analysis"]
    scenarios = {s["scenario_id"]: s for s in sec["scenarios"]}
    assert scenarios["MCD64A1_POISSON_PRIMARY"]["model"] == "discrete_poisson"
    assert scenarios["MCD64A1_POISSON_PRIMARY"]["exposure_role"] == "secondary.mcd64a1_exposure"
    assert scenarios["VIIRS_STP_PRIMARY"]["model"] == "space_time_permutation"
    assert scenarios["VIIRS_STP_PRIMARY"]["exposure_role"] is None
    assert sec["common"]["max_spatial_percent"] == 50
    assert sec["common"]["max_temporal_months"] == 12
    assert sec["common"]["monte_carlo_replicates"] == 999
    assert sec["common"]["reporting_method"] == "hierarchical_non_overlapping"
    assert sec["common"]["geographical_overlap"] is False
    assert sec["common"]["gini_optimised_reporting"] is False

    output = _yaml("output_contract.yml")
    figures = _yaml("figure_contract.yml")
    tables = output["publication_outputs"]["tables"]
    main_tables = [x["id"] for x in tables if x["role"] == "manuscript"]
    supp_tables = [x["id"] for x in tables if x["role"] == "supplementary"]
    main_figures = [x["id"] for x in figures["figures"] if x["role"] == "manuscript"]
    supp_figures = [x["id"] for x in figures["figures"] if x["role"] == "supplementary"]
    assert main_tables == ["T1", "T2", "T3"]
    assert supp_tables == ["S1", "S2", "S3", "S4", "S5", "S6"]
    assert main_figures == ["F2", "F3", "F4", "F5", "F6"]
    assert supp_figures == ["S1"]


def test_public_scientific_docs_are_cross_consistent_on_high_risk_roles() -> None:
    docs = {
        "data": DOC.read_text(encoding="utf-8"),
        "variables": VARIABLE_MAP.read_text(encoding="utf-8"),
        "methods": METHODS_DOC.read_text(encoding="utf-8"),
        "readme": README.read_text(encoding="utf-8"),
    }
    combined = "\n".join(docs.values()).lower()
    assert "required sensitivity denominator" not in combined
    assert "annual-denominator sensitivity" not in combined
    assert "modis active-fire co-detection are not model predictors" in docs["readme"].lower()
    assert "active-fire days and modis active-fire co-detection are excluded from the final model" in docs["methods"].lower()
    assert "not used by final rq2" in docs["variables"].lower()
    assert re.search(r"governed source fields excluded from production rq3.*viirs_days_active_nh.*modis_det_primary_any", docs["data"], re.I)
