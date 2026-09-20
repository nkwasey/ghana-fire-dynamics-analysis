from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

import rp1_analysis_v1.presentation_export as pe
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.figures import FigureRenderError
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.presentation import get_presentation_export_spec
from rp1_analysis_v1.presentation_rq2 import render_rq2_five_acz_comparison, render_rq2_single_trend

ROOT = Path(__file__).resolve().parents[1]
RUN_BASE = "qualified_presentation_fixture"
RUN_CLOSE = ROOT / "out" / "runs" / f"{RUN_BASE}_close"
FD_F4 = ROOT / "out" / "runs" / f"{RUN_BASE}_pub" / "02_rq2_temporal_robustness" / "figure_data" / "FD_F4.csv"
S4 = ROOT / "out" / "runs" / f"{RUN_BASE}_pub" / "02_rq2_temporal_robustness" / "tables" / "S4.csv"
EXPECTED_SOURCE_SHA = "7e92e946c3c8f6ad6cefd9850de2dcb6f45ab45c8df14e7b5513a9b42336a32a"
EXPECTED = {
    "CZ": ("COASTAL ZONE", -0.1647449475437066, 0.2322, 0.29025),
    "FZ": ("FOREST ZONE", -0.0531408764429660, 0.5741, 0.5741),
    "GS": ("GUINEA SAVANNAH", -0.4502995257160126, 0.0833, 0.20825),
    "SS": ("SUDAN SAVANNAH", -0.5015820536774339, 0.1372, 0.2286666666666666),
    "TZ": ("TRANSITION ZONE", -0.6753271231724751, 0.0571, 0.20825),
}
EXPORTS = {
    "rq2_coastal_trend": "CZ",
    "rq2_forest_trend": "FZ",
    "rq2_guinea_trend": "GS",
    "rq2_sudan_trend": "SS",
    "rq2_transition_trend": "TZ",
}


def _context_and_source(export_id: str):
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


def test_fd_f4_is_byte_identical_to_governed_source_identity() -> None:
    assert hashlib.sha256(FD_F4.read_bytes()).hexdigest() == EXPECTED_SOURCE_SHA


def test_fd_f4_numeric_projection_exactly_matches_governed_s4() -> None:
    fd = pd.read_csv(FD_F4)
    s4 = pd.read_csv(S4)
    cols = ["parent_code", "parent_name", "year", "annual_rate", "sen_slope", "raw_p", "bh_q"]
    pd.testing.assert_frame_equal(fd[cols], s4[cols], check_exact=True, check_dtype=True)


@pytest.mark.parametrize(("export_id", "code"), tuple(EXPORTS.items()))
def test_each_single_export_resolves_exact_governed_24_year_series(export_id: str, code: str) -> None:
    _spec, _context, source = _context_and_source(export_id)
    frame = source.frame
    assert frame is not None
    assert len(frame) == 24
    assert tuple(frame["year"].astype(int)) == tuple(range(2001, 2025))
    assert set(frame["parent_code"].astype(str)) == {code}
    name, slope, raw_p, q = EXPECTED[code]
    assert set(frame["parent_name"].astype(str)) == {name}
    assert frame["sen_slope"].nunique() == frame["raw_p"].nunique() == frame["bh_q"].nunique() == 1
    assert float(frame["sen_slope"].iloc[0]) == pytest.approx(slope, abs=1e-15)
    assert float(frame["raw_p"].iloc[0]) == pytest.approx(raw_p, abs=1e-15)
    assert float(frame["bh_q"].iloc[0]) == pytest.approx(q, abs=1e-15)
    assert float(frame["sen_slope"].iloc[0]) < 0.0
    assert float(frame["bh_q"].iloc[0]) >= 0.05


@pytest.mark.parametrize("export_id", tuple(EXPORTS))
def test_single_renderer_returns_valid_configured_png_pdf(export_id: str) -> None:
    spec, context, source = _context_and_source(export_id)
    assert source.frame is not None
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
    with pytest.raises(FigureRenderError, match="exactly 24 annual rows"):
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
    assert len(source.frame) == 120
    assert set(source.frame["parent_code"].astype(str)) == set(EXPECTED)
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
    assert {row["source_sha256"] for row in manifest["exports"]} == {EXPECTED_SOURCE_SHA}
    assert (destination / f"{export_id}.png").read_bytes().startswith(b"\x89PNG")
    assert (destination / f"{export_id}.pdf").read_bytes().startswith(b"%PDF")


def test_end_to_end_five_acz_comparison_is_read_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
