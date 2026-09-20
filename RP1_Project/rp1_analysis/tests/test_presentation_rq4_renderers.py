from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

import rp1_analysis_v1.presentation_export as pe
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.presentation import get_presentation_export_spec
from rp1_analysis_v1.presentation_rq4 import (
    render_rq4_cluster_membership,
    render_rq4_cluster_recurrence,
)

ROOT = Path(__file__).resolve().parents[1]
RUN_BASE = "qualified_presentation_fixture"
RUN_CLOSE = ROOT / "out" / "runs" / f"{RUN_BASE}_close"
RUN_SEC = ROOT / "out" / "runs" / f"{RUN_BASE}_sec"
MEMBERSHIP = RUN_SEC / "04_secondary_concentration" / "publication_sources" / "cluster_membership_source.csv"
RECURRENCE = RUN_SEC / "04_secondary_concentration" / "publication_sources" / "cluster_recurrence_source.csv"
STATUS = RUN_SEC / "04_secondary_concentration" / "secondary_external_execution_status.json"
MANIFEST = RUN_SEC / "04_secondary_concentration" / "publication_sources" / "M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json"
EXPECTED_MEMBERSHIP_SHA = "857fc399ab87e97c0a3ff753628bf3f94171d206e23441ef3083a53359ee369b"
EXPECTED_RECURRENCE_SHA = "379df7566b6a3aa5428766fe142de9dc969bd6f19f5a424f40622baafc6d74aa"
EXPORTS = (
    "rq4_mcd64a1_clusters",
    "rq4_viirs_clusters",
    "rq4_mcd64a1_recurrence",
    "rq4_viirs_recurrence",
)


def _context_and_source(export_id: str):
    paths = ProjectPaths(ROOT)
    bundle = load_configuration_bundle(ROOT / "config")
    registry = bundle.figure.presentation_export
    assert registry is not None
    spec = get_presentation_export_spec(export_id, bundle.figure)
    run = pe.resolve_run_family(RUN_CLOSE, paths=paths, validate=False)
    run = replace(
        run,
        validation=pe.RunValidationResult(
            run_id=RUN_BASE,
            status="PASS",
            publication_files=1,
            secondary_files=1,
            closeout_files=1,
            publication_tables=1,
            publication_figures=1,
            secondary_external_state="RESULTS_VALIDATED",
            output_inventory=pd.DataFrame(columns=["path", "sha256", "size_bytes"]),
            checks=(),
        ),
    )
    source = pe.resolve_source(spec, run, paths=paths)
    geometry = pe.resolve_geometry_dependency(spec.geometry_dependency, paths=paths, bundle=bundle, registry=registry)
    style = pe._presentation_style(bundle, spec)
    context = pe.RenderContext(paths, bundle, registry, run, source, geometry, style)
    return spec, context, source, run


def test_rq4_governed_secondary_sources_are_byte_identical() -> None:
    assert hashlib.sha256(MEMBERSHIP.read_bytes()).hexdigest() == EXPECTED_MEMBERSHIP_SHA
    assert hashlib.sha256(RECURRENCE.read_bytes()).hexdigest() == EXPECTED_RECURRENCE_SHA


def test_rq4_secondary_state_and_publication_source_manifest_are_validated() -> None:
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    assert status["external_execution_state"] == "RESULTS_VALIDATED"
    assert status["validated_model_count"] == 2
    assert status["satscan_engine_version_authority"] == "10.3.3"
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["external_execution_state"] == "RESULTS_VALIDATED"
    assert manifest["secondary_run_id"] == f"{RUN_BASE}_sec"
    assert manifest["sources"]["cluster_membership_source"]["rows"] == 5861
    assert manifest["sources"]["cluster_recurrence_source"]["rows"] == 520


def test_rq4_governed_cluster_and_membership_counts_are_exact() -> None:
    membership = pd.read_csv(MEMBERSHIP)
    recurrence = pd.read_csv(RECURRENCE)
    assert membership.shape == (5861, 3)
    assert recurrence.shape == (520, 7)
    by_product = membership.groupby("product", observed=True)["cluster_id"].agg(["nunique", "size"]).reset_index()
    counts = {str(row.product): {"clusters": int(row.nunique), "memberships": int(row.size)} for row in by_product.itertuples(index=False)}
    assert counts == {
        "mcd64a1": {"clusters": 104, "memberships": 2435},
        "viirs": {"clusters": 108, "memberships": 3426},
    }
    totals = recurrence.groupby("product", observed=True)["total_significant_clusters"].nunique().to_dict()
    assert totals == {"mcd64a1": 1, "viirs": 1}
    assert int(recurrence.loc[recurrence["product"].eq("mcd64a1"), "total_significant_clusters"].iloc[0]) == 104
    assert int(recurrence.loc[recurrence["product"].eq("viirs"), "total_significant_clusters"].iloc[0]) == 108


@pytest.mark.parametrize(
    ("export_id", "expected_rows"),
    [
        ("rq4_mcd64a1_clusters", 2435),
        ("rq4_viirs_clusters", 3426),
        ("rq4_mcd64a1_recurrence", 260),
        ("rq4_viirs_recurrence", 260),
    ],
)
def test_presentation_export_selectors_resolve_expected_rq4_shapes(export_id: str, expected_rows: int) -> None:
    _spec, _context, source, _run = _context_and_source(export_id)
    assert source.frame is not None
    assert len(source.frame) == expected_rows


@pytest.mark.parametrize("export_id", ("rq4_mcd64a1_clusters", "rq4_viirs_clusters"))
def test_cluster_membership_renderers_return_valid_png_pdf(export_id: str) -> None:
    spec, context, source, run = _context_and_source(export_id)
    pe.validate_required_result_state(spec, run)
    pe.resolve_secondary_export_authority(spec, run, source, paths=ProjectPaths(ROOT))
    assert source.frame is not None
    rendered = render_rq4_cluster_membership(source.frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")


@pytest.mark.parametrize("export_id", ("rq4_mcd64a1_recurrence", "rq4_viirs_recurrence"))
def test_cluster_recurrence_renderers_return_valid_png_pdf(export_id: str) -> None:
    spec, context, source, run = _context_and_source(export_id)
    pe.validate_required_result_state(spec, run)
    pe.resolve_secondary_export_authority(spec, run, source, paths=ProjectPaths(ROOT))
    assert source.frame is not None
    rendered = render_rq4_cluster_recurrence(source.frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")


def test_exporter_registry_marks_all_four_rq4_exports_implemented() -> None:
    listed = {row["export_id"]: row for row in pe.list_presentation_exports(paths=ProjectPaths(ROOT))}
    for export_id in EXPORTS:
        assert listed[export_id]["implementation_status"] == "IMPLEMENTED"


@pytest.mark.parametrize("export_id", EXPORTS)
def test_end_to_end_rq4_export_is_read_only_and_manifest_bound(export_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = ProjectPaths(ROOT)
    _spec, _context, _source, run = _context_and_source(export_id)
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    before = pe.snapshot_run_tree(run, project_root=ROOT)
    destination = tmp_path / export_id
    report = pe.export_one_presentation_figure(run_dir=RUN_CLOSE, output_dir=destination, export_id=export_id, paths=paths)
    after = pe.snapshot_run_tree(run, project_root=ROOT)
    pe.assert_run_tree_unchanged(before, after)
    assert report["status"] == "PASS"
    assert report["source_run_unchanged"] is True
    manifest = json.loads((destination / "presentation_export_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_run_read_only"] is True
    inventory = pd.read_csv(destination / "presentation_export_source_inventory.csv")
    kinds = set(inventory["kind"].astype(str))
    assert "secondary_result_report" in kinds
    assert "secondary_result_cluster" in kinds
    assert "secondary_result_membership" in kinds
    assert (destination / f"{export_id}.png").read_bytes().startswith(b"\x89PNG")
    assert (destination / f"{export_id}.pdf").read_bytes().startswith(b"%PDF")


def test_deterministic_repeat_rendering_for_all_four_rq4_exports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paths = ProjectPaths(ROOT)
    _spec, _context, _source, run = _context_and_source("rq4_mcd64a1_clusters")
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    for export_id in EXPORTS:
        first = tmp_path / f"{export_id}_a"
        second = tmp_path / f"{export_id}_b"
        pe.export_one_presentation_figure(run_dir=RUN_CLOSE, output_dir=first, export_id=export_id, paths=paths)
        pe.export_one_presentation_figure(run_dir=RUN_CLOSE, output_dir=second, export_id=export_id, paths=paths)
        assert (first / f"{export_id}.png").read_bytes() == (second / f"{export_id}.png").read_bytes()
        assert (first / f"{export_id}.pdf").read_bytes() == (second / f"{export_id}.pdf").read_bytes()
