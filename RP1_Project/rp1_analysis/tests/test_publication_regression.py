from __future__ import annotations

import ast
from pathlib import Path

import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.design import assert_execution_ready
from rp1_analysis_v1.presentation import load_figure_specs
from rp1_analysis_v1.publication import build_publication_run
from rp1_analysis_v1.registers import validate_publication_specs

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"


def test_publication_architecture_validates_without_import_time_snapshot() -> None:
    bundle = load_configuration_bundle(CONFIG)
    validate_publication_specs(bundle.output, bundle.figure)
    assert len(bundle.output.tables) == 9
    assert len(load_figure_specs(bundle.figure)) == 6


def test_publication_architecture_accepts_qualified_rq2_method() -> None:
    bundle = load_configuration_bundle(CONFIG)
    assert_execution_ready(bundle.analysis.to_dict(), bundle.methods, "rq2")
    rq2_outputs = [item for item in bundle.output.tables if item.rq in {"RQ2", "INTEGRATED_RQ1_RQ2"}]
    assert {item.output_id for item in rq2_outputs} == {"T1", "S4"}
    s4 = next(item for item in rq2_outputs if item.output_id == "S4")
    assert "realised_bandwidth" in s4.required_columns
    assert "raw_p" in s4.required_columns
    assert "bh_q" in s4.required_columns
    assert {"sen_slope", "u_n", "long_run_variance", "t_n", "raw_p", "bh_q"} <= set(s4.required_columns)


def test_publication_python_contains_no_study_output_id_snapshot_constants() -> None:
    configured = load_configuration_bundle(CONFIG)
    ids = {x.output_id for x in configured.output.tables} | {x.figure_id for x in configured.figure.figures}
    for rel in (
        "src/rp1_analysis_v1/registers.py",
        "src/rp1_analysis_v1/presentation.py",
        "src/rp1_analysis_v1/publication.py",
    ):
        path = SUBPROJECT / rel
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        assert ids.isdisjoint(literals), (rel, sorted(ids.intersection(literals)))


def test_current_figure_contract_keeps_notes_outside_figures() -> None:
    bundle = load_configuration_bundle(CONFIG)
    assert bundle.figure.text_policy["embedded_notes"] is False
    assert bundle.figure.text_policy["title_inside_figure"] is False
    assert bundle.figure.panel_layout["panel_titles"] is False
    assert bundle.figure.panel_layout["panel_descriptions"] is False
