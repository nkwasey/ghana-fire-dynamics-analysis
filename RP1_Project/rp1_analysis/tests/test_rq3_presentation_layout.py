"""Self-contained layout checks: source-only releases need no scientific run."""
from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path
import re
from types import SimpleNamespace

import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfFile, RendererPdf
from matplotlib.colors import to_rgba
from matplotlib.text import Text
import numpy as np
import pandas as pd
from PIL import Image
import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.figures import FigureRenderError
from rp1_analysis_v1.presentation import get_presentation_export_spec
import rp1_analysis_v1.presentation_export as pe
import rp1_analysis_v1.presentation_rq3 as rq3


ROOT = Path(__file__).resolve().parents[1]
STATES = (
    "both_zero", "mcd64a1_positive_viirs_zero",
    "viirs_positive_mcd64a1_zero", "both_positive",
)


def _context(export_id):
    bundle = load_configuration_bundle(ROOT / "config")
    spec = get_presentation_export_spec(export_id, bundle.figure)
    context = SimpleNamespace(
        bundle=bundle, registry=bundle.figure.presentation_export,
        run=SimpleNamespace(publication_run=Path("unused-synthetic-source")),
        style=pe._presentation_style(bundle, spec),
    )
    return spec, context


def _artist(fig, gid):
    return next(obj for obj in fig.findobj() if obj.get_gid() == gid)


def _inside(inner, outer, tolerance=0.05):
    assert inner.x0 >= outer.x0 - tolerance
    assert inner.y0 >= outer.y0 - tolerance
    assert inner.x1 <= outer.x1 + tolerance
    assert inner.y1 <= outer.y1 + tolerance


def _check_both_backends(fig, style, check):
    fig.canvas.draw()
    check(fig.canvas.get_renderer())
    # PDF uses point-space font metrics, which differ slightly from Agg's
    # raster measurements.  Check the realised text against both canvases.
    dpi = fig.dpi
    pdf = PdfFile(BytesIO())
    width, height = fig.get_size_inches()
    pdf.newPage(width, height)
    renderer = RendererPdf(pdf, style.dpi, height, width)
    try:
        fig.set_dpi(72)
        fig.draw(renderer)
        check(renderer)
    finally:
        pdf.finalize()
        pdf.close()
        fig.set_dpi(dpi)


def _valid_export(rendered, style):
    with Image.open(BytesIO(rendered.png)) as image:
        assert image.size == (
            round(rendered.width_in * style.dpi),
            round(rendered.height_in * style.dpi),
        )
    assert rendered.pdf.startswith(b"%PDF")
    media = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", rendered.pdf)
    assert media is not None
    assert float(media[1]) == pytest.approx(rendered.width_in * 72)
    assert float(media[2]) == pytest.approx(rendered.height_in * 72)


@pytest.mark.parametrize("magnitude,font_increment", [(1, 0), (10**12, 1.0)])
def test_focal_footer_fits_full_panel_and_clears_axes_for_png_and_pdf(monkeypatch, magnitude, font_increment):
    spec, context = _context("rq3_focal_effects")
    context.style = replace(context.style, tick_font=context.style.tick_font + font_increment)
    y1, y0 = 17 * magnitude, 9 * magnitude
    observations, districts, columns = y1 + y0, 7 * magnitude, 13
    monkeypatch.setattr(rq3, "_overall_model_diagnostics", lambda _context: (observations, districts, y1, y0, columns))
    terms = tuple(spec.category_order["values"])
    source = pd.DataFrame({
        "term": terms, "adjusted_or": [0.45, 0.67],
        "or_lower_95": [0.34, 0.52], "or_upper_95": [0.58, 0.81], "p": [0.0002, 0.003],
    })
    expected = (
        f"Conditional model population: n={observations:,} VIIRS-positive district-months; {districts} districts "
        f"Outcome Y=1 mapped burned-area absence; Y=0 mapped burned-area presence; design columns={columns}"
    )
    export = rq3.export_figure
    checks = []

    def capture(fig, style):
        note = _artist(fig, "rq3-focal-footnote")
        plot = _artist(fig, "rq3-focal-effects-plot")
        labels = _artist(fig, "rq3-focal-effects-labels")
        band = _artist(fig, "rq3-focal-footer-band")
        notes_box = _artist(fig, "rq3-focal-notes-box")
        summary = _artist(fig, "rq3-focal-effects-summary")
        null_reference = _artist(fig, "f5-focal-effect-null")
        estimates = _artist(fig, "f5-focal-effect-estimates")
        assert " ".join(note.get_text().split()) == expected
        assert fig._suptitle.get_text() == spec.label
        assert notes_box.get_facecolor() == to_rgba("#eeeeee")
        assert list(null_reference.get_xdata()) == [1.0, 1.0]
        assert null_reference.get_color() == "#777777"
        assert null_reference.get_linestyle() == "--"
        assert estimates.get_color() == "#30343B"
        assert labels.get_position().y0 == pytest.approx(plot.get_position().y0)
        assert labels.get_position().height == pytest.approx(plot.get_position().height)
        assert summary.get_position().y0 == pytest.approx(plot.get_position().y0)
        assert summary.get_position().height == pytest.approx(plot.get_position().height)
        assert summary.get_ylim() == pytest.approx(plot.get_ylim())

        def check(renderer):
            canvas = fig.get_window_extent(renderer)
            box = note.get_window_extent(renderer)
            _inside(box, canvas)
            _inside(box, band.get_window_extent(renderer))
            _inside(box, notes_box.get_window_extent(renderer))
            assert box.x0 < plot.get_window_extent(renderer).x0
            assert plot.xaxis.label.get_window_extent(renderer).y0 > band.get_window_extent(renderer).y1
            assert box.y1 < plot.xaxis.label.get_window_extent(renderer).y0
            for index in range(2):
                value = _artist(fig, f"rq3-focal-stat-{index}")
                effect = _artist(fig, f"f5-effect-label-{index}")
                assert value.get_position()[1] == effect.get_position()[1] == index
                value_box = value.get_window_extent(renderer)
                _inside(value_box, summary.get_window_extent(renderer))
                assert value_box.x0 > plot.get_window_extent(renderer).x1
                assert not value_box.overlaps(null_reference.get_window_extent(renderer))
                _inside(effect.get_window_extent(renderer), labels.get_window_extent(renderer))
            checks.append(type(renderer).__name__)

        _check_both_backends(fig, style, check)
        return export(fig, style)

    monkeypatch.setattr(rq3, "export_figure", capture)
    rendered = rq3.render_rq3_focal_effects(source, spec=spec, context=context)
    _valid_export(rendered, context.style)
    assert checks == ["RendererAgg", "RendererPdf"]


def test_four_state_summary_is_lower_right_translucent_and_legend_centered_below(monkeypatch):
    spec, context = _context("rq3_four_state_correspondence")
    by_zone = np.array([[7, 1, 4, 5], [2, 1, 8, 3], [4, 2, 1, 6], [5, 1, 3, 2], [3, 2, 7, 4]])
    totals = dict(zip(STATES, by_zone.sum(axis=0).tolist(), strict=True))
    source = pd.DataFrame([
        {"parent_code": code, "unit_name": f"Zone {code}", "state": state,
         "proportion": count / sum(counts)}
        for code, counts in zip(("CZ", "FZ", "GS", "SS", "TZ"), by_zone, strict=True)
        for state, count in zip(STATES, counts, strict=True)
    ])
    monkeypatch.setattr(rq3, "_overall_four_state_counts", lambda _context: totals)
    export = rq3.export_figure
    checks = []

    def capture(fig, style):
        plot = _artist(fig, "rq3-four-state-plot")
        band = _artist(fig, "rq3-four-state-band")
        note = _artist(fig, "rq3-four-state-counts")
        legend = _artist(fig, "f5-state-legend")
        assert note.get_ha() == "right" and note.get_va() == "bottom"
        assert 0 < note.get_bbox_patch().get_alpha() < 1
        for count in totals.values():
            assert f"{count:,}" in note.get_text()
        assert f"n={sum(totals.values()):,}" in note.get_text()
        assert [item.get_text() for item in legend.get_texts()] == list(rq3._f5_state_aliases(context).values())
        expected = (
            ("#D9D9D9", None), ("#E69F00", "//"), ("#0072B2", None), ("#AD80BD", ".."),
        )
        for container, key, (colour, hatch) in zip(plot.containers, legend.legend_handles, expected, strict=True):
            for patch in (*container.patches, key):
                assert patch.get_facecolor() == to_rgba(colour)
                assert patch.get_edgecolor() == to_rgba("#3F3F3F")
                assert patch.get_hatch() == hatch

        def check(renderer):
            plot_box = plot.get_window_extent(renderer)
            note_box = note.get_bbox_patch().get_window_extent(renderer)
            legend_box = legend.get_window_extent(renderer)
            _inside(note_box, plot_box)
            _inside(legend_box, band.get_window_extent(renderer))
            assert note_box.x1 > plot_box.x0 + 0.9 * plot_box.width
            assert note_box.y0 < plot_box.y0 + 0.1 * plot_box.height
            assert (legend_box.x0 + legend_box.x1) / 2 == pytest.approx((plot_box.x0 + plot_box.x1) / 2, abs=0.1)
            assert legend_box.y1 < plot.xaxis.label.get_window_extent(renderer).y0
            checks.append(type(renderer).__name__)

        _check_both_backends(fig, style, check)
        return export(fig, style)

    monkeypatch.setattr(rq3, "export_figure", capture)
    rendered = rq3.render_rq3_four_state_correspondence(source, spec=spec, context=context)
    _valid_export(rendered, context.style)
    assert checks == ["RendererAgg", "RendererPdf"]


def test_annotation_rejects_a_word_that_cannot_fit_instead_of_cropping():
    fig = plt.figure()
    try:
        note = fig.text(0.1, 0.1, "a_long_unbreakable_annotation_token")
        with pytest.raises(FigureRenderError, match="word wider"):
            rq3._wrap_measured_text(note, width_px=1.0)
    finally:
        plt.close(fig)
