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
from rp1_analysis_v1.presentation_rq1 import render_rq1_district_choropleth
from rp1_analysis_v1.presentation_rq3 import (
    render_rq3_focal_effects,
    render_rq3_four_state_correspondence,
    render_rq3_standardised_probabilities,
)

ROOT = Path(__file__).resolve().parents[1]
RUN_BASE = "qualified_presentation_fixture"
RUN_CLOSE = ROOT / "out" / "runs" / f"{RUN_BASE}_close"
FD_F5 = ROOT / "out" / "runs" / f"{RUN_BASE}_pub" / "03_rq3_observability" / "figure_data" / "FD_F5.csv"
S5 = ROOT / "out" / "runs" / f"{RUN_BASE}_pub" / "03_rq3_observability" / "tables" / "S5.csv"
EXPECTED_FD_F5_SHA = "38736b0376469908b7a057ce88e52462bec8ccad0efbec16c0c26158d51c5317"
EXPECTED_S5_SHA = "c83c612186a7b7d144b86e1c04f5870f2f9966f3bf99f18701cd718b45f331b4"
EXPECTED_OVERALL_COUNTS = {
    "both_zero": 15447,
    "mcd64a1_positive_viirs_zero": 209,
    "viirs_positive_mcd64a1_zero": 16811,
    "both_positive": 6128,
}
EXPECTED_FOCAL = {
    "VIIRS detection count (per doubling)": {
        "beta": -0.7843026825360361,
        "corrected_se": 0.0399247377445332,
        "adjusted_or": 0.4564378729396108,
        "or_lower_95": 0.4220828190165896,
        "or_upper_95": 0.493589225780469,
        "p": 6.439083909458447e-86,
    },
    "Mean FRP (per doubling)": {
        "beta": -0.5011983313001792,
        "corrected_se": 0.0693817366830306,
        "adjusted_or": 0.6058042703530587,
        "or_lower_95": 0.5287793529104989,
        "or_upper_95": 0.694049062161699,
        "p": 5.05624111169361e-13,
    },
}
EXPECTED_STANDARDISED = {
    "viirs_detection_count": {
        0.25: {"raw_quantile_value": 2.0, "standardised_probability": 0.9185166447796452},
        0.75: {"raw_quantile_value": 40.0, "standardised_probability": 0.6128446058877899},
    },
    "viirs_mean_frp": {
        0.25: {"raw_quantile_value": 4.09, "standardised_probability": 0.7599209398023414},
        0.75: {"raw_quantile_value": 10.018712121212122, "standardised_probability": 0.7147889477059636},
    },
}
EXPORTS = (
    "rq3_four_state_correspondence",
    "rq3_district_mismatch",
    "rq3_focal_effects",
    "rq3_standardised_probabilities",
)


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


def test_rq3_governed_sources_are_byte_identical() -> None:
    assert hashlib.sha256(FD_F5.read_bytes()).hexdigest() == EXPECTED_FD_F5_SHA
    assert hashlib.sha256(S5.read_bytes()).hexdigest() == EXPECTED_S5_SHA


def test_rq3_overall_populations_and_four_state_counts_are_exact() -> None:
    s5 = pd.read_csv(S5)
    overall = s5.loc[s5["record_type"].eq("four_state") & s5["scope"].eq("overall")].copy()
    assert len(overall) == 4
    assert overall["denominator_n"].eq(38595).all()
    assert dict(zip(overall["state"].astype(str), overall["count"].astype(int), strict=True)) == EXPECTED_OVERALL_COUNTS

    diagnostics = s5.loc[s5["record_type"].eq("diagnostic")].copy()
    lookup = {str(row["diagnostic_name"]): row["diagnostic_value"] for _, row in diagnostics.iterrows()}
    assert int(float(lookup["observations"])) == 22939
    assert int(float(lookup["districts"])) == 249
    assert int(float(lookup["outcome_y1"])) == 16811
    assert int(float(lookup["outcome_y0"])) == 6128
    assert int(float(lookup["model_columns"])) == 31


def test_presentation_export_selectors_resolve_expected_rq3_shapes() -> None:
    expected_rows = {
        "rq3_four_state_correspondence": 20,
        "rq3_district_mismatch": 260,
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


def test_district_mismatch_renderer_uses_governed_249_supported_districts() -> None:
    spec, context, source = _context_and_source("rq3_district_mismatch")
    assert source.frame is not None
    frame = source.frame
    assert len(frame) == 260
    assert frame.loc[~frame["support_status"].eq("excluded"), "unit_id"].nunique() == 249
    valid = frame.loc[~frame["support_status"].eq("excluded")].copy()
    assert valid["value"].between(0.0, 1.0, inclusive="both").all()
    rendered = render_rq1_district_choropleth(frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")


def test_focal_effect_source_exactly_matches_governed_s5_coefficients() -> None:
    spec, _context, source = _context_and_source("rq3_focal_effects")
    assert source.frame is not None
    frame = source.frame.copy()
    assert tuple(frame["term"].astype(str)) == tuple(EXPECTED_FOCAL)
    s5 = pd.read_csv(S5)
    coeff = s5.loc[s5["record_type"].eq("coefficient") & s5["term_role"].eq("focal_predictor")].copy()
    assert len(coeff) == 2
    for row in coeff.itertuples(index=False):
        label = "VIIRS detection count (per doubling)" if row.term == "log2_viirs_det_primary" else "Mean FRP (per doubling)"
        expected = EXPECTED_FOCAL[label]
        assert float(row.beta) == pytest.approx(expected["beta"], abs=1e-15)
        assert float(row.corrected_se) == pytest.approx(expected["corrected_se"], abs=1e-15)
        assert float(row.adjusted_or) == pytest.approx(expected["adjusted_or"], abs=1e-15)
        assert float(row.or_lower_95) == pytest.approx(expected["or_lower_95"], abs=1e-15)
        assert float(row.or_upper_95) == pytest.approx(expected["or_upper_95"], abs=1e-15)
        assert float(row.p) == pytest.approx(expected["p"], abs=1e-15)
    for row in frame.itertuples(index=False):
        expected = EXPECTED_FOCAL[str(row.term)]
        assert float(row.adjusted_or) == pytest.approx(expected["adjusted_or"], abs=1e-15)
        assert float(row.or_lower_95) == pytest.approx(expected["or_lower_95"], abs=1e-15)
        assert float(row.or_upper_95) == pytest.approx(expected["or_upper_95"], abs=1e-15)
        assert float(row.p) == pytest.approx(expected["p"], abs=1e-15)


def test_focal_effect_renderer_returns_valid_configured_png_pdf() -> None:
    spec, context, source = _context_and_source("rq3_focal_effects")
    assert source.frame is not None
    rendered = render_rq3_focal_effects(source.frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")


def test_standardised_probability_source_exact_values_and_population() -> None:
    _spec, _context, source = _context_and_source("rq3_standardised_probabilities")
    assert source.frame is not None
    frame = source.frame.copy()
    assert len(frame) == 4
    assert frame["n"].eq(22939).all()
    assert frame["districts"].eq(249).all()
    grouped = {}
    for predictor_id, group in frame.groupby("predictor_id", sort=False, observed=True):
        grouped[str(predictor_id)] = {
            float(row.quantile): {
                "raw_quantile_value": float(row.raw_quantile_value),
                "standardised_probability": float(row.standardised_probability),
            }
            for row in group.itertuples(index=False)
        }
    assert tuple(grouped) == tuple(EXPECTED_STANDARDISED)
    for predictor_id, expected in EXPECTED_STANDARDISED.items():
        for quantile, values in expected.items():
            observed = grouped[predictor_id][quantile]
            assert observed["raw_quantile_value"] == pytest.approx(values["raw_quantile_value"], abs=1e-12)
            assert observed["standardised_probability"] == pytest.approx(values["standardised_probability"], abs=1e-15)


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
