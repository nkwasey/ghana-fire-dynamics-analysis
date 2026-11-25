from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
from generated_run_reference import publication_source_root, publication_sources, selected_run_base
from rp1_analysis_v1.config import load_configuration_bundle
from scientific_input_reference import (
    design_terms_reference,
    long_run_input_reference,
    panel_input_reference,
)

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"


def _bundle():
    return load_configuration_bundle(CONFIG)


def _sources():
    return publication_sources(ROOT)


def test_exact_publication_identity_and_counts() -> None:
    b = _bundle()
    main_tables = [x for x in b.output.tables if x.role == "manuscript"]
    supp_tables = [x for x in b.output.tables if x.role == "supplementary"]
    main_fig = [x for x in b.figure.figures if x.role == "manuscript"]
    supp_fig = [x for x in b.figure.figures if x.role == "supplementary"]
    assert [x.output_id for x in main_tables] == ["T1", "T2", "T3"]
    assert [x.output_id for x in supp_tables] == [f"S{i}" for i in range(1, 26)]
    assert [x.figure_id for x in main_fig] == ["F2", "F3", "F4", "F5", "F6"]
    assert [x.figure_id for x in supp_fig] == ["FS1", "FS2", "FS3", "FS4"]
    assert "F1" not in {x.figure_id for x in b.figure.figures}


def test_table1_has_compact_numeric_acz_summary_columns() -> None:
    numeric = [
        "direct_long_run_rate",
        "district_rate_median",
        "district_rate_iqr",
        "district_rate_gini",
        "circular_mean_month",
        "mean_resultant_length",
    ]
    expected_columns = ["parent_code", "parent_name", *numeric]
    table = next(x for x in _bundle().output.tables if x.output_id == "T1")
    assert list(table.required_columns) == expected_columns
    source = _sources()[table.source_attribute]
    run = ROOT / "out/runs" / f"{selected_run_base(ROOT)}_pub"
    f = pd.read_csv(run / "90_integrated/tables/T1.csv")
    assert list(f.columns) == expected_columns
    assert len(f) == 5 and f["parent_code"].nunique() == 5
    assert all(pd.api.types.is_numeric_dtype(f[column]) for column in numeric)
    pd.testing.assert_frame_equal(
        f, source.loc[:, expected_columns], check_exact=False, rtol=1e-14, atol=0,
    )


def test_table2_has_exact_three_continuous_model_rows() -> None:
    f = _sources()["table2_rq3_model"]
    assert len(f) == 3
    assert f["term"].tolist() == [
        "log2_viirs_det_primary",
        "log2_viirs_frp_mean_mw",
        "log2_modis_burnable_km2_union_ba2012",
    ]
    assert f["predictor_role"].tolist() == ["focal", "focal", "adjustment"]


def test_f2_semantic_projection_has_only_two_rate_panels() -> None:
    b = _bundle()
    spec = next(x for x in b.figure.figures if x.figure_id == "F2")
    assert spec.source_attribute == "long_run_spatial_rate_presentation_source"
    f = _sources()[spec.source_attribute]
    assert list(dict.fromkeys(f["panel"].astype(str))) == [
        "direct_acz_long_run_rate",
        "district_long_run_rate",
    ]
    assert (
        len(f)
        == panel_input_reference().unit_id.nunique()
        + panel_input_reference("acz_monthly").unit_id.nunique()
    )


def test_f3_and_fs1_are_disjoint_projections_of_the_same_source() -> None:
    authority = _sources()["seasonality_spatial_organisation_presentation_source"]
    output_root = ROOT / "out/runs" / f"{selected_run_base(ROOT)}_pub" / "01_rq1_spatial_scale/figure_data"
    for figure, panels in (
        ("F3", ("district_departure", "local_moran")),
        ("FS1", ("acz_seasonality",)),
    ):
        rendered = pd.read_csv(output_root / f"FD_{figure}.csv")
        assert tuple(rendered["panel"].drop_duplicates()) == panels
        expected = authority.loc[authority["panel"].isin(panels), rendered.columns].reset_index(drop=True)
        pd.testing.assert_frame_equal(rendered, expected, check_exact=False, rtol=1e-14, atol=0)
    monthly = authority.loc[authority["panel"].eq("acz_seasonality")]
    assert len(monthly) == 60
    assert monthly.groupby("parent_code", observed=True)["month"].nunique().eq(12).all()


def test_f4_uses_exact_rq2_publication_fields_and_frozen_order() -> None:
    b = _bundle()
    spec = next(x for x in b.figure.figures if x.figure_id == "F4")
    assert spec.source_attribute == "annual_trend_source"
    assert tuple(spec.renderer_options["panel_order"]) == (
        "COASTAL ZONE",
        "FOREST ZONE",
        "GUINEA SAVANNAH",
        "SUDAN SAVANNAH",
        "TRANSITION ZONE",
    )
    f = _sources()[spec.source_attribute]
    assert (
        len(f) == 120
        and f["parent_code"].nunique() == 5
        and f.groupby("parent_code", observed=True)["year"].nunique().eq(24).all()
    )


def test_f5_focal_panel_has_exactly_two_effects() -> None:
    f = _sources()["cross_product_observability_presentation_source"]
    focal = f.loc[f["panel"].eq("focal_adjusted_associations")]
    assert len(focal) == 2
    assert focal["term"].tolist() == [
        "VIIRS detection count (per doubling)",
        "Mean FRP (per doubling)",
    ]
    assert not focal["term"].str.contains("burnable", case=False, na=False).any()


def test_supplement_s3_has_one_global_moran_and_local_rows() -> None:
    f = _sources()["supplement_s3_spatial"]
    assert (f["record_type"].astype(str) == "global_moran_national").sum() == 1
    local = f.loc[f["record_type"].astype(str).eq("local_moran")]
    assert (
        len(local) == long_run_input_reference().unit_id.nunique()
        and local["unit_id"].nunique() == long_run_input_reference().unit_id.nunique()
    )


def test_supplement_s4_has_configured_years_and_acz_support() -> None:
    f = _sources()["supplement_s4_rq2"]
    assert (
        len(f) == 120
        and f["parent_code"].nunique() == 5
        and f.groupby("parent_code", observed=True)["year"].nunique().eq(24).all()
    )


def test_supplement_s5_contains_full_model_and_exact_probability_outputs() -> None:
    f = _sources()["supplement_s5_rq3"]
    assert (f["record_type"].eq("coefficient")).sum() == len(design_terms_reference())
    std = f.loc[f["record_type"].eq("standardised_probability")]
    assert len(std) == 4 and std["predictor_id"].nunique() == 2


def test_publication_runtime_does_not_recompute_rq_statistics() -> None:
    source = (ROOT / "src/rp1_analysis_v1/publication.py").read_text()
    assert (
        "build_rq1_tables" not in source
        and "build_rq2_tables" not in source
        and "build_rq3_tables" not in source
    )
    assert "load_publication_authorities" in source


def test_materialised_source_manifest_is_hash_closed_and_semantic() -> None:
    mp = publication_source_root(ROOT) / "SOURCE_MANIFEST.json"
    m = json.loads(mp.read_text())
    assert m["satscan_dependent_sources_materialised"] is False
    bundle = _bundle()
    expected_tables = {
        spec.source_attribute
        for spec in bundle.output.tables
        if not any(
            spec.builder_options.get(gate)
            for gate in ("genuine_external_results_required", "requires_restricted_scan")
        )
    }
    expected_figures = {
        spec.source_attribute
        for spec in bundle.figure.figures
        if not spec.data_builder_options.get("genuine_external_results_required")
    }
    assert set(m["sources"]) == expected_tables | expected_figures
    for name, item in m["sources"].items():
        path = ROOT / item["path"]
        assert path.is_file(), name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
        f = pd.read_csv(path)
        assert len(f) == item["rows"] and list(f.columns) == item["columns"]


def test_primary_sources_exclude_run_local_external_scan_outputs() -> None:
    assert {
        "table3_satscan_clusters",
        "supplement_s6_satscan",
        "cluster_membership_source",
        "cluster_recurrence_source",
        "restricted_scan_summary",
        "restricted_scan_clusters",
        "restricted_scan_recurrence",
    }.isdisjoint(_sources())


def test_reviewer_tables_reconcile_to_their_district_source_rows() -> None:
    sources = _sources()
    support = sources["district_burnable_support"].set_index("unit_id", verify_integrity=True)
    baseline = support.loc[support["baseline_eligible"]]
    variability = sources["district_rate_variability"]
    assert set(variability["unit_id"]) == set(baseline.index)
    assert not variability.duplicated(["unit_id", "block_length_years"]).any()
    assert variability.loc[variability["is_primary_block"], "unit_id"].is_unique
    assert (variability["lower_rate"] <= variability["upper_rate"]).all()
    by_unit = sources["district_threshold_by_unit"]
    by_zone = sources["district_threshold_by_acz"]
    for scenario in sources["district_threshold_national"].itertuples(index=False):
        rows = by_unit.loc[by_unit["scenario_id"].eq(scenario.scenario_id)]
        assert set(rows["unit_id"]) == set(support.index)
        retained = rows.loc[rows["included"]]
        expected = baseline.loc[
            baseline["fixed_burnable_union_km2"].gt(scenario.minimum_fixed_union_km2)
        ]
        assert set(retained["unit_id"]) == set(expected.index)
        assert len(retained) == scenario.retained_districts
        assert int(retained["local_raw_p"].notna().sum()) == scenario.local_bh_family_size
        assert by_zone.loc[
            by_zone["scenario_id"].eq(scenario.scenario_id), "district_count"
        ].sum() == len(retained)


def test_restricted_scan_publication_family_is_complete_or_deferred() -> None:
    publication_source_root(ROOT)
    base = selected_run_base(ROOT)
    pub = ROOT / "out" / "runs" / f"{base}_pub"
    registry = pd.read_csv(pub / "90_integrated" / "T_TABLE_REGISTRY.csv")
    typed = registry.set_index("table_id", verify_integrity=True)
    restricted = typed.loc[["S21", "S22", "S23", "S24"]]
    states = set(restricted["availability"])
    if states == {"RESTRICTED_SCAN_RESULTS_REQUIRED"}:
        assert restricted["path"].fillna("").eq("").all()
        assert restricted["sha256"].fillna("").eq("").all()
    else:
        assert states == {"AVAILABLE"}
        specs = {spec.output_id: spec for spec in _bundle().output.tables}
        for table_id, row in restricted.iterrows():
            path = pub / row["path"]
            assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
            published = pd.read_csv(path)
            assert list(published.columns) == list(specs[table_id].required_columns)
