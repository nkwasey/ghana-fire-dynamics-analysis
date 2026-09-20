from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
import yaml

from rp1_analysis_v1.config import ConfigurationError, load_configuration_bundle, rq2_trend_parameters
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.inference import MethodAdmissibilityError
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.trend_robustness import (
    PRIMARY_RATE,
    TrendRobustnessError,
    build_acz_annual_ba_series,
    build_rq2_tables,
)
from rp1_analysis_v1.validation import validate_data_authorities

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"


def _copy_config(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    shutil.copytree(CONFIG, root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    return root / "config"


def _mutate(path: Path, fn) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def test_rq2_parameter_projection_contains_rule_not_realised_bandwidth() -> None:
    bundle = load_configuration_bundle(CONFIG)
    params = rq2_trend_parameters(bundle.analysis)
    assert params.effect_estimator == "sens_slope"
    assert params.inferential_test == "studentized_global_mann_kendall_permutation"
    assert params.bandwidth_rule == "floor_n_power_one_third"
    assert params.requires_distinct_observations is True
    assert params.on_ties == "fail_closed"
    assert not hasattr(params, "bandwidth")
    assert params.permutations == int(bundle.analysis.research_questions["rq2"]["inferential_test"]["permutations"])


def test_real_governed_annual_series_is_complete_and_fixed_support() -> None:
    bundle = load_configuration_bundle(CONFIG)
    paths = ProjectPaths(SUBPROJECT)
    authorities = load_data_authorities(paths, bundle.data_schema)
    annual = build_acz_annual_ba_series(authorities.acz_panel, bundle.analysis)
    rq2 = bundle.analysis.research_questions["rq2"]
    assert len(annual) == int(rq2["expected_series_count"]) * int(rq2["expected_n_per_series"])
    assert annual.groupby("unit_id", observed=True)["year"].nunique().eq(int(rq2["expected_n_per_series"])).all()
    assert annual.groupby("unit_id", observed=True)["fixed_burnable_km2"].nunique().eq(1).all()
    assert pd.to_numeric(annual[PRIMARY_RATE], errors="coerce").notna().all()


def test_rq2_production_tables_execute_exact_five_series_family() -> None:
    bundle = load_configuration_bundle(CONFIG)
    paths = ProjectPaths(SUBPROJECT)
    authorities = load_data_authorities(paths, bundle.data_schema)
    summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    tables = build_rq2_tables(
        authorities, summary, bundle.analysis, bundle.methods,
        configuration_sha256=bundle.configuration_sha256,
    )
    primary = tables.primary_trend_authority
    assert len(primary) == 5
    assert primary["n"].eq(24).all()
    assert primary["realised_bandwidth"].eq(2).all()
    assert primary["permutation_count"].eq(9999).all()
    assert primary["raw_p"].gt(0).all()
    assert primary["bh_q"].notna().all()
    assert len(tables.rq2_full_authority) == 120
    from rp1_analysis_v1.trend_robustness import PRIMARY_TREND_COLUMNS
    assert tuple(primary.columns) == PRIMARY_TREND_COLUMNS


def test_synthetic_rate_scale_mutation_propagates_without_python_edit(tmp_path: Path) -> None:
    config = _copy_config(tmp_path)
    _mutate(
        config / "analysis_contract.yml",
        lambda raw: raw["research_questions"]["rq2"]["rate"].__setitem__("scale_per_km2", 10),
    )
    mutated = load_configuration_bundle(config)
    baseline = load_configuration_bundle(CONFIG)
    panel = load_data_authorities(ProjectPaths(SUBPROJECT), baseline.data_schema).acz_panel
    base = build_acz_annual_ba_series(panel, baseline.analysis)
    changed = build_acz_annual_ba_series(panel, mutated.analysis)
    assert changed[PRIMARY_RATE].to_numpy().tolist() == pytest.approx((base[PRIMARY_RATE] / 10.0).to_numpy())


def test_annual_series_rejects_nonconstant_fixed_support() -> None:
    bundle = load_configuration_bundle(CONFIG)
    panel = load_data_authorities(ProjectPaths(SUBPROJECT), bundle.data_schema).acz_panel.copy()
    rq2 = bundle.analysis.research_questions["rq2"]
    denominator = bundle.analysis.field_roles["rq2"]["fixed_burnable_area"]
    first_unit = panel["unit_id"].iloc[0]
    idx = panel.index[panel["unit_id"].eq(first_unit)][0]
    panel.loc[idx, denominator] = float(panel.loc[idx, denominator]) + 1.0
    with pytest.raises(TrendRobustnessError, match="invalid fixed support"):
        build_acz_annual_ba_series(panel, bundle.analysis)


def test_rq2_reference_admissibility_is_config_owned_and_fail_closed(tmp_path: Path) -> None:
    baseline = load_configuration_bundle(CONFIG)
    params = rq2_trend_parameters(baseline.analysis)
    assert params.requires_distinct_observations is True
    assert params.on_ties == "fail_closed"

    config = _copy_config(tmp_path)
    _mutate(
        config / "analysis_contract.yml",
        lambda raw: raw["research_questions"]["rq2"]["inferential_test"]["reference_admissibility"].__setitem__("on_ties", "allow"),
    )
    mutated = load_configuration_bundle(config)
    with pytest.raises(ConfigurationError, match="strict reference admissibility"):
        rq2_trend_parameters(mutated.analysis)


def test_strict_rq2_production_route_rejects_realised_annual_tie() -> None:
    bundle = load_configuration_bundle(CONFIG)
    paths = ProjectPaths(SUBPROJECT)
    authorities = load_data_authorities(paths, bundle.data_schema)
    summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    panel = authorities.acz_panel.copy()
    rq2 = bundle.analysis.research_questions["rq2"]
    ba_field = bundle.analysis.field_roles["rq2"]["burned_area"]
    keys = bundle.analysis.field_roles["keys"]
    unit_id = keys["unit_id"]
    year_field = keys["year"]
    first_unit = str(panel[unit_id].iloc[0])
    source = panel.loc[panel[unit_id].eq(first_unit) & panel[year_field].eq(2001), ba_field].to_numpy(copy=True)
    target_idx = panel.index[panel[unit_id].eq(first_unit) & panel[year_field].eq(2002)]
    assert len(source) == len(target_idx) == 12
    panel.loc[target_idx, ba_field] = source
    tied_authorities = replace(authorities, acz_panel=panel)
    with pytest.raises(MethodAdmissibilityError, match="requires tie-free annual observations"):
        build_rq2_tables(
            tied_authorities, summary, bundle.analysis, bundle.methods,
            configuration_sha256=bundle.configuration_sha256,
        )
