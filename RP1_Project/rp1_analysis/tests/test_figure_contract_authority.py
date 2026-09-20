from __future__ import annotations

from pathlib import Path
import pytest

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.presentation import load_figure_specs
from rp1_analysis_v1.style import PublicationStyle, panel_label

SUBPROJECT = Path(__file__).resolve().parents[1]
CONFIG = SUBPROJECT / "config"


def test_current_publication_output_counts_and_roles_are_config_owned() -> None:
    bundle = load_configuration_bundle(CONFIG)
    main_tables = [x for x in bundle.output.tables if x.role == "manuscript"]
    supplements = [x for x in bundle.output.tables if x.role == "supplementary"]
    main_figures = [x for x in bundle.figure.figures if x.role == "manuscript"]
    assert [x.output_id for x in main_tables] == ["T1", "T2", "T3"]
    assert [x.output_id for x in supplements] == [f"S{i}" for i in range(1, 7)]
    assert [x.figure_id for x in main_figures] == ["F2", "F3", "F4", "F5", "F6"]
    assert len(load_figure_specs(bundle.figure)) == 6
    assert [x.figure_id for x in bundle.figure.figures if x.role == "supplementary"] == ["S1"]
    assert "F1" not in {x.figure_id for x in bundle.figure.figures}


def test_publication_format_and_map_policy_are_exactly_loaded_from_contract() -> None:
    bundle = load_configuration_bundle(CONFIG)
    style = PublicationStyle.from_contract(bundle.figure)
    assert tuple(bundle.figure.formats["raster"]) == ("png",)
    assert tuple(bundle.figure.formats["vector"]) == ("pdf",)
    assert style.map.north_arrow.position == "upper_right"
    assert style.map.scale_bar.position == "lower_right"
    assert style.map.scale_bar.length_km == pytest.approx(100.0)
    assert style.map.scale_bar.label == "100 km"
    assert style.map.colorbar.position == "below"
    assert style.map.colorbar.orientation == "horizontal"
    assert style.map.colorbar.label_required is True
    assert style.map.legend_position == "below"
    assert style.map.embedded_notes is False
    assert style.title_inside_figure is False


def test_final_rectangular_figure_architecture_is_exact() -> None:
    bundle = load_configuration_bundle(CONFIG)
    style = PublicationStyle.from_contract(bundle.figure)
    by_id = {x.figure_id: x for x in bundle.figure.figures}
    assert style.panels.orientation == "grid"
    assert panel_label(0) == "(a)" and panel_label(1) == "(b)" and panel_label(2) == "(c)"
    assert by_id["F2"].layout_role == "rectangular_one_by_two" and by_id["F2"].panel_count == 2
    assert tuple(by_id["F2"].data_builder_options["panel_order"]) == ("direct_acz_long_run_rate", "district_long_run_rate")
    assert by_id["F3"].layout_role == "rectangular_top_span_two_bottom" and by_id["F3"].panel_count == 3
    assert by_id["F4"].layout_role == "rectangular_three_by_two_with_key" and by_id["F4"].panel_count == 5
    assert tuple(by_id["F4"].renderer_options["panel_order"]) == (
        "COASTAL ZONE", "FOREST ZONE", "GUINEA SAVANNAH", "SUDAN SAVANNAH", "TRANSITION ZONE"
    )
    assert len(bundle.figure.grid_layouts[by_id["F4"].layout_role].data_cells) == 5
    assert [c.auxiliary_id for c in bundle.figure.grid_layouts[by_id["F4"].layout_role].auxiliary_cells] == ["shared_graphical_key"]
    assert by_id["F5"].layout_role == "rectangular_left_span_two_right" and by_id["F5"].panel_count == 3
    assert tuple(by_id["F5"].data_builder_options["panel_order"]) == ("mismatch_geography", "four_state_correspondence", "focal_adjusted_associations")
    assert by_id["F6"].layout_role == "rectangular_one_by_two" and by_id["F6"].panel_count == 2
    assert by_id["F6"].source_attribute == "cluster_recurrence_source"
    assert by_id["F6"].renderer == "cluster_recurrence_maps_grid"
    assert by_id["F6"].data_builder == "source_frame"
    assert by_id["F6"].renderer_options["cmap"] == "cividis"
    assert by_id["F6"].renderer_options["value_column"] == "significant_cluster_count"
    assert by_id["F6"].renderer_options["shared_colorbar"] is True
    assert by_id["F6"].renderer_options["colorbar_labelpad_pt"] == pytest.approx(2.0)
    assert by_id["F6"].evidence_class == "DESCRIPTIVE"
    assert by_id["S1"].layout_role == "supplementary_wide_top_two_bottom" and by_id["S1"].panel_count == 3
    for spec in by_id.values():
        assert style.dimensions_for(spec.layout_role) == pytest.approx((20/2.54, 15/2.54))
    assert style.raster_pixels_for_physical_role("rectangular_landscape_20x15_cm") == (2362, 1772)


def test_continuous_map_colorbar_labels_are_scientific_not_generic() -> None:
    bundle = load_configuration_bundle(CONFIG)
    by_id = {x.figure_id: x for x in bundle.figure.figures}
    f2 = tuple(by_id["F2"].renderer_options["panel_colorbar_labels"])
    assert all(x and str(x).casefold() != "value" for x in f2)
    f3 = tuple(by_id["F3"].renderer_options["panel_colorbar_labels"])
    assert f3[1] and str(f3[1]).casefold() != "value"
    f5 = tuple(by_id["F5"].renderer_options["panel_colorbar_labels"])
    assert f5[0] and str(f5[0]).casefold() != "value"


def test_figure_source_data_policy_is_mandatory_and_deterministic() -> None:
    bundle = load_configuration_bundle(CONFIG)
    policy = bundle.figure.source_data_policy
    assert policy["required_for_manuscript_figures"] is True
    assert policy["format"] == "csv"
    assert policy["deterministic_filenames"] is True
    for spec in load_figure_specs(bundle.figure):
        assert spec.figure_data_identity == f"FD_{spec.figure_id}.csv"
        assert spec.source_attribute
        assert spec.required_columns
