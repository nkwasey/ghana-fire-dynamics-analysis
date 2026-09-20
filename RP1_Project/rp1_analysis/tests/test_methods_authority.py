from __future__ import annotations

import re
import shutil
from pathlib import Path

import pytest
import yaml

from rp1_analysis_v1.config import ConfigurationError, load_configuration_bundle
from rp1_analysis_v1.method_authority import (
    method_is_implemented,
    registered_implementation_ids,
    require_implementation,
    require_method_authority,
)

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"
ALLOWED = {
    "method_defined",
    "study_design_defined",
    "data_defined",
    "computational_reproducibility_only",
}


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir()
    shutil.copytree(CONFIG, root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    return root / "config"


def _mutate(path: Path, fn) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def test_method_authority_entries_are_complete_and_outcome_tuning_is_forbidden() -> None:
    bundle = load_configuration_bundle(CONFIG)
    assert bundle.methods.authorities
    for item in bundle.methods.authorities:
        assert item.method_id
        assert item.implementation_id
        assert item.family
        assert item.protocol_reference
        assert item.authoritative_reference
        assert item.governed_variant
        assert item.outcome_tuning_allowed is False
        assert set(item.parameter_provenance.values()) <= ALLOWED
        require_implementation(item.implementation_id)


def test_method_ids_live_only_in_yaml_and_bind_to_registered_capabilities() -> None:
    bundle = load_configuration_bundle(CONFIG)
    implementation_ids = {item.implementation_id for item in bundle.methods.authorities}
    assert implementation_ids <= registered_implementation_ids()
    assert all(require_method_authority(bundle.methods, item.method_id) == item for item in bundle.methods.authorities)


def test_current_scientific_targets_have_explicit_qualification_states() -> None:
    bundle = load_configuration_bundle(CONFIG)
    by_id = {item.method_id: item for item in bundle.methods.authorities}
    required = {
        "sens_slope",
        "studentized_global_mann_kendall_permutation",
        "benjamini_hochberg",
        "gini_coefficient",
        "circular_mean_resultant",
        "global_morans_i",
        "local_morans_i",
        "firth_penalized_gee",
        "binomial",
        "logit",
        "independence",
        "morel_bokossa_neerchal",
        "standard_normal_wald",
        "variance_inflation_factor",
        "observed_covariate_predictive_standardisation",
        "discrete_poisson",
        "space_time_permutation",
        "hierarchical_non_overlapping",
    }
    assert required <= set(by_id)
    assert by_id["studentized_global_mann_kendall_permutation"].status == "implemented"
    assert by_id["studentized_global_mann_kendall_permutation"].qualification_status == "independent_reference_qualified"
    assert by_id["observed_covariate_predictive_standardisation"].status == "implemented"
    assert by_id["observed_covariate_predictive_standardisation"].qualification_status == "independent_manual_reference_qualified"
    assert by_id["firth_penalized_gee"].qualification_status == "reference_parity_qualified"
    assert by_id["morel_bokossa_neerchal"].qualification_status == "reference_parity_qualified"
    assert by_id["standard_normal_wald"].qualification_status == "standard_reference_qualified"
    assert by_id["discrete_poisson"].qualification_status == "python_interface_qualified_external_execution_deferred"
    assert by_id["space_time_permutation"].qualification_status == "python_interface_qualified_external_execution_deferred"
    assert by_id["hierarchical_non_overlapping"].qualification_status == "configuration_interface_qualified"


def test_method_authority_set_is_exactly_the_current_scientific_contract() -> None:
    bundle = load_configuration_bundle(CONFIG)
    expected = {
        "within_acz_rate_difference", "median_iqr", "gini_coefficient", "circular_mean_resultant",
        "queen_contiguity", "global_morans_i", "local_morans_i", "permutation", "sens_slope",
        "studentized_global_mann_kendall_permutation", "benjamini_hochberg", "firth_penalized_gee",
        "binomial", "logit", "independence", "morel_bokossa_neerchal", "standard_normal_wald",
        "log2_positive", "categorical", "variance_inflation_factor",
        "observed_covariate_predictive_standardisation", "discrete_poisson", "space_time_permutation",
        "hierarchical_non_overlapping",
    }
    assert set(bundle.methods.method_ids) == expected

def test_method_authority_yaml_contains_no_python_callables() -> None:
    raw = yaml.safe_load((CONFIG / "method_authorities.yml").read_text(encoding="utf-8"))
    forbidden = {"callable", "function", "import", "module", "expression", "python_path"}
    for item in raw["authorities"]:
        assert not forbidden.intersection(item)


def test_unknown_method_and_implementation_are_rejected() -> None:
    bundle = load_configuration_bundle(CONFIG)
    with pytest.raises(ValueError, match="Unknown governed method"):
        require_method_authority(bundle.methods, "os.system")
    with pytest.raises(ValueError, match="Unregistered implementation"):
        require_implementation("os.system")


def test_config_status_and_software_capability_must_agree() -> None:
    bundle = load_configuration_bundle(CONFIG)
    assert method_is_implemented(bundle.methods, "firth_penalized_gee") is True
    assert method_is_implemented(bundle.methods, "studentized_global_mann_kendall_permutation") is True
    assert method_is_implemented(bundle.methods, "observed_covariate_predictive_standardisation") is True


def test_yaml_arbitrary_implementation_injection_fails(tmp_path: Path) -> None:
    config = _copy(tmp_path)
    _mutate(
        config / "method_authorities.yml",
        lambda raw: raw["authorities"][0].__setitem__("implementation_id", "os.system"),
    )
    with pytest.raises(ConfigurationError, match="Unregistered implementation"):
        load_configuration_bundle(config)


def test_yaml_invalid_parameter_provenance_fails(tmp_path: Path) -> None:
    config = _copy(tmp_path)
    _mutate(
        config / "method_authorities.yml",
        lambda raw: raw["authorities"][0]["parameter_provenance"].__setitem__("x", "outcome_selected"),
    )
    with pytest.raises(ConfigurationError, match="invalid parameter provenance"):
        load_configuration_bundle(config)


def test_yaml_outcome_tuning_true_fails(tmp_path: Path) -> None:
    config = _copy(tmp_path)
    _mutate(
        config / "method_authorities.yml",
        lambda raw: raw["authorities"][0].__setitem__("outcome_tuning_allowed", True),
    )
    with pytest.raises(ConfigurationError, match="outcome_tuning_allowed=false"):
        load_configuration_bundle(config)


def test_method_authority_documents_describe_current_scientific_targets() -> None:
    register = (SUBPROJECT / "docs/Method_Authority_Register.md").read_text(encoding="utf-8")
    validation = (SUBPROJECT / "docs/Reference_Method_Validation.md").read_text(encoding="utf-8")
    assert "Romano–Tirlea" in register
    assert "Firth-type penalised GEE" in register
    assert "standard-normal Wald" in register
    assert "hierarchical non-overlapping" in register
    assert "hierarchical geographically non-overlapping" in register
    assert "external SaTScan" in validation


def test_reference_qualification_script_and_fixture_roots_exist() -> None:
    assert (SUBPROJECT / "scripts/qualify_reference_methods.py").is_file()
    assert (SUBPROJECT / "tests/reference_methods/pgee_reference_implementations.py").is_file()
    assert (SUBPROJECT / "tests/fixtures/reference_methods/satscan/known_good").is_file()


def test_project_paths_exposes_governed_reference_fixture_root() -> None:
    from rp1_analysis_v1.paths import ProjectPaths
    assert ProjectPaths(SUBPROJECT).reference_fixture_root == (
        SUBPROJECT / "tests/fixtures/reference_methods"
    ).resolve()


def test_rq2_parameter_provenance_distinguishes_method_from_study_choices() -> None:
    bundle = load_configuration_bundle(CONFIG)
    authority = require_method_authority(bundle.methods, "studentized_global_mann_kendall_permutation")
    provenance = dict(authority.parameter_provenance)
    assert provenance["bandwidth_rule"] == "study_design_defined"
    assert provenance["p_value_construction"] == "study_design_defined"
    assert provenance["variance_floor"] == "study_design_defined"
    assert provenance["permutations"] == "study_design_defined"
    assert provenance["random_seed"] == "computational_reproducibility_only"
    assert provenance["studentisation"] == "method_defined"
