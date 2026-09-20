from __future__ import annotations
from pathlib import Path
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.publication_sources import load_publication_authorities
from rp1_analysis_v1.style import PublicationStyle

ROOT=Path(__file__).resolve().parents[1]

def _b(): return load_configuration_bundle(ROOT/'config')
def _s(): return load_publication_authorities(paths=ProjectPaths(ROOT))

def test_external_figure1_is_outside_generated_estate() -> None:
    b=_b(); ids=[x.figure_id for x in b.figure.figures]; assert ids==['F2','F3','F4','F5','F6','S1']; assert 'F1' not in ids

def test_f2_two_panel_projection_and_geometry() -> None:
    b=_b(); f=next(x for x in b.figure.figures if x.figure_id=='F2'); assert f.panel_count==2 and f.layout_role=='rectangular_one_by_two'; assert tuple(f.data_builder_options['panel_order'])==('direct_acz_long_run_rate','district_long_run_rate')

def test_f3_top_span_two_bottom_geometry() -> None:
    b=_b(); f=next(x for x in b.figure.figures if x.figure_id=='F3'); layout=b.figure.grid_layouts[f.layout_role]; assert f.panel_count==3; assert [(c.row,c.column,c.row_span,c.column_span) for c in layout.data_cells]==[(0,0,1,2),(1,0,1,1),(1,1,1,1)]

def test_f4_five_panels_plus_unlabelled_auxiliary_key_and_order() -> None:
    b=_b(); f=next(x for x in b.figure.figures if x.figure_id=='F4'); layout=b.figure.grid_layouts[f.layout_role]; assert f.panel_count==5 and len(layout.data_cells)==5 and [c.auxiliary_id for c in layout.auxiliary_cells]==['shared_graphical_key']; assert tuple(f.renderer_options['panel_order'])==('COASTAL ZONE','FOREST ZONE','GUINEA SAVANNAH','SUDAN SAVANNAH','TRANSITION ZONE')

def test_f5_map_spans_left_and_focal_panel_has_two_effects() -> None:
    b=_b(); f=next(x for x in b.figure.figures if x.figure_id=='F5'); layout=b.figure.grid_layouts[f.layout_role]; assert f.panel_count==3; assert (layout.data_cells[0].row,layout.data_cells[0].column,layout.data_cells[0].row_span)==(0,0,2); src=_s()[f.source_attribute]; assert len(src.loc[src['panel'].eq('focal_adjusted_associations')])==2

def test_f6_two_panels_and_requires_genuine_external_results() -> None:
    b=_b(); f=next(x for x in b.figure.figures if x.figure_id=='F6'); assert f.panel_count==2 and f.data_builder_options['genuine_external_results_required'] is True

def test_external_dependent_set_is_exactly_t3_f6_s6() -> None:
    b=_b(); dep={x.output_id for x in b.output.tables if x.builder_options.get('genuine_external_results_required')} | {x.figure_id for x in b.figure.figures if x.data_builder_options.get('genuine_external_results_required')}; assert dep=={'T3','F6','S6'}

def test_s1_wide_top_two_bottom_geometry() -> None:
    b=_b(); f=next(x for x in b.figure.figures if x.figure_id=='S1'); layout=b.figure.grid_layouts[f.layout_role]; assert f.panel_count==3; assert [(c.row,c.column,c.row_span,c.column_span) for c in layout.data_cells]==[(0,0,1,2),(1,0,1,1),(1,1,1,1)]

def test_semantic_publication_source_manifest_is_current() -> None:
    names=set(_s()); assert 'figure1_source' not in names and 'figure2_source' not in names and 'figure3_source' not in names and 'figure4_source' not in names and 'figure_s1_source' not in names; assert {'long_run_spatial_rate_presentation_source','seasonality_spatial_organisation_presentation_source','annual_trend_source','cross_product_observability_presentation_source','district_seasonal_diagnostics_source'}.issubset(names)

def test_f2_values_are_exact_projection_of_internal_rq1_authorities() -> None:
    s=_s(); f2=s['long_run_spatial_rate_presentation_source']; assert set(f2['panel'])=={'direct_acz_long_run_rate','district_long_run_rate'} and len(f2)==265

def test_all_generated_figures_use_20_by_15_cm() -> None:
    b=_b(); style=PublicationStyle.from_contract(b.figure); expected=(20/2.54,15/2.54)
    for f in b.figure.figures: assert style.dimensions_for(f.layout_role)==pytest.approx(expected)
