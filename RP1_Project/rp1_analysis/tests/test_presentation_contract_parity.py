from __future__ import annotations
from pathlib import Path
import ast
import pytest
import yaml
from rp1_analysis_v1.config import ConfigurationError, load_figure_contract
from rp1_analysis_v1.grid_rendering import build_grid_figure
from rp1_analysis_v1.style import PublicationStyle

ROOT = Path(__file__).resolve().parents[1]


def test_f4_contract_has_five_data_panels_plus_one_auxiliary_key() -> None:
    contract=load_figure_contract(ROOT/'config/figure_contract.yml')
    style=PublicationStyle.from_contract(contract)
    f4=next(x for x in contract.figures if x.figure_id=='F4')
    layout=contract.grid_layouts[f4.layout_role]
    assert f4.panel_count == len(f4.panel_xlabels) == len(f4.panel_ylabels) == 5
    assert f4.layout_role == 'rectangular_three_by_two_with_key'
    assert [c.panel_index for c in layout.data_cells] == [0,1,2,3,4]
    assert [c.auxiliary_id for c in layout.auxiliary_cells] == ['shared_graphical_key']
    assert style.dimensions_for(f4.layout_role) == pytest.approx((20/2.54,15/2.54))


def test_inconsistent_layout_role_and_panel_count_is_rejected(tmp_path: Path) -> None:
    raw=yaml.safe_load((ROOT/'config/figure_contract.yml').read_text())
    f4=next(x for x in raw['figures'] if x['id']=='F4')
    f4['layout_role']='rectangular_top_span_two_bottom'
    path=tmp_path/'figure_contract.yml'; path.write_text(yaml.safe_dump(raw,sort_keys=False))
    with pytest.raises(ConfigurationError, match='provides 3 data panels'):
        load_figure_contract(path)


def test_grid_builder_consumes_synthetic_dimensions_without_layout_constants() -> None:
    contract=load_figure_contract(ROOT/'config/figure_contract.yml')
    size=(6.4,9.7); grid=build_grid_figure(contract.grid_layouts['rectangular_three_by_two_with_key'],figure_size=size)
    try:
        assert tuple(grid.figure.get_size_inches()) == pytest.approx(size)
        assert len(grid.data_axes)==5 and list(grid.auxiliary_axes)==['shared_graphical_key']
    finally:
        import matplotlib.pyplot as plt; plt.close(grid.figure)


def _function_source(path: Path,name:str)->str:
    text=path.read_text(); tree=ast.parse(text); node=next(n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name==name); return ast.get_source_segment(text,node) or ''


def test_active_multi_panel_renderers_are_grid_driven_and_do_not_reingest_png() -> None:
    publication=(ROOT/'src/rp1_analysis_v1/publication.py').read_text(); figures=(ROOT/'src/rp1_analysis_v1/figures.py').read_text()
    assert 'build_grid_figure' in publication
    assert 'compose_rendered_panels' not in publication
    assert 'mpimg.imread' not in figures and 'matplotlib.image' not in figures
    assert 'plt.subplots(5' not in publication and '11.5' not in publication


def test_cluster_renderer_is_generic_grid_renderer_not_vertical_alias() -> None:
    mapping=ROOT/'src/rp1_analysis_v1/mapping.py'; source=_function_source(mapping,'cluster_maps_grid')
    assert 'build_grid_figure' in source and 'layout.data_cells' in source and 'vertical' not in source.casefold()
    text=mapping.read_text(); assert 'cluster_maps_vertical' not in text and '_build_cluster_maps_vertical_figure' not in text
