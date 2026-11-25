from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import matplotlib.pyplot as plt
import pandas as pd
import pytest
import yaml
from shapely.geometry import box

from rp1_analysis_v1 import figures, mapping, presentation_rq1, publication
from rp1_analysis_v1.config import ConfigurationError, load_figure_contract
from rp1_analysis_v1.presentation import get_figure_spec, get_presentation_export_spec
from rp1_analysis_v1.style import PublicationStyle


FIGURE_CONTRACT = Path(__file__).resolve().parents[1] / "config/figure_contract.yml"


@pytest.fixture
def rate_maps():
    contract = load_figure_contract(FIGURE_CONTRACT)
    codes = ["CZ", "FZ", "GS", "SS", "TZ"]
    districts = gpd.GeoDataFrame(
        {"dist_id": [f"D{i}" for i in range(5)], "zone_id": [f"Z{i}" for i in range(5)],
         "zone_code": codes, "zone_name": codes},
        geometry=[box(200000, i * 150000, 500000, (i + 1) * 150000) for i in range(5)],
        crs="EPSG:32630",
    )
    zones = districts.drop(columns=["dist_id"]).copy()
    authority = mapping.prepare_geography(districts, zones)
    zonal = pd.DataFrame(
        {"unit_id": zones["zone_id"], "value": [2, 12, 20, 30, 40], "support_status": "valid_nonzero",
         "panel": "direct_acz_long_run_rate"},
    )
    district = pd.DataFrame(
        {"unit_id": districts["dist_id"], "value": [10, 0, 20, 31, 66],
         "support_status": ["valid_nonzero", "valid_zero", "valid_nonzero", "valid_nonzero", "valid_nonzero"],
         "panel": "district_long_run_rate"},
    )
    return contract, authority, zonal, district


def test_f2_notebook_and_standalone_maps_share_one_colour_scale(rate_maps, monkeypatch):
    contract, authority, zonal, district = rate_maps
    style = PublicationStyle.from_contract(contract)
    seen = []
    draw_colorbar = mapping._draw_colorbar_band

    def capture(*args, norm, cmap, ticks, **kwargs):
        seen.append((cmap, (norm.vmin, norm.vmax), tuple(ticks)))
        return draw_colorbar(*args, norm=norm, cmap=cmap, ticks=ticks, **kwargs)

    monkeypatch.setattr(mapping, "_draw_colorbar_band", capture)
    monkeypatch.setattr(figures, "_export", lambda fig, _style: plt.close(fig))
    monkeypatch.setattr(presentation_rq1, "_map_authority", lambda _context: authority)
    context = SimpleNamespace(style=style, bundle=SimpleNamespace(figure=contract))
    authorities = SimpleNamespace(district_geometry=authority.districts, acz_geometry=authority.acz)
    publication._render(
        get_figure_spec("F2", contract), pd.concat([zonal, district]),
        authorities=authorities, style=style,
    )
    for export_id, renderer, frame in [
        ("rq1_acz_long_run_rate", presentation_rq1.render_rq1_acz_long_run_rate, zonal),
        ("rq1_district_long_run_rate", presentation_rq1.render_rq1_district_choropleth, district),
    ]:
        renderer(frame, spec=get_presentation_export_spec(export_id, contract), context=context)

    assert seen == [("cividis_r", (0.0, 70.0), tuple(range(0, 71, 10)))] * 3


def test_fixed_district_scale_rejects_overflow_instead_of_clipping(rate_maps):
    contract, authority, _zonal, district = rate_maps
    district.loc[district["value"].eq(66), "value"] = 71
    fig, ax = plt.subplots()
    try:
        with pytest.raises(mapping.MappingError, match=r"within the declared scale \[0, 70\]"):
            mapping.draw_choropleth_axis(
                fig, ax, authority, district, value="value", colorbar_label="Burned-area rate",
                style=PublicationStyle.from_contract(contract), cmap="cividis_r",
                norm=mapping.bounded_map_norm(70),
            )
    finally:
        plt.close(fig)


@pytest.mark.parametrize(
    ("figure_id", "key", "value", "message"),
    [
        ("F2", "panel_colormaps", ["cividis_r", "viridis"], "same colour map"),
        ("F2", "rate_scale_max", None, "rate_scale_max.*numeric"),
        ("F2", "rate_scale_ticks", [0, 20, 20, 70], "must increase"),
        ("F3", "departure_scale_ticks", [-60, 20, 60], "must mark zero"),
        ("F3", "symmetric_departure_scale", False, "symmetric zero-centred"),
        ("F5", "mismatch_percent_scale", False, "must use a percentage"),
        ("F6", "recurrence_scale_ticks", [0, 12.5, 45], "whole clusters"),
        ("F6", "recurrence_scale_max", float("inf"), "must be finite"),
    ],
)
def test_invalid_shared_map_scales_fail_when_the_contract_is_loaded(tmp_path, figure_id, key, value, message):
    raw = yaml.safe_load(FIGURE_CONTRACT.read_text(encoding="utf-8"))
    options = next(item["renderer_options"] for item in raw["figures"] if item["id"] == figure_id)
    options[key] = value
    path = tmp_path / "figure_contract.yml"
    path.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ConfigurationError, match=message):
        load_figure_contract(path)
