from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pytest

from rp1_analysis_v1.grid_rendering import (
    GridRenderError,
    VerticalBandAxes,
    build_vertical_band_axes,
    ensure_vertical_band_xlabel_clearance,
)


def _clearance_px(fig, axes: VerticalBandAxes) -> float:
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    label_box = axes.plot_ax.xaxis.label.get_window_extent(renderer)
    band_box = axes.band_ax.get_window_extent(renderer)
    return float(label_box.y0 - band_box.y1)


def _banded_axes(*, band_fraction: float = 0.15, gap_fraction: float = 0.0):
    fig, ax = plt.subplots(figsize=(4.0, 3.0), dpi=100)
    ax.set_position((0.15, 0.15, 0.75, 0.75))
    banded = build_vertical_band_axes(
        fig,
        ax,
        band_fraction=band_fraction,
        gap_fraction=gap_fraction,
        gid_prefix="clearance-regression",
    )
    banded.plot_ax.set_xlabel("Month")
    return fig, banded


def _force_contact(fig, axes: VerticalBandAxes) -> None:
    """Move only the plot viewport until the rendered boxes are in contact."""

    for _ in range(3):
        clearance = _clearance_px(fig, axes)
        if abs(clearance) <= 1e-9:
            return
        x0, y0, width, height = axes.plot_ax.get_position().bounds
        delta = -clearance / float(fig.bbox.height)
        axes.plot_ax.set_position((x0, y0 + delta, width, height - delta))
    assert _clearance_px(fig, axes) == pytest.approx(0.0, abs=1e-8)


def test_negative_clearance_is_corrected_to_strictly_positive_rendered_clearance() -> None:
    fig, axes = _banded_axes(gap_fraction=0.0)
    try:
        assert _clearance_px(fig, axes) < 0.0
        band_before = axes.band_ax.get_position().bounds
        ensure_vertical_band_xlabel_clearance(fig, axes)
        assert _clearance_px(fig, axes) > 0.0
        assert axes.band_ax.get_position().bounds == pytest.approx(band_before, abs=1e-12)
        assert axes.plot_ax.get_position().height > 0.0
    finally:
        plt.close(fig)


def test_exact_contact_is_corrected_to_strictly_positive_rendered_clearance() -> None:
    fig, axes = _banded_axes(gap_fraction=0.10)
    try:
        _force_contact(fig, axes)
        assert _clearance_px(fig, axes) == pytest.approx(0.0, abs=1e-8)
        ensure_vertical_band_xlabel_clearance(fig, axes)
        assert _clearance_px(fig, axes) > 0.0
    finally:
        plt.close(fig)


def test_already_positive_clearance_does_not_move_plot_viewport() -> None:
    fig, axes = _banded_axes(gap_fraction=0.35)
    try:
        assert _clearance_px(fig, axes) > 0.0
        before = axes.plot_ax.get_position().bounds
        ensure_vertical_band_xlabel_clearance(fig, axes)
        assert axes.plot_ax.get_position().bounds == pytest.approx(before, abs=1e-12)
    finally:
        plt.close(fig)


def test_empty_xlabel_is_safe_no_op() -> None:
    fig, axes = _banded_axes(gap_fraction=0.0)
    try:
        axes.plot_ax.set_xlabel("")
        before = axes.plot_ax.get_position().bounds
        ensure_vertical_band_xlabel_clearance(fig, axes)
        assert axes.plot_ax.get_position().bounds == pytest.approx(before, abs=1e-12)
    finally:
        plt.close(fig)


def test_insufficient_remaining_plot_height_fails_closed() -> None:
    fig, axes = _banded_axes(gap_fraction=0.0)
    try:
        axes.plot_ax.xaxis.labelpad = 1000.0
        assert _clearance_px(fig, axes) < 0.0
        with pytest.raises(GridRenderError, match="no positive plot height"):
            ensure_vertical_band_xlabel_clearance(fig, axes)
    finally:
        plt.close(fig)


def test_repeated_clearance_enforcement_is_position_stable() -> None:
    fig, axes = _banded_axes(gap_fraction=0.0)
    try:
        ensure_vertical_band_xlabel_clearance(fig, axes)
        first = axes.plot_ax.get_position().bounds
        first_clearance = _clearance_px(fig, axes)
        ensure_vertical_band_xlabel_clearance(fig, axes)
        second = axes.plot_ax.get_position().bounds
        assert first_clearance > 0.0
        assert second == pytest.approx(first, abs=1e-12)
        assert _clearance_px(fig, axes) == pytest.approx(first_clearance, abs=1e-8)
    finally:
        plt.close(fig)


@pytest.mark.parametrize(
    ("band_fraction", "gap_fraction"),
    ((0.08, 0.02), (0.12, 0.04), (0.18, 0.06)),
)
def test_generic_vertical_band_consumers_realise_positive_clearance(
    band_fraction: float,
    gap_fraction: float,
) -> None:
    fig, axes = _banded_axes(
        band_fraction=band_fraction,
        gap_fraction=gap_fraction,
    )
    try:
        ensure_vertical_band_xlabel_clearance(fig, axes)
        assert _clearance_px(fig, axes) > 0.0
        assert axes.plot_ax.get_position().height > 0.0
    finally:
        plt.close(fig)
