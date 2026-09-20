from __future__ import annotations

from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader
import pytest
import yaml

from rp1_analysis_v1.config import ConfigurationError, load_figure_contract
from rp1_analysis_v1.figures import export_figure
from rp1_analysis_v1.grid_rendering import add_panel_labels, build_grid_figure
from rp1_analysis_v1.style import PublicationStyle

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config/figure_contract.yml"


def _mutated(tmp_path: Path, mutate) -> Path:
    raw = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    mutate(raw)
    path = tmp_path / "figure_contract.yml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return path


def test_all_required_generic_grid_shapes_are_configured() -> None:
    contract = load_figure_contract(CONFIG)
    layouts = contract.grid_layouts
    one_two = layouts["rectangular_one_by_two"]
    top = layouts["rectangular_top_span_two_bottom"]
    key = layouts["rectangular_three_by_two_with_key"]
    left = layouts["rectangular_left_span_two_right"]
    supp = layouts["supplementary_wide_top_two_bottom"]
    assert (one_two.rows, one_two.columns, len(one_two.data_cells)) == (1, 2, 2)
    assert top.data_cells[0].column_span == 2
    assert (key.rows, key.columns, len(key.data_cells), len(key.auxiliary_cells)) == (3, 2, 5, 1)
    assert left.data_cells[0].row_span == 2
    assert supp.data_cells[0].column_span == 2


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda raw: raw["grid_layouts"]["rectangular_one_by_two"].__setitem__("rows", 0), "rows and columns must be > 0"),
        (lambda raw: raw["grid_layouts"]["rectangular_one_by_two"].__setitem__("columns", 0), "rows and columns must be > 0"),
        (lambda raw: raw["grid_layouts"]["rectangular_one_by_two"].__setitem__("width_ratios", [1.0]), "width_ratios length"),
        (lambda raw: raw["grid_layouts"]["rectangular_top_span_two_bottom"].__setitem__("height_ratios", [1.0]), "height_ratios length"),
        (lambda raw: raw["grid_layouts"]["rectangular_one_by_two"]["cells"][0].__setitem__("column", -1), "row and column must be >= 0"),
        (lambda raw: raw["grid_layouts"]["rectangular_one_by_two"]["cells"][0].__setitem__("column_span", 3), "outside the configured grid"),
        (lambda raw: raw["grid_layouts"]["rectangular_one_by_two"]["cells"][1].__setitem__("column", 0), "overlaps another configured grid cell"),
        (lambda raw: raw["grid_layouts"]["rectangular_one_by_two"]["cells"][1].__setitem__("panel_index", 0), "duplicates data panel_index"),
    ],
)
def test_malformed_grid_contract_fails_closed(tmp_path: Path, mutate, message: str) -> None:
    with pytest.raises(ConfigurationError, match=message):
        load_figure_contract(_mutated(tmp_path, mutate))


def test_auxiliary_cell_is_not_a_data_panel_and_receives_no_panel_label() -> None:
    contract = load_figure_contract(CONFIG)
    style = PublicationStyle.from_contract(contract)
    layout = contract.grid_layouts["rectangular_three_by_two_with_key"]
    grid = build_grid_figure(layout, figure_size=style.dimensions_for("rectangular_three_by_two_with_key"))
    try:
        assert len(grid.data_axes) == 5
        assert set(grid.auxiliary_axes) == {"shared_graphical_key"}
        add_panel_labels(grid.data_axes, style=style)
        assert sum(
            1 for ax in grid.data_axes for text in ax.texts
            if str(text.get_gid()).startswith("panel-marker-")
        ) == 5
        assert not next(iter(grid.auxiliary_axes.values())).texts
    finally:
        import matplotlib.pyplot as plt
        plt.close(grid.figure)


def test_figure_panel_count_excludes_auxiliary_cells() -> None:
    contract = load_figure_contract(CONFIG)
    f4 = next(x for x in contract.figures if x.figure_id == "F4")
    layout = contract.grid_layouts[f4.layout_role]
    assert f4.panel_count == 5
    assert len(layout.data_cells) == 5
    assert len(layout.auxiliary_cells) == 1
    assert len(layout.data_cells) + len(layout.auxiliary_cells) == 6


def _render_rectangular() -> tuple[bytes, bytes, PublicationStyle]:
    contract = load_figure_contract(CONFIG)
    style = PublicationStyle.from_contract(contract)
    size = style.physical_inches_for("rectangular_landscape_20x15_cm")
    grid = build_grid_figure(contract.grid_layouts["rectangular_one_by_two"], figure_size=size)
    grid.data_axes[0].plot([0.0, 1.0], [0.0, 1.0])
    grid.data_axes[1].plot([0.0, 1.0], [1.0, 0.0])
    rendered = export_figure(grid.figure, style)
    return rendered.png, rendered.pdf, style


def test_exact_physical_page_and_deterministic_raster_rounding() -> None:
    png, pdf, style = _render_rectangular()
    assert style.physical_inches_for("rectangular_landscape_20x15_cm") == pytest.approx((20 / 2.54, 15 / 2.54))
    assert style.raster_pixels_for_physical_role("rectangular_landscape_20x15_cm") == (2362, 1772)
    assert Image.open(BytesIO(png)).size == (2362, 1772)
    page = PdfReader(BytesIO(pdf)).pages[0]
    assert float(page.mediabox.width) / 72 == pytest.approx(20 / 2.54, abs=1e-9)
    assert float(page.mediabox.height) / 72 == pytest.approx(15 / 2.54, abs=1e-9)


def test_portrait_physical_role_is_available_generically() -> None:
    contract = load_figure_contract(CONFIG)
    style = PublicationStyle.from_contract(contract)
    assert style.physical_inches_for("portrait_10x15_cm") == pytest.approx((10 / 2.54, 15 / 2.54))
    assert style.raster_pixels_for_physical_role("portrait_10x15_cm") == (1181, 1772)


def test_two_clean_vector_render_passes_are_deterministic_or_page_equivalent() -> None:
    png_a, pdf_a, _ = _render_rectangular()
    png_b, pdf_b, _ = _render_rectangular()
    assert png_a == png_b
    if pdf_a != pdf_b:
        page_a = PdfReader(BytesIO(pdf_a)).pages[0]
        page_b = PdfReader(BytesIO(pdf_b)).pages[0]
        assert tuple(float(x) for x in page_a.mediabox) == tuple(float(x) for x in page_b.mediabox)
        assert len(page_a.get_contents().get_data()) == len(page_b.get_contents().get_data())


def test_active_composites_do_not_reingest_intermediate_pngs() -> None:
    publication = (ROOT / "src/rp1_analysis_v1/publication.py").read_text(encoding="utf-8")
    figures = (ROOT / "src/rp1_analysis_v1/figures.py").read_text(encoding="utf-8")
    assert "mpimg" not in publication
    assert "imread(" not in publication
    assert "compose_rendered_panels" not in publication
    assert "mpimg" not in figures


def test_generic_grid_module_contains_no_ghana_or_publication_number_authority() -> None:
    source = (ROOT / "src/rp1_analysis_v1/grid_rendering.py").read_text(encoding="utf-8")
    lower = source.casefold()
    assert "ghana" not in lower
    for token in ("F2", "F3", "F4", "F5", "F6", "S1"):
        assert token not in source
