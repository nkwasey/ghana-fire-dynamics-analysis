from __future__ import annotations
from scientific_input_reference import long_run_input_reference, panel_input_reference
from generated_run_reference import selected_run_base, require_selected_run

import hashlib
import json
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from PIL import Image

import rp1_analysis_v1.presentation_export as pe
import rp1_analysis_v1.presentation_rq1 as rq1p
from rp1_analysis_v1.mapping import join_district_figure_data, prepare_geography
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.presentation import get_presentation_export_spec, load_presentation_export_registry
from rp1_analysis_v1.style import cm_to_inches, round_pixels_half_up

ROOT = Path(__file__).resolve().parents[1]
RUN_BASE = selected_run_base(ROOT)
RUN_CLOSE = ROOT / "out" / "runs" / f"{RUN_BASE}_close"
STUDY_RQ1_IDS = (
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
    "rq1_burnable_support_sensitivity",
)


def _run() -> pe.RunFamilyAuthority:
    require_selected_run(ROOT, RUN_BASE)
    return pe.resolve_run_family(RUN_CLOSE, paths=ProjectPaths(ROOT), validate=False)


def _source(export_id: str) -> pe.SourceAuthority:
    paths = ProjectPaths(ROOT)
    spec = get_presentation_export_spec(export_id, paths=paths)
    return pe.resolve_source(spec, _run(), paths=paths)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_study_and_rq1_catalogue_is_frozen_and_fully_implemented() -> None:
    paths = ProjectPaths(ROOT)
    registry = load_presentation_export_registry(paths=paths)
    configured = tuple(
        item.export_id for item in registry.exports if item.group in {"study", "rq1"}
    )
    assert configured == STUDY_RQ1_IDS
    implemented = set(pe.build_core_renderer_registry().identities)
    assert all(registry.export_by_id(export_id).renderer_identity in implemented for export_id in configured)


def test_rq1_acz_categories_and_rate_units_match_governed_contract() -> None:
    spec = get_presentation_export_spec("rq1_acz_long_run_rate", paths=ProjectPaths(ROOT))
    source = _source("rq1_acz_long_run_rate")
    assert source.frame is not None
    frame = source.frame
    assert len(frame) == 5
    assert tuple(spec.category_order["values"]) == ("CZ", "FZ", "GS", "SS", "TZ")
    assert set(frame["parent_code"].astype(str)) == {"CZ", "FZ", "GS", "SS", "TZ"}
    assert spec.units == "km\u00b2 burned per 100 km\u00b2 fixed BA-2001 burnable area per year"
    assert frame["support_status"].astype(str).isin(["valid_nonzero", "valid_zero"]).all()


def test_rq1_district_support_counts_and_valid_zero_semantics_are_preserved() -> None:
    frame = _source("rq1_district_long_run_rate").frame
    assert frame is not None
    assert len(frame) == panel_input_reference().unit_id.nunique()
    assert frame["unit_id"].nunique() == panel_input_reference().unit_id.nunique()
    assert int((~frame["support_status"].astype(str).eq("excluded")).sum()) == long_run_input_reference().unit_id.nunique()
    assert int(frame["support_status"].astype(str).eq("excluded").sum()) == panel_input_reference().unit_id.nunique() - long_run_input_reference().unit_id.nunique()
    valid_zero = frame["support_status"].astype(str).eq("valid_zero")
    assert valid_zero.equals(frame["value"].eq(0) & ~frame["support_status"].eq("excluded"))
    assert pd.to_numeric(frame.loc[valid_zero, "value"], errors="raise").eq(0.0).all()
    assert frame.loc[frame["support_status"].astype(str).eq("excluded"), "value"].isna().all()


def test_governed_geometry_join_preserves_exact_district_universe() -> None:
    require_selected_run(ROOT, RUN_BASE)
    districts = gpd.read_file(ROOT / "data" / "geo" / "districts_within_acz.shp")
    acz = gpd.read_file(ROOT / "data" / "geo" / "acz.shp")
    authority = prepare_geography(districts, acz)
    frame = _source("rq1_district_long_run_rate").frame
    assert frame is not None
    merged = join_district_figure_data(authority, frame)
    assert len(districts) == panel_input_reference().unit_id.nunique()
    assert len(acz) == 5
    assert len(merged) == panel_input_reference().unit_id.nunique()
    assert merged["dist_id"].astype(str).nunique() == panel_input_reference().unit_id.nunique()
    assert merged["support_status"].isna().sum() == 0


def test_seasonality_month_order_and_circular_labels_are_source_owned() -> None:
    source = _source("rq1_acz_seasonality")
    assert source.frame is not None
    frame = source.frame
    assert len(frame) == 60
    for code, group in frame.groupby("parent_code", observed=True):
        assert tuple(group.sort_values("month")["month"].astype(int)) == tuple(range(1, 13))
        assert group["circular_mean_month"].nunique(dropna=False) == 1
        assert group["mean_resultant_length"].nunique(dropna=False) == 1
        assert group["unit_name"].nunique() == 1
    spec = get_presentation_export_spec("rq1_acz_seasonality", paths=ProjectPaths(ROOT))
    assert tuple(spec.category_order["values"]) == ("CZ", "FZ", "GS", "SS", "TZ")
    assert any("\u03bc and R" in text for text in spec.annotation_policy)


def test_district_departure_sign_is_consumed_not_recomputed() -> None:
    frame = _source("rq1_district_departure").frame
    assert frame is not None
    retained = frame.loc[~frame["support_status"].astype(str).eq("excluded")]
    values = pd.to_numeric(retained["value"], errors="raise")
    assert len(retained) == long_run_input_reference().unit_id.nunique()
    assert values.notna().all()
    assert frame.loc[frame["support_status"].astype(str).eq("excluded"), "value"].isna().all()


def test_local_moran_classes_and_island_state_are_preserved_exactly() -> None:
    source = _source("rq1_local_moran")
    assert source.frame is not None
    frame = source.frame
    retained = frame.loc[~frame["support_status"].astype(str).eq("excluded")]
    spec = get_presentation_export_spec("rq1_local_moran", paths=ProjectPaths(ROOT))
    allowed = tuple(spec.category_order["values"])
    observed = set(retained["local_class"].dropna().astype(str))
    assert observed.issubset(set(allowed))
    reference = pd.read_csv(ROOT / "out/runs" / f"{RUN_BASE}_pub" / "01_rq1_spatial_scale/tables/S3.csv")
    reference = reference.loc[reference.record_type.eq("local_moran")]
    actual = retained.set_index("unit_id").local_class.astype(str).sort_index()
    expected = reference.set_index("unit_id").local_class.astype(str).sort_index()
    pd.testing.assert_series_equal(actual, expected, check_names=False)
    assert frame.loc[frame["support_status"].astype(str).eq("excluded"), "local_class"].isna().all()
    # Renderer source is categorical authority only; it carries no recalculated statistic.
    assert frame["value"].isna().all()


def test_seasonal_source_preserves_current_district_support_and_undefined_timing() -> None:
    frame = _source("rq1_district_seasonal_heatmap").frame
    assert frame is not None
    assert len(frame) == long_run_input_reference().unit_id.nunique() * 12
    assert frame["unit_id"].nunique() == long_run_input_reference().unit_id.nunique()
    assert tuple(sorted(frame["month"].astype(int).unique())) == tuple(range(1, 13))
    counts = frame.groupby("unit_id", observed=True)["month"].nunique()
    assert counts.eq(12).all()
    all_missing = frame.groupby("unit_id", observed=True)["monthly_share"].apply(lambda s: s.isna().all())
    reference = pd.read_csv(ROOT / "out/runs" / f"{RUN_BASE}_pub" / "01_rq1_spatial_scale/tables/S2.csv")
    expected_missing = reference.set_index("unit_id").circular_mean_month.isna().sort_index()
    pd.testing.assert_series_equal(all_missing.sort_index(), expected_missing, check_names=False)
    assert int(frame["monthly_share"].isna().sum()) == int(expected_missing.sum()) * 12
    work, summary = rq1p._normalise_s1(frame)
    assert len(work) == len(frame)
    assert len(summary) == long_run_input_reference().unit_id.nunique()
    undefined = summary["circular_mean_month"].isna()
    assert int(undefined.sum()) == int(expected_missing.sum())
    assert summary.loc[undefined, "mean_resultant_length"].isna().all()


@pytest.mark.parametrize("export_id", STUDY_RQ1_IDS)
def test_each_study_rq1_export_writes_valid_configured_outputs_and_source_identity(
    export_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ProjectPaths(ROOT)
    run = _run()
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    destination = tmp_path / export_id
    before = pe.snapshot_run_tree(run, project_root=ROOT)
    report = pe.export_one_presentation_figure(
        run_dir=RUN_CLOSE,
        output_dir=destination,
        export_id=export_id,
        paths=paths,
    )
    after = pe.snapshot_run_tree(run, project_root=ROOT)
    pe.assert_run_tree_unchanged(before, after)
    assert report["status"] == "PASS"
    assert report["source_run_unchanged"] is True
    spec = get_presentation_export_spec(export_id, paths=paths)
    png = destination / f"{export_id}.png"
    pdf = destination / f"{export_id}.pdf"
    assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert pdf.read_bytes().startswith(b"%PDF")
    with Image.open(png) as image:
        expected = (
            round_pixels_half_up(cm_to_inches(20.0), 300),
            round_pixels_half_up(cm_to_inches(15.0), 300),
        )
        assert image.size == expected
    manifest = json.loads(
        (destination / "presentation_export_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "PASS"
    assert len(manifest["exports"]) == 2
    assert {row["format"] for row in manifest["exports"]} == {"png", "pdf"}
    assert all(row["dimensions"]["width_cm"] == 20.0 for row in manifest["exports"])
    assert all(row["dimensions"]["height_cm"] == 15.0 for row in manifest["exports"])
    source = pe.resolve_source(spec, run, paths=paths)
    assert all(row["source_sha256"] == source.sha256 for row in manifest["exports"])
    assert all(row["exact_source_path"] == source.project_relative_path for row in manifest["exports"])
    assert not (destination / f"{export_id}.svg").exists()


@pytest.mark.parametrize("export_id", ("study_ghana_acz", "rq1_acz_seasonality", "rq1_district_departure", "rq1_district_seasonal_heatmap"))
def test_repeat_export_is_byte_deterministic(
    export_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = ProjectPaths(ROOT)
    run = _run()
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    first = tmp_path / f"{export_id}_a"
    second = tmp_path / f"{export_id}_b"
    pe.export_one_presentation_figure(
        run_dir=RUN_CLOSE, output_dir=first, export_id=export_id, paths=paths
    )
    pe.export_one_presentation_figure(
        run_dir=RUN_CLOSE, output_dir=second, export_id=export_id, paths=paths
    )
    for suffix in ("png", "pdf"):
        assert _sha(first / f"{export_id}.{suffix}") == _sha(second / f"{export_id}.{suffix}")
        assert (first / f"{export_id}.{suffix}").read_bytes() == (
            second / f"{export_id}.{suffix}"
        ).read_bytes()


def test_rq4_renderer_identities_are_now_registered() -> None:
    registry = pe.build_core_renderer_registry()
    assert callable(registry.resolve("cluster_membership_map"))
    assert callable(registry.resolve("cluster_recurrence_map"))


