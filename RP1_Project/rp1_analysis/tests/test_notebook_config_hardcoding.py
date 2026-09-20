from __future__ import annotations

import ast
from pathlib import Path
from typing import Iterable

import nbformat

from rp1_analysis_v1 import load_configuration_bundle

SUBPROJECT = Path(__file__).resolve().parents[1]
NOTEBOOK = SUBPROJECT / "RP1_Analysis_v1.ipynb"
BUNDLE = load_configuration_bundle(SUBPROJECT / "config")


def _code_cells() -> list[str]:
    nb = nbformat.read(NOTEBOOK, as_version=4)
    return ["".join(cell.get("source", "")) for cell in nb.cells if cell.cell_type == "code"]


def _trees() -> list[ast.AST]:
    return [ast.parse(source) for source in _code_cells()]


def _string_constants() -> set[str]:
    values: set[str] = set()
    for tree in _trees():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                values.add(node.value)
    return values


def _flatten_strings(value) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _flatten_strings(item)
    elif isinstance(value, (tuple, list)):
        for item in value:
            yield from _flatten_strings(item)


def test_dataset_field_identities_are_not_embedded_as_code_literals() -> None:
    data_fields = set(BUNDLE.data_schema.field_names)
    governed_role_values = set(_flatten_strings(BUNDLE.analysis.field_roles)) & data_fields
    embedded = _string_constants()
    assert not (governed_role_values & embedded), sorted(governed_role_values & embedded)


def test_publication_output_ids_are_not_embedded_as_code_literals() -> None:
    configured_ids = {item.output_id for item in BUNDLE.output.tables}
    configured_ids |= {item.output_id for item in BUNDLE.output.secondary_outputs}
    configured_ids |= {item.figure_id for item in BUNDLE.figure.figures}
    embedded = _string_constants()
    assert not (configured_ids & embedded), sorted(configured_ids & embedded)


def test_satscan_model_ids_are_not_embedded_as_code_literals() -> None:
    configured_ids = {str(item["scenario_id"]) for item in BUNDLE.analysis.secondary_analysis["scenarios"]}
    embedded = _string_constants()
    assert not (configured_ids & embedded), sorted(configured_ids & embedded)


def test_no_notebook_owned_assignment_of_governed_numeric_parameters() -> None:
    scientific_name_fragments = (
        "permutation", "bandwidth", "variance_floor", "random_seed", "alpha", "bh_family",
        "max_spatial", "max_temporal", "monte_carlo", "quantile",
    )
    offenders: list[tuple[str, object]] = []
    for tree in _trees():
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if not isinstance(value, ast.Constant) or not isinstance(value.value, (int, float)):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and any(part in target.id.lower() for part in scientific_name_fragments):
                    offenders.append((target.id, value.value))
    assert not offenders


def test_no_scientific_call_keyword_is_supplied_as_literal() -> None:
    governed_keywords = {
        "permutations", "random_seed", "alpha", "variance_floor", "monte_carlo_replicates",
        "max_spatial_percent", "max_temporal_months", "working_correlation", "covariance",
        "reference_distribution", "focal_predictor_quantiles",
    }
    offenders: list[tuple[str, object]] = []
    for tree in _trees():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg in governed_keywords and isinstance(keyword.value, ast.Constant):
                    offenders.append((keyword.arg, keyword.value.value))
    assert not offenders


def test_notebook_calls_high_level_builders_with_analysis_contract() -> None:
    code = "\n".join(_code_cells()).replace(" ", "")
    assert "build_rq1_tables(authorities,data_contract,contracts.analysis)" in code
    assert "build_rq2_tables(" in code and "contracts.methods" in code and "configuration_sha256=contracts.configuration_sha256" in code
    assert "build_rq3_tables(" in code
    assert "contracts.analysis" in code and "contracts.methods" in code
    assert "configuration_sha256=contracts.configuration_sha256" in code
    assert "bundle=contracts" in code


def test_parameter_audits_use_typed_config_projections() -> None:
    code = "\n".join(_code_cells())
    for projection in (
        "rq1_spatial_parameters(contracts.analysis)",
        "rq2_trend_parameters(contracts.analysis)",
        "rq3_model_parameters(contracts.analysis)",
        "satscan_parameters(contracts.analysis)",
        "configured_predictor_metadata(contracts.analysis)",
    ):
        assert projection in code
    for stale in (
        'rq2_config["resampling"]',
        'rq1_config["spatial_autocorrelation"]',
        'analysis_config["spatial_autocorrelation"]',
        'model_family',
        'mean_model',
        'repeated_measure_id_field',
    ):
        assert stale not in code


def test_notebook_executes_configured_rq2_route() -> None:
    code = "\n".join(_code_cells())
    markdown = "\n".join(
        "".join(c.get("source", ""))
        for c in nbformat.read(NOTEBOOK, as_version=4).cells
        if c.cell_type == "markdown"
    ).lower()
    assert "PendingDesignError" not in code
    assert 'rq2_gate = "PASS"' in code
    assert 'final_run_gate = "PASS"' in code
    assert "studentized global mann–kendall" in markdown
    assert "romano–tirlea" in markdown
    assert "benjamini–hochberg" in markdown

