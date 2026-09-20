from __future__ import annotations

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
RUN_BASE = "qualified_presentation_fixture"
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
)


def _run() -> pe.RunFamilyAuthority:
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
    assert spec.units == "km² burned per 100 km² fixed BA-2001 burnable area per year"
    assert frame["support_status"].astype(str).eq("valid_nonzero").all()


def test_rq1_district_support_counts_and_valid_zero_semantics_are_preserved() -> None:
    frame = _source("rq1_district_long_run_rate").frame
    assert frame is not None
    assert len(frame) == 260
    assert frame["unit_id"].nunique() == 260
    assert int((~frame["support_status"].astype(str).eq("excluded")).sum()) == 250
    assert int(frame["support_status"].astype(str).eq("excluded").sum()) == 10
    valid_zero = frame["support_status"].astype(str).eq("valid_zero")
    assert int(valid_zero.sum()) == 14
    assert pd.to_numeric(frame.loc[valid_zero, "value"], errors="raise").eq(0.0).all()
    assert frame.loc[frame["support_status"].astype(str).eq("excluded"), "value"].isna().all()


def test_governed_geometry_join_preserves_exact_district_universe() -> None:
    districts = gpd.read_file(ROOT / "data" / "geo" / "districts_within_acz.shp")
    acz = gpd.read_file(ROOT / "data" / "geo" / "acz.shp")
    authority = prepare_geography(districts, acz)
    frame = _source("rq1_district_long_run_rate").frame
    assert frame is not None
    merged = join_district_figure_data(authority, frame)
    assert len(districts) == 260
    assert len(acz) == 5
    assert len(merged) == 260
    assert merged["dist_id"].astype(str).nunique() == 260
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
    assert any("μ and R" in text for text in spec.annotation_policy)


def test_district_departure_sign_is_consumed_not_recomputed() -> None:
    frame = _source("rq1_district_departure").frame
    assert frame is not None
    retained = frame.loc[~frame["support_status"].astype(str).eq("excluded")]
    values = pd.to_numeric(retained["value"], errors="raise")
    assert len(retained) == 250
    assert values.lt(0).any()
    assert values.gt(0).any()
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
    assert int(retained["local_class"].astype(str).eq("ISLAND").sum()) == 1
    assert frame.loc[frame["support_status"].astype(str).eq("excluded"), "local_class"].isna().all()
    # Renderer source is categorical authority only; it carries no recalculated statistic.
    assert frame["value"].isna().all()


def test_s1_source_preserves_250_by_12_support_and_undefined_zero_district_timing() -> None:
    frame = _source("rq1_district_seasonal_heatmap").frame
    assert frame is not None
    assert len(frame) == 3000
    assert frame["unit_id"].nunique() == 250
    assert tuple(sorted(frame["month"].astype(int).unique())) == tuple(range(1, 13))
    counts = frame.groupby("unit_id", observed=True)["month"].nunique()
    assert counts.eq(12).all()
    all_missing = frame.groupby("unit_id", observed=True)["monthly_share"].apply(lambda s: s.isna().all())
    assert int(all_missing.sum()) == 14
    assert int(frame["monthly_share"].isna().sum()) == 14 * 12
    work, summary = rq1p._normalise_s1(frame)
    assert len(work) == 3000
    assert len(summary) == 250
    undefined = summary["circular_mean_month"].isna()
    assert int(undefined.sum()) == 14
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
