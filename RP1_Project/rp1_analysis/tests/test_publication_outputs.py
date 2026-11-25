from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import shutil
from types import SimpleNamespace

import pandas as pd
import pytest
from rp1_analysis_v1 import publication, publication_sources
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.outputs import OutputRecord
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.presentation import get_figure_spec, load_figure_specs
from rp1_analysis_v1.registers import (
    RegistryError,
    figure_registry,
    result_registry,
    table_registry,
    validate_publication_specs,
)

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"


@pytest.fixture
def pending_publication_sources(tmp_path, monkeypatch):
    bundle = load_configuration_bundle(CONFIG)
    paths = ProjectPaths(tmp_path)
    (tmp_path / "config").mkdir()
    shutil.copyfile(CONFIG / "output_contract.yml", paths.output_contract)
    root = tmp_path / publication_sources.PUBLICATION_AUTHORITY_DIR
    root.mkdir(parents=True)
    columns_by_source = {}
    panels_by_source = {}
    for spec in bundle.output.tables:
        if not any(spec.builder_options.get(key) for key in ("genuine_external_results_required", "requires_restricted_scan")):
            columns_by_source.setdefault(spec.source_attribute, {}).update(dict.fromkeys(spec.required_columns, 1))
    for spec in load_figure_specs(bundle.figure):
        if not spec.data_builder_options.get("genuine_external_results_required"):
            columns_by_source.setdefault(spec.source_attribute, {}).update(dict.fromkeys(spec.required_columns, 1))
            order = spec.data_builder_options.get("panel_order")
            if order:
                panels_by_source.setdefault(spec.source_attribute, {}).update(dict.fromkeys(order))
    for rows in columns_by_source.values():
        if "support_status" in rows:
            rows["support_status"] = "valid_nonzero"
    columns_by_source["supplement_s3_spatial"]["record_type"] = "global_moran_national"
    columns_by_source["supplement_s4_rq2"]["parent_code"] = "CZ"
    columns_by_source["table2_rq3_model"].update(predictor_role="focal", n=1)

    manifest_path = root / publication_sources.MANIFEST_NAME
    manifest = {"configuration_sha256": bundle.configuration_sha256, "sources": {}}

    def write_source(name, frame):
        path = root / f"{name}.csv"
        frame.to_csv(path, index=False)
        manifest["sources"][name] = {
            "path": path.relative_to(tmp_path).as_posix(),
            "sha256": sha256(path.read_bytes()).hexdigest(),
            "columns": list(frame.columns), "rows": len(frame),
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    for source, row in columns_by_source.items():
        panels = panels_by_source.get(source, ())
        rows = [{**row, "panel": panel} for panel in panels] if panels else [row]
        write_source(source, pd.DataFrame(rows))
    monkeypatch.setattr(publication_sources, "load_configuration_bundle", lambda _: bundle)
    # Test publication dependencies and provenance with synthetic sources and images.
    monkeypatch.setattr(publication, "_render", lambda *a, **k: SimpleNamespace(
        png=b"fixture PNG", pdf=b"fixture PDF", dpi=300, width_in=8, height_in=6,
    ))

    def build():
        return publication.build_publication_run(
            paths=paths, run_id="pending_fixture", bundle=bundle, authorities=object(),
            data_contract=object(), secondary_run=SimpleNamespace(
                execution_state=publication.EXTERNAL_RESULTS_REQUIRED,
            ),
        )

    return SimpleNamespace(
        build=build, manifest=manifest, manifest_path=manifest_path, write_source=write_source, bundle=bundle,
    )


def test_pending_publication_renders_primary_estate_and_defers_only_scan_outputs(pending_publication_sources):
    run = pending_publication_sources.build()
    assert run.deferred_outputs == {
        "T3": publication.EXTERNAL_RESULTS_REQUIRED,
        "S6": publication.EXTERNAL_RESULTS_REQUIRED,
        "F6": publication.EXTERNAL_RESULTS_REQUIRED,
        **{f"S{i}": publication.RESTRICTED_SCAN_RESULTS_REQUIRED for i in range(21, 25)},
    }
    assert run.table_registry.loc[run.table_registry["availability"].eq("AVAILABLE"), "table_id"].nunique() == 26
    assert run.figure_registry.loc[run.figure_registry["availability"].eq("AVAILABLE"), "figure_id"].nunique() == 8


@pytest.mark.parametrize("name", [
    "table1_acz_summary", "table2_rq3_model", "supplement_s2_district_rq1",
    "supplement_s3_spatial", "supplement_s4_rq2", "supplement_s5_rq3",
    "long_run_spatial_rate_presentation_source", "seasonality_spatial_organisation_presentation_source",
    "annual_trend_source", "cross_product_observability_presentation_source",
    "district_seasonal_diagnostics_source",
])
def test_pending_publication_rejects_missing_mandatory_sources(pending_publication_sources, name):
    pending = pending_publication_sources
    pending.manifest["sources"].pop(name)
    pending.manifest_path.write_text(json.dumps(pending.manifest), encoding="utf-8")
    with pytest.raises(publication_sources.PublicationSourceError, match=f"Required primary publication sources missing: {name}"):
        pending.build()
    assert not (pending.manifest_path.parents[3] / "out/runs/pending_fixture").exists()


@pytest.mark.parametrize(("name", "error"), [
    ("table1_acz_summary", "is empty for T1"),
    ("long_run_spatial_rate_presentation_source", "F2 source is missing configured panels"),
])
def test_pending_publication_rejects_blank_mandatory_sources(pending_publication_sources, name, error):
    pending = pending_publication_sources
    pending.write_source(name, pd.DataFrame(columns=pending.manifest["sources"][name]["columns"]))
    with pytest.raises(publication.PublicationError, match=error):
        pending.build()


def test_prepared_restricted_scan_without_results_is_pending(tmp_path):
    from rp1_analysis_v1.scan_sensitivity import DESIGN_NAME, RESULTS_PREFIX

    restricted = tmp_path / "support_sensitivity"
    (restricted / RESULTS_PREFIX).parent.mkdir(parents=True)
    (restricted / DESIGN_NAME).write_text("{}", encoding="utf-8")
    assert publication.load_restricted_scan_sources(tmp_path) == {}


@pytest.mark.parametrize("result_kind", ["native", "derived", "summary"])
def test_restricted_scan_partial_results_fail_instead_of_deferring(tmp_path, result_kind):
    from rp1_analysis_v1.scan_sensitivity import RESULTS_PREFIX, RESULT_NAMES, scan_sensitivity_summary_path

    restricted = tmp_path / "support_sensitivity"
    summary = scan_sensitivity_summary_path(restricted)
    paths = {
        "native": (restricted / RESULTS_PREFIX).with_suffix(".col.txt"),
        "derived": summary.parent / RESULT_NAMES["clusters"],
        "summary": summary,
    }
    path = paths[result_kind]
    path.parent.mkdir(parents=True)
    path.write_text("fixture", encoding="utf-8")
    with pytest.raises(publication.PublicationError, match="Restricted scan.*(incomplete|complete derived comparison)"):
        publication.load_restricted_scan_sources(tmp_path)


def test_publisher_rejects_partial_restricted_source_context_before_writing():
    bundle = load_configuration_bundle(CONFIG)
    with pytest.raises(publication.PublicationError, match="Restricted scan publication sources incomplete"):
        publication._write_configured_tables(
            None, bundle, {"restricted_scan_summary": pd.DataFrame()},
            external_state=publication.RESULTS_VALIDATED,
        )


def test_publication_registries_are_projected_only_from_injected_contracts() -> None:
    bundle = load_configuration_bundle(CONFIG)
    validate_publication_specs(bundle.output, bundle.figure)
    assert [x.output_id for x in bundle.output.tables if x.role == "manuscript"] == [
        "T1",
        "T2",
        "T3",
    ]
    assert [x.output_id for x in bundle.output.tables if x.role == "supplementary"] == [
        f"S{i}" for i in range(1, 26)
    ]
    assert [x.output_id for x in bundle.output.tables if x.role == "internal_authority"] == [
        "QA_C3_EVIDENCE",
        "QA_C3_EXCLUSIONS",
        "QA_C3_RECONCILIATION",
        "QA_C3_DIAGNOSTICS",
    ]
    assert [x.figure_id for x in load_figure_specs(bundle.figure)] == [
        "F2",
        "F3",
        "F4",
        "F5",
        "F6",
        "FS1",
        "FS2",
        "FS3",
        "FS4",
    ]


def test_table_registry_requires_explicit_contract_and_preserves_deferred_state() -> None:
    bundle = load_configuration_bundle(CONFIG)
    deferred = {
        "T3": "EXTERNAL_RESULTS_REQUIRED",
        "S6": "EXTERNAL_RESULTS_REQUIRED",
        **{f"S{i}": "RESTRICTED_SCAN_RESULTS_REQUIRED" for i in range(21, 24)},
    }
    records = {
        spec.output_id: OutputRecord(path=f"x/{spec.output_id}.csv", sha256="a" * 64, size_bytes=1)
        for spec in bundle.output.tables
        if spec.output_id not in deferred
    }
    frame = table_registry(
        records,
        output_contract=bundle.output,
        deferred=deferred,
    )
    assert set(frame["table_id"]) == {x.output_id for x in bundle.output.tables}
    pending = frame.set_index("table_id").loc[list(deferred)]
    assert pending["availability"].to_dict() == deferred
    assert pending["path"].eq("").all()
    with pytest.raises(RegistryError, match="Missing registered table output: T3"):
        table_registry(
            {**records, "T999": next(iter(records.values()))}, output_contract=bundle.output
        )


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
    assert list(frame["figure_id"]) == ["F2", "F3", "F4", "F5", "F6", "FS1", "FS2", "FS3", "FS4"]
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


def test_rq2_result_registry_points_to_annual_trend_authority() -> None:
    bundle = load_configuration_bundle(CONFIG)
    spatial = pd.DataFrame([{"morans_i": 0.5, "permutation_p": 0.02, "n_effective": 250}])
    temporal = pd.DataFrame(
        [{"parent_code": "CZ", "sen_slope": -0.1, "raw_p": 0.2, "bh_q": 0.4, "n": 24}]
    )
    registry = result_registry(
        spatial, temporal, output_contract=bundle.output, figure_contract=bundle.figure
    )
    trend = registry.loc[registry["rq"].eq("RQ2")].iloc[0]
    assert trend["source_table"] == "S4.csv"
    assert trend["source_figure"] == "F4"
    assert (trend["estimate"], trend["p_value"], trend["q_value"], trend["sample_n"]) == (
        -0.1,
        0.2,
        0.4,
        24,
    )


def test_figure_lookup_is_contract_injected_and_external_f1_is_not_generated() -> None:
    bundle = load_configuration_bundle(CONFIG)
    f2 = get_figure_spec("F2", bundle.figure)
    assert f2.panel_count == 2
    assert tuple(f2.data_builder_options["panel_order"]) == (
        "direct_acz_long_run_rate",
        "district_long_run_rate",
    )
    with pytest.raises(KeyError):
        get_figure_spec("F1", bundle.figure)
    with pytest.raises(KeyError):
        get_figure_spec("S2", bundle.figure)
    with pytest.raises(KeyError):
        get_figure_spec("F999", bundle.figure)
