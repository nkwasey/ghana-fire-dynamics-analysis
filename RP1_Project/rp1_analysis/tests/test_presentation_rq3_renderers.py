from __future__ import annotations
from scientific_input_reference import paired_input_reference, model_input_reference, design_terms_reference
from generated_run_reference import selected_run_base, require_selected_run

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
from rp1_analysis_v1.presentation_rq1 import render_rq1_district_choropleth
from rp1_analysis_v1.presentation_rq3 import (
    render_rq3_focal_effects,
    render_rq3_four_state_correspondence,
    render_rq3_standardised_probabilities,
)

ROOT = Path(__file__).resolve().parents[1]
RUN_BASE = selected_run_base(ROOT)
RUN_CLOSE = ROOT / "out" / "runs" / f"{RUN_BASE}_close"
FD_F5 = ROOT / "out" / "runs" / f"{RUN_BASE}_pub" / "03_rq3_observability" / "figure_data" / "FD_F5.csv"
S5 = ROOT / "out" / "runs" / f"{RUN_BASE}_pub" / "03_rq3_observability" / "tables" / "S5.csv"
EXPORTS = (
    "rq3_four_state_correspondence",
    "rq3_district_mismatch",
    "rq3_focal_effects",
    "rq3_standardised_probabilities",
)


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


def test_rq3_source_identity_is_computed_from_selected_run() -> None:
    for export_id in EXPORTS:
        _spec, _context, source = _context_and_source(export_id)
        assert source.sha256 == hashlib.sha256(source.path.read_bytes()).hexdigest()


def test_rq3_populations_and_four_state_counts_match_recorded_inputs() -> None:
    require_selected_run(ROOT, RUN_BASE)
    s5 = pd.read_csv(S5)
    overall = s5.loc[s5["record_type"].eq("four_state") & s5["scope"].eq("overall")].copy()
    paired = paired_input_reference()
    ba, viirs = paired.modis_ba_any_ba2012.eq(1), paired.viirs_det_primary.gt(0)
    expected = {"both_zero": int((~ba & ~viirs).sum()), "mcd64a1_positive_viirs_zero": int((ba & ~viirs).sum()),
                "viirs_positive_mcd64a1_zero": int((~ba & viirs).sum()), "both_positive": int((ba & viirs).sum())}
    assert overall["denominator_n"].eq(len(paired)).all()
    assert dict(zip(overall["state"].astype(str), overall["count"].astype(int), strict=True)) == expected
    diagnostics = s5.loc[s5["record_type"].eq("diagnostic")]
    lookup = {str(row["diagnostic_name"]): row["diagnostic_value"] for _, row in diagnostics.iterrows()}
    model = model_input_reference()
    expected_diagnostics = {"observations": len(model), "districts": model.unit_id.nunique(),
                            "outcome_y1": int(model.mismatch_y.sum()), "outcome_y0": int(model.mismatch_y.eq(0).sum()),
                            "model_columns": len(design_terms_reference())}
    for key, value in expected_diagnostics.items():
        assert int(float(lookup[key])) == value


def test_presentation_export_selectors_resolve_expected_rq3_shapes() -> None:
    require_selected_run(ROOT, RUN_BASE)
    expected_rows = {
        "rq3_four_state_correspondence": 20,
        "rq3_district_mismatch": pd.read_csv(ROOT / "data/raw/fire_panel_district_monthly_consolidated_2001_2024.csv").unit_id.nunique(),
        "rq3_focal_effects": 2,
        "rq3_standardised_probabilities": 4,
    }
    for export_id, rows in expected_rows.items():
        _spec, _context, source = _context_and_source(export_id)
        assert source.frame is not None
        assert len(source.frame) == rows


def test_four_state_renderer_returns_valid_configured_png_pdf() -> None:
    spec, context, source = _context_and_source("rq3_four_state_correspondence")
    assert source.frame is not None
    rendered = render_rq3_four_state_correspondence(source.frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")
    assert rendered.width_in == pytest.approx(20.0 / 2.54)
    assert rendered.height_in == pytest.approx(15.0 / 2.54)
    assert rendered.dpi == 300


def test_four_state_renderer_fails_closed_on_broken_within_acz_support() -> None:
    spec, context, source = _context_and_source("rq3_four_state_correspondence")
    assert source.frame is not None
    broken = source.frame.copy()
    broken = broken.loc[~((broken["parent_code"] == "CZ") & (broken["state"] == "both_positive"))].copy()
    with pytest.raises(FigureRenderError, match="requires exactly 20 governed rows|contain all four states"):
        render_rq3_four_state_correspondence(broken, spec=spec, context=context)


def test_district_mismatch_renderer_uses_current_supported_districts() -> None:
    spec, context, source = _context_and_source("rq3_district_mismatch")
    assert source.frame is not None
    frame = source.frame
    assert frame.unit_id.is_unique
    valid = frame.loc[~frame["support_status"].eq("excluded")].copy()
    assert set(valid.unit_id) == set(paired_input_reference().unit_id)
    assert valid["value"].between(0.0, 1.0, inclusive="both").all()
    rendered = render_rq1_district_choropleth(frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")


def test_focal_effect_source_matches_selected_model_coefficients() -> None:
    _spec, _context, source = _context_and_source("rq3_focal_effects")
    assert source.frame is not None
    frame = source.frame.copy()
    s5 = pd.read_csv(S5)
    coefficients = s5.loc[s5["record_type"].eq("coefficient") & s5["term_role"].eq("focal_predictor")]
    labels = {"log2_viirs_det_primary": "VIIRS detection count (per doubling)",
              "log2_viirs_frp_mean_mw": "Mean FRP (per doubling)"}
    assert set(frame.term) == {labels[str(term)] for term in coefficients.term}
    for row in coefficients.itertuples(index=False):
        observed = frame.loc[frame.term.eq(labels[str(row.term)])].iloc[0]
        for field in ("adjusted_or", "or_lower_95", "or_upper_95", "p"):
            assert float(observed[field]) == pytest.approx(float(getattr(row, field)), rel=1e-12, abs=1e-15)


def test_focal_effect_renderer_returns_valid_configured_png_pdf() -> None:
    spec, context, source = _context_and_source("rq3_focal_effects")
    assert source.frame is not None
    rendered = render_rq3_focal_effects(source.frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")


def test_standardised_probability_source_matches_selected_model() -> None:
    _spec, _context, source = _context_and_source("rq3_standardised_probabilities")
    assert source.frame is not None
    frame = source.frame.copy()
    model = model_input_reference()
    assert frame["n"].eq(len(model)).all()
    assert frame["districts"].eq(model.unit_id.nunique()).all()
    expected = pd.read_csv(S5).loc[lambda x: x.record_type.eq("standardised_probability")]
    keys = ["predictor_id", "quantile"]
    columns = keys + ["raw_quantile_value", "standardised_probability"]
    pd.testing.assert_frame_equal(frame[columns].sort_values(keys).reset_index(drop=True),
                                  expected[columns].sort_values(keys).reset_index(drop=True), check_dtype=False)
    assert frame["standardised_probability"].between(0.0, 1.0).all()


def test_standardised_probability_renderer_returns_valid_configured_png_pdf() -> None:
    spec, context, source = _context_and_source("rq3_standardised_probabilities")
    assert source.frame is not None
    rendered = render_rq3_standardised_probabilities(source.frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")


def test_exporter_registry_marks_all_four_rq3_exports_implemented() -> None:
    paths = ProjectPaths(ROOT)
    registry = pe.build_core_renderer_registry()
    assert callable(registry.resolve("stacked_proportions"))
    assert callable(registry.resolve("coefficient_or_plot"))
    assert callable(registry.resolve("standardised_probability_pairs"))
    listed = {row["export_id"]: row for row in pe.list_presentation_exports(paths=paths)}
    for export_id in EXPORTS:
        assert listed[export_id]["implementation_status"] == "IMPLEMENTED"


@pytest.mark.parametrize("export_id", EXPORTS)
def test_end_to_end_rq3_export_is_read_only_and_manifest_bound(export_id: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert (destination / f"{export_id}.png").read_bytes().startswith(b"\x89PNG")
    assert (destination / f"{export_id}.pdf").read_bytes().startswith(b"%PDF")


def test_deterministic_repeat_rendering_for_all_four_rq3_exports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    require_selected_run(ROOT, RUN_BASE)
    paths = ProjectPaths(ROOT)
    run = pe.resolve_run_family(RUN_CLOSE, paths=paths, validate=False)
    monkeypatch.setattr(pe, "resolve_run_family", lambda *args, **kwargs: run)
    for export_id in EXPORTS:
        first = tmp_path / f"{export_id}_a"
        second = tmp_path / f"{export_id}_b"
        pe.export_one_presentation_figure(run_dir=RUN_CLOSE, output_dir=first, export_id=export_id, paths=paths)
        pe.export_one_presentation_figure(run_dir=RUN_CLOSE, output_dir=second, export_id=export_id, paths=paths)
        assert (first / f"{export_id}.png").read_bytes() == (second / f"{export_id}.png").read_bytes()
        assert (first / f"{export_id}.pdf").read_bytes() == (second / f"{export_id}.pdf").read_bytes()


