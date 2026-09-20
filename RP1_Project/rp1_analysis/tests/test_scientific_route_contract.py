from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from rp1_analysis_v1.config import ConfigurationError, load_configuration_bundle

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"


def _copy(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    root.mkdir(parents=True)
    shutil.copytree(CONFIG, root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    return root / "config"


def _mutate(path: Path, fn) -> None:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    fn(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")


def test_rq2_route_is_exactly_the_configured_final_authority() -> None:
    bundle = load_configuration_bundle(CONFIG)
    rq2 = bundle.analysis.research_questions["rq2"]
    assert rq2["effect_estimator"] == "sens_slope"
    assert rq2["inferential_test"]["method"] == "studentized_global_mann_kendall_permutation"
    assert rq2["inferential_test"]["bandwidth_rule"] == "floor_n_power_one_third"
    assert rq2["inferential_test"]["variance_floor"] == 0.001
    assert rq2["inferential_test"]["permutations"] == 9999
    assert rq2["inferential_test"]["p_value_method"] == "monte_carlo_plus_one"
    assert rq2["multiple_testing"]["method"] == "benjamini_hochberg"
    assert rq2["multiple_testing"]["family_size"] == 5
    assert "bandwidth" not in rq2["inferential_test"]


def test_unregistered_rq2_method_is_rejected(tmp_path: Path) -> None:
    config = _copy(tmp_path)
    _mutate(config / "analysis_contract.yml", lambda raw: raw["research_questions"]["rq2"]["inferential_test"].__setitem__("method", "unregistered_rq2_method"))
    with pytest.raises(ConfigurationError, match="Unknown method identifier|Study methods"):
        load_configuration_bundle(config)


def test_rq2_realised_bandwidth_cannot_become_parallel_config_authority(tmp_path: Path) -> None:
    config = _copy(tmp_path)
    _mutate(config / "analysis_contract.yml", lambda raw: raw["research_questions"]["rq2"]["inferential_test"].__setitem__("bandwidth", 2))
    with pytest.raises(ConfigurationError, match="derived"):
        load_configuration_bundle(config)


def test_rq3_route_is_exactly_the_configured_final_authority() -> None:
    bundle = load_configuration_bundle(CONFIG)
    rq3 = bundle.analysis.research_questions["rq3"]
    assert rq3["estimator"] == "firth_penalized_gee"
    assert rq3["family"] == "binomial"
    assert rq3["link"] == "logit"
    assert rq3["working_correlation"] == "independence"
    assert rq3["covariance"] == "morel_bokossa_neerchal"
    assert rq3["reference_distribution"] == "standard_normal_wald"
    assert [item["term_name"] for item in rq3["predictors"]] == [
        "log2_viirs_det_primary",
        "log2_viirs_frp_mean_mw",
        "log2_modis_burnable_km2_union_ba2012",
    ]


@pytest.mark.parametrize(("field", "value"), [("estimator", "unregistered_estimator"), ("working_correlation", "unregistered_correlation"), ("covariance", "unregistered_covariance")])
def test_unregistered_rq3_authorities_are_rejected(tmp_path: Path, field: str, value: str) -> None:
    config = _copy(tmp_path)
    _mutate(config / "analysis_contract.yml", lambda raw: raw["research_questions"]["rq3"].__setitem__(field, value))
    with pytest.raises(ConfigurationError, match="Unknown method identifier|Study methods"):
        load_configuration_bundle(config)


def test_parallel_rq3_selection_key_is_rejected(tmp_path: Path) -> None:
    config = _copy(tmp_path)
    _mutate(config / "analysis_contract.yml", lambda raw: raw["research_questions"]["rq3"].__setitem__("selection_enabled", True))
    with pytest.raises(ConfigurationError, match="unsupported parallel authority"):
        load_configuration_bundle(config)
