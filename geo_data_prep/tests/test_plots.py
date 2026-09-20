from __future__ import annotations

import os
from pathlib import Path

import geopandas as gpd
import pytest
from geo_data_prep.plots.combined import plot_combined_zones_districts
from geo_data_prep.plots.per_zone import plot_per_zone_maps
from shapely.geometry import Polygon

RUN_NATIVE_PLOT_SMOKE = os.environ.get("RP_RUN_NATIVE_PLOT_SMOKE") == "1"
NATIVE_PLOT_SKIP_REASON = (
    "Set RP_RUN_NATIVE_PLOT_SMOKE=1 to run native GeoPandas/Matplotlib rendering smoke tests."
)


def _square(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)])


def _sample_zone_and_district_frames() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    crs = "EPSG:4326"
    zones = gpd.GeoDataFrame(
        {"zone_id": ["A", "B"], "zone_name": ["Zone A", "Zone B"]},
        geometry=[_square(0, 0, 2, 2), _square(2, 0, 4, 2)],
        crs=crs,
    )
    districts = gpd.GeoDataFrame(
        {"district_id": ["D1", "D2"], "district_name": ["District 1", "District 2"]},
        geometry=[_square(0, 0, 2, 2), _square(2, 0, 4, 2)],
        crs=crs,
    )
    return zones, districts


def _sample_enriched_districts() -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    zones, _ = _sample_zone_and_district_frames()
    districts_enriched = gpd.GeoDataFrame(
        {
            "district_id": ["D1", "D2"],
            "district_name": ["District 1", "District 2"],
            "zone_id": ["A", "B"],
        },
        geometry=[_square(0, 0, 2, 2), _square(2, 0, 4, 2)],
        crs="EPSG:4326",
    )
    return zones, districts_enriched


def _stub_geopandas_plotting(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace GeoPandas native rendering with axis-preserving no-op plotters.

    The plotting contract under test is output orchestration, deterministic file
    writing, and legend/grid/title assembly. Native geometry rendering is kept in
    separate opt-in smoke tests because it can crash some Windows geospatial
    stacks at process level.
    """

    def _fake_plot(self, *args, ax=None, **kwargs):  # type: ignore[no-untyped-def]
        if ax is None:
            import matplotlib.pyplot as plt

            _, ax = plt.subplots()
        return ax

    def _fake_savefig(self, fname, *args, **kwargs):  # type: ignore[no-untyped-def]
        target = Path(str(fname))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"stub-plot-output")

    import matplotlib.figure

    monkeypatch.setattr(gpd.GeoDataFrame, "plot", _fake_plot, raising=True)
    monkeypatch.setattr(gpd.GeoSeries, "plot", _fake_plot, raising=True)
    monkeypatch.setattr(matplotlib.figure.Figure, "savefig", _fake_savefig, raising=True)


def test_plot_combined_contract_creates_png_without_native_geopandas_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_geopandas_plotting(monkeypatch)
    zones, districts = _sample_zone_and_district_frames()

    res = plot_combined_zones_districts(zones, districts, out_dir=tmp_path, title="Combined")

    assert res.png_path.exists()
    assert res.png_path.stat().st_size > 0


def test_plot_per_zone_contract_creates_pngs_without_native_geopandas_render(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_geopandas_plotting(monkeypatch)
    zones, districts_enriched = _sample_enriched_districts()

    outs = plot_per_zone_maps(zones, districts_enriched, out_dir=tmp_path)

    assert len(outs) == 2
    for out in outs:
        assert out.png_path.exists()
        assert out.png_path.stat().st_size > 0


@pytest.mark.native_plot_smoke
@pytest.mark.skipif(not RUN_NATIVE_PLOT_SMOKE, reason=NATIVE_PLOT_SKIP_REASON)
def test_plot_combined_native_smoke_creates_png(tmp_path: Path) -> None:
    zones, districts = _sample_zone_and_district_frames()

    res = plot_combined_zones_districts(zones, districts, out_dir=tmp_path, title="Combined")

    assert res.png_path.exists()
    assert res.png_path.stat().st_size > 1_000


@pytest.mark.native_plot_smoke
@pytest.mark.skipif(not RUN_NATIVE_PLOT_SMOKE, reason=NATIVE_PLOT_SKIP_REASON)
def test_plot_per_zone_native_smoke_creates_one_png_per_zone(tmp_path: Path) -> None:
    zones, districts_enriched = _sample_enriched_districts()

    outs = plot_per_zone_maps(zones, districts_enriched, out_dir=tmp_path)

    assert len(outs) == 2
    for out in outs:
        assert out.png_path.exists()
        assert out.png_path.stat().st_size > 1_000
