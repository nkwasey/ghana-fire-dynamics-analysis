from __future__ import annotations
from generated_run_reference import selected_run_base, require_selected_run

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import rp1_analysis_v1.presentation_export as pe
import rp1_analysis_v1.presentation_rq2 as rq2
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.figures import FigureRenderError
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.presentation import get_presentation_export_spec
from rp1_analysis_v1.presentation_rq2 import render_rq2_five_acz_comparison, render_rq2_single_trend

ROOT = Path(__file__).resolve().parents[1]
RUN_BASE = selected_run_base(ROOT)
RUN_CLOSE = ROOT / "out" / "runs" / f"{RUN_BASE}_close"
FD_F4 = ROOT / "out" / "runs" / f"{RUN_BASE}_pub" / "02_rq2_temporal_robustness" / "figure_data" / "FD_F4.csv"
S4 = ROOT / "out" / "runs" / f"{RUN_BASE}_pub" / "02_rq2_temporal_robustness" / "tables" / "S4.csv"
EXPORTS = {
    "rq2_coastal_trend": "CZ",
    "rq2_forest_trend": "FZ",
    "rq2_guinea_trend": "GS",
    "rq2_sudan_trend": "SS",
    "rq2_transition_trend": "TZ",
}


def _context_and_source(export_id: str):
    require_selected_run(ROOT, RUN_BASE)
    paths = ProjectPaths(ROOT)
    bundle = load_configuration_bundle(ROOT / "config")
    registry = bundle.figure.presentation_export
    assert registry is not None
    spec = get_presentation_export_spec(export_id, bundle.figure)
    run = pe.resolve_run_family(RUN_CLOSE, paths=paths, validate=False)
    source = pe.resolve_source(spec, run, paths=paths)
    geometry = pe.resolve_geometry_dependency(spec.geometry_dependency, paths=paths, bundle=bundle, registry=registry)
    style = pe._presentation_style(bundle, spec)
    context = pe.RenderContext(paths, bundle, registry, run, source, geometry, style)
    return spec, context, source


def test_fd_f4_source_identity_is_computed_from_selected_run() -> None:
    spec, context, source = _context_and_source("rq2_five_acz_comparison")
    assert source.sha256 == hashlib.sha256(source.path.read_bytes()).hexdigest()


def test_fd_f4_numeric_projection_exactly_matches_governed_s4() -> None:
    require_selected_run(ROOT, RUN_BASE)
    fd = pd.read_csv(FD_F4)
    s4 = pd.read_csv(S4)
    cols = ["parent_code", "parent_name", "year", "annual_rate", "sen_slope", "raw_p", "bh_q"]
    pd.testing.assert_frame_equal(fd[cols], s4[cols], check_exact=True, check_dtype=True)


@pytest.mark.parametrize(("export_id", "code"), tuple(EXPORTS.items()))
def test_each_single_export_resolves_configured_year_series(export_id: str, code: str) -> None:
    _spec, context, source = _context_and_source(export_id)
    frame = source.frame
    assert frame is not None
    window = context.bundle.analysis.study["temporal_windows"]["long_run"]
    years = tuple(range(int(str(window["start"])[:4]), int(str(window["end"])[:4]) + 1))
    assert tuple(frame["year"].astype(int)) == years
    assert set(frame["parent_code"].astype(str)) == {code}
    authority = pd.read_csv(S4).loc[lambda x: x.parent_code.eq(code)]
    columns = ["parent_code", "parent_name", "year", "annual_rate", "sen_slope", "raw_p", "bh_q"]
    pd.testing.assert_frame_equal(frame[columns].reset_index(drop=True), authority[columns].reset_index(drop=True), check_dtype=False)
    for field in ("sen_slope", "raw_p", "bh_q"):
        assert frame[field].nunique() == 1
    assert frame["raw_p"].between(0.0, 1.0).all()
    assert frame["bh_q"].between(0.0, 1.0).all()


@pytest.mark.parametrize("export_id", tuple(EXPORTS))
def test_single_renderer_returns_valid_configured_png_pdf(export_id: str, monkeypatch) -> None:
    spec, context, source = _context_and_source(export_id)
    assert source.frame is not None
    export = rq2.export_figure

    def capture(fig, style):
        ax, = fig.axes
        assert ax.get_title() == spec.label
        observed, slope = ax.lines
        assert (observed.get_color(), observed.get_marker(), observed.get_linestyle()) == ("#0072B2", "o", "-")
        assert (slope.get_color(), slope.get_linestyle()) == ("#D55E00", "--")
        return export(fig, style)

    monkeypatch.setattr(rq2, "export_figure", capture)
    rendered = render_rq2_single_trend(source.frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")
    assert rendered.width_in == pytest.approx(20.0 / 2.54)
    assert rendered.height_in == pytest.approx(15.0 / 2.54)
    assert rendered.dpi == 300


def test_single_renderer_fails_closed_on_wrong_year_support() -> None:
    spec, context, source = _context_and_source("rq2_coastal_trend")
    assert source.frame is not None
    broken = source.frame.iloc[:-1].copy()
    window = context.bundle.analysis.study["temporal_windows"]["long_run"]
    annual_count = int(str(window["end"])[:4]) - int(str(window["start"])[:4]) + 1
    with pytest.raises(FigureRenderError, match=f"exactly {annual_count} annual rows"):
        render_rq2_single_trend(broken, spec=spec, context=context)


def test_single_renderer_fails_closed_on_inconsistent_inference_authority() -> None:
    spec, context, source = _context_and_source("rq2_coastal_trend")
    assert source.frame is not None
    broken = source.frame.copy()
    broken.loc[broken.index[-1], "bh_q"] = 0.01
    with pytest.raises(FigureRenderError, match="one governed bh_q"):
        render_rq2_single_trend(broken, spec=spec, context=context)


def test_five_acz_comparison_is_approved_and_complete() -> None:
    spec, context, source = _context_and_source("rq2_five_acz_comparison")
    assert source.frame is not None
    assert len(source.frame) == len(pd.read_csv(S4))
    assert set(source.frame["parent_code"].astype(str)) == set(EXPORTS.values())
    rendered = render_rq2_five_acz_comparison(source.frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")


def test_exporter_registry_implements_exactly_six_rq2_exports() -> None:
    paths = ProjectPaths(ROOT)
    registry = pe.build_core_renderer_registry()
    assert callable(registry.resolve("single_trajectory_with_sen"))
    assert callable(registry.resolve("grid_trajectory_with_sen"))
    listed = {row["export_id"]: row for row in pe.list_presentation_exports(paths=paths)}
    for export_id in (*EXPORTS, "rq2_five_acz_comparison"):
        assert listed[export_id]["implementation_status"] == "IMPLEMENTED"


@pytest.mark.parametrize("export_id", tuple(EXPORTS))
def test_end_to_end_single_export_is_read_only_and_manifest_bound(export_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    require_selected_run(ROOT, RUN_BASE)
    paths = ProjectPaths(ROOT)
    run = pe.resolve_run_family(RUN_CLOSE, paths=paths, validate=False)
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
    assert {row["source_sha256"] for row in manifest["exports"]} == {_context_and_source(export_id)[2].sha256}
    assert (destination / f"{export_id}.png").read_bytes().startswith(b"\x89PNG")
    assert (destination / f"{export_id}.pdf").read_bytes().startswith(b"%PDF")


def test_end_to_end_five_acz_comparison_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    require_selected_run(ROOT, RUN_BASE)
    paths = ProjectPaths(ROOT)
    run = pe.resolve_run_family(RUN_CLOSE, paths=paths, validate=False)
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    before = pe.snapshot_run_tree(run, project_root=ROOT)
    destination = tmp_path / "comparison"
    report = pe.export_one_presentation_figure(run_dir=RUN_CLOSE, output_dir=destination, export_id="rq2_five_acz_comparison", paths=paths)
    after = pe.snapshot_run_tree(run, project_root=ROOT)
    pe.assert_run_tree_unchanged(before, after)
    assert report["status"] == "PASS"
    assert report["source_run_unchanged"] is True


def test_deterministic_repeat_rendering_for_all_six_exports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    require_selected_run(ROOT, RUN_BASE)
    paths = ProjectPaths(ROOT)
    run = pe.resolve_run_family(RUN_CLOSE, paths=paths, validate=False)
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    for export_id in (*EXPORTS, "rq2_five_acz_comparison"):
        first = tmp_path / f"{export_id}_a"
        second = tmp_path / f"{export_id}_b"
        pe.export_one_presentation_figure(run_dir=RUN_CLOSE, output_dir=first, export_id=export_id, paths=paths)
        pe.export_one_presentation_figure(run_dir=RUN_CLOSE, output_dir=second, export_id=export_id, paths=paths)
        assert (first / f"{export_id}.png").read_bytes() == (second / f"{export_id}.png").read_bytes()
        assert (first / f"{export_id}.pdf").read_bytes() == (second / f"{export_id}.pdf").read_bytes()


