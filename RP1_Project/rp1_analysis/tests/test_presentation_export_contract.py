from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from rp1_analysis_v1.config import ConfigurationError, load_configuration_bundle, load_figure_contract
from rp1_analysis_v1.design import DesignValidationError
from rp1_analysis_v1.presentation import (
    get_presentation_export_spec,
    get_presentation_exports_for_group,
    load_presentation_export_registry,
)

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"
EXPECTED_IDS = (
    "study_ghana_acz",
    "study_district_support",
    "rq1_acz_long_run_rate",
    "rq1_district_long_run_rate",
    "rq1_acz_seasonality",
    "rq1_district_departure",
    "rq1_local_moran",
    "rq1_district_seasonal_heatmap",
    "rq1_district_circular_mean_timing",
    "rq1_district_resultant_length_by_acz",
    "rq2_coastal_trend",
    "rq2_forest_trend",
    "rq2_guinea_trend",
    "rq2_sudan_trend",
    "rq2_transition_trend",
    "rq2_five_acz_comparison",
    "rq3_four_state_correspondence",
    "rq3_district_mismatch",
    "rq3_focal_effects",
    "rq3_standardised_probabilities",
    "rq4_mcd64a1_clusters",
    "rq4_viirs_clusters",
    "rq4_mcd64a1_recurrence",
    "rq4_viirs_recurrence",
)


def _copy_config(tmp_path: Path) -> Path:
    root = tmp_path / "project"
    shutil.copytree(CONFIG, root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    return root / "config"


def _mutate_figure(config: Path, mutator) -> None:
    path = config / "figure_contract.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    mutator(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")


def _export(raw: dict, export_id: str) -> dict:
    return next(item for item in raw["presentation_export"]["exports"] if item["export_id"] == export_id)


def test_registry_loads_complete_frozen_export_estate() -> None:
    bundle = load_configuration_bundle(CONFIG)
    registry = load_presentation_export_registry(bundle.figure)
    assert registry.schema == "rp1-presentation-export-v1"
    assert registry.groups == ("study", "rq1", "rq2", "rq3", "rq4")
    assert registry.export_ids == EXPECTED_IDS
    assert len(set(registry.export_ids)) == 24
    assert tuple(item.export_id for item in get_presentation_exports_for_group("rq1", bundle.figure)) == EXPECTED_IDS[2:10]
    assert get_presentation_export_spec("rq3_standardised_probabilities", bundle.figure).source_identity == "supplement_s5_rq3"


def test_registry_output_and_read_only_policy_are_configured() -> None:
    registry = load_presentation_export_registry(load_figure_contract(CONFIG / "figure_contract.yml"))
    assert registry.output.formats == ("png", "pdf")
    assert registry.output.size_role == "rectangular_landscape_20x15_cm"
    assert registry.output.raster_dpi == 300
    assert registry.output.collision_policy == "error_if_output_dir_exists"
    assert registry.output.deterministic_names is True
    assert registry.output.source_run_read_only is True
    assert registry.output.staging_policy == "temporary_sibling_then_atomic_promote"
    assert registry.run_family.required_member_suffix == "_close"
    assert registry.run_family.publication_member_suffix == "_pub"
    assert registry.run_family.secondary_member_suffix == "_sec"
    assert registry.run_family.require_closeout_validation is True


def test_rq4_exports_require_validated_results_and_governed_scenarios() -> None:
    registry = load_presentation_export_registry(load_figure_contract(CONFIG / "figure_contract.yml"))
    rq4 = registry.exports_for_group("rq4")
    assert {item.required_result_state for item in rq4} == {"RESULTS_VALIDATED"}
    assert {item.scenario for item in rq4} == {"MCD64A1_POISSON_PRIMARY", "VIIRS_STP_PRIMARY"}
    assert all(item.scenario is None and item.required_result_state == "NONE" for item in registry.exports if item.group != "rq4")


def test_semantic_palettes_are_explicit_config_authority() -> None:
    registry = load_presentation_export_registry(load_figure_contract(CONFIG / "figure_contract.yml"))
    assert dict(registry.semantic_styles["acz_categories"]) == {
        "CZ": "#1f77b4", "FZ": "#ff7f0e", "GS": "#2ca02c", "SS": "#d62728", "TZ": "#9467bd"
    }
    assert dict(registry.semantic_styles["four_state_categories"]) == {
        "both_zero": "#1f77b4",
        "mcd64a1_positive_viirs_zero": "#ff7f0e",
        "viirs_positive_mcd64a1_zero": "#2ca02c",
        "both_positive": "#d62728",
    }


def test_configuration_mutations_reach_typed_accessors(tmp_path: Path) -> None:
    config = _copy_config(tmp_path)
    def mutate(raw):
        _export(raw, "rq2_coastal_trend")["selector"]["equals"] = "FZ"
        raw["presentation_export"]["semantic_styles"]["four_state_categories"]["both_zero"] = "#123456"
    _mutate_figure(config, mutate)
    figure = load_figure_contract(config / "figure_contract.yml")
    assert get_presentation_export_spec("rq2_coastal_trend", figure).selector["equals"] == "FZ"
    assert load_presentation_export_registry(figure).semantic_styles["four_state_categories"]["both_zero"] == "#123456"


def test_backward_compatible_figure_contract_without_presentation_registry(tmp_path: Path) -> None:
    config = _copy_config(tmp_path)
    _mutate_figure(config, lambda raw: raw.pop("presentation_export"))
    figure = load_figure_contract(config / "figure_contract.yml")
    assert figure.presentation_export is None
    assert tuple(item.figure_id for item in figure.figures) == ("F2", "F3", "F4", "F5", "F6", "S1")
    with pytest.raises(KeyError, match="No presentation-export registry"):
        load_presentation_export_registry(figure)


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("group", "unknown"), "Unknown presentation export group"),
        (lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("renderer_identity", "unknown_renderer"), "Unknown presentation renderer identity"),
        (lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("source_identity", "missing_source"), "Unknown presentation source identity"),
        (lambda raw: _export(raw, "rq1_acz_long_run_rate").__setitem__("geometry_dependency", "bad_geometry"), "Unknown geometry dependency"),
        (lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("size_role", "missing_size"), "size_role"),
        (lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("formats", ["svg"]), "formats"),
        (lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("required_result_state", "EXTERNAL_RESULTS_REQUIRED"), "Unsupported presentation result-state"),
        (lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("selector", {"column": "parent_code"}), "selector"),
        (lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("output_filename", "other.{format}"), "output_filename"),
        (lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("raster_dpi", 299), "raster_dpi"),
    ],
)
def test_malformed_export_contract_fails_closed(tmp_path: Path, mutation, match: str) -> None:
    config = _copy_config(tmp_path)
    _mutate_figure(config, mutation)
    with pytest.raises(ConfigurationError, match=match):
        load_figure_contract(config / "figure_contract.yml")


def test_duplicate_export_id_fails_closed(tmp_path: Path) -> None:
    config = _copy_config(tmp_path)
    def mutate(raw):
        raw["presentation_export"]["exports"][1]["export_id"] = raw["presentation_export"]["exports"][0]["export_id"]
    _mutate_figure(config, mutate)
    with pytest.raises(ConfigurationError, match="Duplicate presentation export ID"):
        load_figure_contract(config / "figure_contract.yml")


def test_source_path_must_match_source_registry(tmp_path: Path) -> None:
    config = _copy_config(tmp_path)
    _mutate_figure(config, lambda raw: _export(raw, "rq2_coastal_trend").__setitem__("source_path_pattern", "other.csv"))
    with pytest.raises(ConfigurationError, match="conflicts with source registry"):
        load_figure_contract(config / "figure_contract.yml")


def test_unknown_package_renderer_identity_fails_bundle_semantics(tmp_path: Path) -> None:
    config = _copy_config(tmp_path)
    def mutate(raw):
        raw["presentation_export"]["renderer_identities"].append("future_unknown_renderer")
    _mutate_figure(config, mutate)
    with pytest.raises(ConfigurationError, match="Unregistered presentation renderer identities"):
        load_configuration_bundle(config)


def test_unknown_secondary_scenario_fails_bundle_semantics(tmp_path: Path) -> None:
    config = _copy_config(tmp_path)
    _mutate_figure(config, lambda raw: _export(raw, "rq4_viirs_clusters").__setitem__("scenario", "UNKNOWN_SCENARIO"))
    with pytest.raises(ConfigurationError, match="unknown secondary scenario"):
        load_configuration_bundle(config)


def test_unknown_cross_contract_geometry_fails_bundle_semantics(tmp_path: Path) -> None:
    config = _copy_config(tmp_path)
    def mutate(raw):
        raw["presentation_export"]["geometry_dependencies"]["district+acz"]["geometries"].append("unknown_geometry")
    _mutate_figure(config, mutate)
    with pytest.raises(ConfigurationError, match="unknown geometries"):
        load_configuration_bundle(config)


def test_export_lookup_fails_closed_for_unknown_id_and_group() -> None:
    figure = load_figure_contract(CONFIG / "figure_contract.yml")
    with pytest.raises(KeyError, match="No configured presentation export"):
        get_presentation_export_spec("not_an_export", figure)
    with pytest.raises(KeyError, match="Unknown presentation export group"):
        get_presentation_exports_for_group("not_a_group", figure)
