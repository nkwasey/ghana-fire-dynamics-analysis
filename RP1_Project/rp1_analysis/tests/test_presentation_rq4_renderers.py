from __future__ import annotations
from generated_run_reference import selected_run_base, require_selected_run

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
RUN_BASE = selected_run_base(ROOT)
RUN_CLOSE = ROOT / "out" / "runs" / f"{RUN_BASE}_close"
RUN_SEC = ROOT / "out" / "runs" / f"{RUN_BASE}_sec"
MEMBERSHIP = RUN_SEC / "04_secondary_concentration" / "publication_sources" / "cluster_membership_source.csv"
RECURRENCE = RUN_SEC / "04_secondary_concentration" / "publication_sources" / "cluster_recurrence_source.csv"
STATUS = RUN_SEC / "04_secondary_concentration" / "secondary_external_execution_status.json"
MANIFEST = RUN_SEC / "04_secondary_concentration" / "publication_sources" / "M_SATSCAN_PUBLICATION_SOURCE_MANIFEST.json"
EXPORTS = (
    "rq4_mcd64a1_clusters",
    "rq4_viirs_clusters",
    "rq4_mcd64a1_recurrence",
    "rq4_viirs_recurrence",
)


def _context_and_source(export_id: str):
    require_selected_run(ROOT, RUN_BASE, external=True)
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


def test_rq4_secondary_sources_match_their_local_manifest() -> None:
    require_selected_run(ROOT, RUN_BASE, external=True)
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    for name, path in (("cluster_membership_source", MEMBERSHIP), ("cluster_recurrence_source", RECURRENCE)):
        assert hashlib.sha256(path.read_bytes()).hexdigest() == manifest["sources"][name]["sha256"]


def test_rq4_secondary_state_and_publication_source_manifest_are_validated() -> None:
    require_selected_run(ROOT, RUN_BASE, external=True)
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    assert status["external_execution_state"] == "RESULTS_VALIDATED"
    assert status["validated_model_count"] == len(load_configuration_bundle(ROOT / "config").analysis.secondary_analysis["scenarios"])
    assert status["satscan_engine_version_authority"]
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["external_execution_state"] == "RESULTS_VALIDATED"
    assert manifest["secondary_run_id"] == f"{RUN_BASE}_sec"
    assert manifest["sources"]["cluster_membership_source"]["rows"] == len(pd.read_csv(MEMBERSHIP))
    assert manifest["sources"]["cluster_recurrence_source"]["rows"] == len(pd.read_csv(RECURRENCE))


def test_rq4_membership_and_recurrence_share_current_cluster_counts() -> None:
    require_selected_run(ROOT, RUN_BASE, external=True)
    membership, recurrence = pd.read_csv(MEMBERSHIP), pd.read_csv(RECURRENCE)
    assert {"product", "cluster_id", "unit_id"}.issubset(membership.columns)
    assert not membership.duplicated(["product", "cluster_id", "unit_id"]).any()
    for product, group in recurrence.groupby("product", observed=True):
        selected = membership.loc[membership["product"].eq(product)]
        assert group.total_significant_clusters.eq(selected.cluster_id.nunique()).all()


@pytest.mark.parametrize("export_id", EXPORTS)
def test_presentation_export_selectors_resolve_expected_rq4_shapes(export_id: str) -> None:
    _spec, _context, source, _run = _context_and_source(export_id)
    assert source.frame is not None
    origin = pd.read_csv(RECURRENCE if "recurrence" in export_id else MEMBERSHIP)
    product = "mcd64a1" if "mcd64a1" in export_id else "viirs"
    assert len(source.frame) == int(origin["product"].eq(product).sum())


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


