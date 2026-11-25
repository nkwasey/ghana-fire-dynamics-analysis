from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.figures import FigureRenderError
from rp1_analysis_v1.presentation import get_presentation_export_spec
from rp1_analysis_v1.presentation_export import _presentation_style
from rp1_analysis_v1.presentation_rq3 import render_rq3_standardised_probabilities


def test_standardised_probability_render_uses_validated_population_and_exports_png_pdf(monkeypatch):
    root = Path(__file__).resolve().parents[1]
    bundle = load_configuration_bundle(root / "config")
    spec = get_presentation_export_spec("rq3_standardised_probabilities", bundle.figure)
    context = SimpleNamespace(bundle=bundle, style=_presentation_style(bundle, spec))
    frame = pd.DataFrame([
        ("viirs_detection_count", 0.25, 1.0, 0.917, "22939", "249"),
        ("viirs_detection_count", 0.75, 4.0, 0.610, "22939", "249"),
        ("viirs_mean_frp", 0.25, 2.0, 0.25, "22939", "249"),
        ("viirs_mean_frp", 0.75, 8.0, 0.40, "22939", "249"),
    ], columns=["predictor_id", "quantile", "raw_quantile_value", "standardised_probability", "n", "districts"])

    import rp1_analysis_v1.presentation_rq3 as renderer
    real_export = renderer.export_figure
    labels = []

    def capture(fig, style):
        ax, = fig.axes
        labels.extend(text.get_text() for text in ax.texts)
        assert ax.get_title() == spec.label
        fig.canvas.draw()
        canvas_renderer = fig.canvas.get_renderer()
        plot_right = ax.get_window_extent(canvas_renderer).x1
        canvas_right = fig.get_window_extent(canvas_renderer).x1
        text_artists = {label.get_gid(): label for label in ax.texts}
        lines = {line.get_gid(): line for line in ax.lines}
        for predictor in ("viirs_detection_count", "viirs_mean_frp"):
            q25 = lines[f"rq3-std-q25-{predictor}"]
            q75 = lines[f"rq3-std-q75-{predictor}"]
            assert q25.get_marker() == "o"
            assert q25.get_markerfacecolor() == ax.get_facecolor()
            assert q75.get_marker() == "s"
            assert q75.get_markerfacecolor() == "#30343B"
            assert q25.get_color() == q75.get_color() == "#30343B"
            delta = text_artists[f"rq3-std-delta-{predictor}"].get_window_extent(canvas_renderer)
            assert plot_right < delta.x0 < delta.x1 < canvas_right
        return real_export(fig, style)

    monkeypatch.setattr(renderer, "export_figure", capture)
    rendered = render_rq3_standardised_probabilities(frame, spec=spec, context=context)
    assert rendered.png.startswith(b"\x89PNG\r\n\x1a\n")
    assert rendered.pdf.startswith(b"%PDF")
    assert any("n=22,939 VIIRS-positive district-months; 249 districts" in text for text in labels)

    inconsistent = frame.copy()
    inconsistent.loc[0, "districts"] = "248"
    with pytest.raises(FigureRenderError, match="one positive realised district count"):
        render_rq3_standardised_probabilities(inconsistent, spec=spec, context=context)
