from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.outputs import OutputRecord
from rp1_analysis_v1.presentation import get_figure_spec, load_figure_specs
from rp1_analysis_v1.registers import figure_registry, table_registry, validate_publication_specs

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"


def test_publication_registries_are_projected_only_from_injected_contracts() -> None:
    bundle = load_configuration_bundle(CONFIG)
    validate_publication_specs(bundle.output, bundle.figure)
    assert [x.output_id for x in bundle.output.tables] == [
        "T1", "T2", "T3", "S1", "S2", "S3", "S4", "S5", "S6"
    ]
    assert [x.figure_id for x in load_figure_specs(bundle.figure)] == ["F2", "F3", "F4", "F5", "F6", "S1"]


def test_table_registry_requires_explicit_contract_and_preserves_deferred_state() -> None:
    bundle = load_configuration_bundle(CONFIG)
    records = {
        spec.output_id: OutputRecord(path=f"x/{spec.output_id}.csv", sha256="a" * 64, size_bytes=1)
        for spec in bundle.output.tables
        if spec.output_id != "T3"
    }
    frame = table_registry(
        records,
        output_contract=bundle.output,
        deferred={"T3": "EXTERNAL_RESULTS_REQUIRED"},
    )
    assert set(frame["table_id"]) == {x.output_id for x in bundle.output.tables}
    t3 = frame.loc[frame["table_id"].eq("T3")].iloc[0]
    assert t3["availability"] == "EXTERNAL_RESULTS_REQUIRED"
    assert t3["path"] == ""


def test_figure_registry_requires_explicit_contract_and_configured_ids() -> None:
    bundle = load_configuration_bundle(CONFIG)
    manifests = {
        spec.figure_id: {
            "availability": "AVAILABLE",
            "figure_data": {"path": f"fig/{spec.figure_data_identity}", "sha256": "b" * 64},
            "images": [
                {"format": "png", "path": f"fig/{spec.figure_id}.png"},
                {"format": "pdf", "path": f"fig/{spec.figure_id}.pdf"},
            ],
            "manifest_path": f"fig/{spec.figure_id}.json",
        }
        for spec in load_figure_specs(bundle.figure)
    }
    frame = figure_registry(manifests, figure_contract=bundle.figure)
    assert list(frame["figure_id"]) == ["F2", "F3", "F4", "F5", "F6", "S1"]
    assert frame["figure_data_path"].str.endswith(".csv").all()


def test_table2_row_selection_is_role_driven_not_a_duplicate_predictor_list() -> None:
    bundle = load_configuration_bundle(CONFIG)
    t2 = next(x for x in bundle.output.tables if x.output_id == "T2")
    assert t2.builder_options["row_selector"] == "all_configured_continuous_predictors"
    assert t2.builder_options["factor_coefficients_destination"] == "S5"
    text = (CONFIG / "output_contract.yml").read_text(encoding="utf-8")
    for term in (
        "log2_viirs_det_primary",
        "log2_viirs_frp_mean_mw",
        "log2_modis_burnable_km2_union_ba2012",
    ):
        assert term not in text


def test_figure_lookup_is_contract_injected_and_external_f1_is_not_generated() -> None:
    bundle = load_configuration_bundle(CONFIG)
    f2 = get_figure_spec("F2", bundle.figure)
    assert f2.panel_count == 2
    assert tuple(f2.data_builder_options["panel_order"]) == (
        "direct_acz_long_run_rate", "district_long_run_rate"
    )
    with pytest.raises(KeyError):
        get_figure_spec("F1", bundle.figure)
    with pytest.raises(KeyError):
        get_figure_spec("F999", bundle.figure)
