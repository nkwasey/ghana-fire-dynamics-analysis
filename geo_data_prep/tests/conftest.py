"""Synthetic polygon inputs with analytically known intersection areas."""
from pathlib import Path
import geopandas as gpd
import pytest
from shapely.geometry import box

CRS = "EPSG:32630"


def polygon(x0, y0, x1, y1):
    return box(500000 + x0, 1000000 + y0, 500000 + x1, 1000000 + y1)


def write_layer(path: Path, attributes, geometries, crs=CRS):
    frame = gpd.GeoDataFrame(attributes, geometry=geometries, crs=crs)
    frame.to_file(path, driver="GPKG", index=False)
    return path


@pytest.fixture
def synthetic_inputs(tmp_path):
    """Two whole districts; first has a 75/25 reference-zone split."""
    root = tmp_path / "project"
    root.mkdir()
    district_path = write_layer(
        root / "districts.gpkg",
        {"district_id": ["d1", "d2"], "district_name": ["One", "Two"]},
        [polygon(0, 0, 4000, 1000), polygon(4000, 0, 8000, 1000)],
    )
    zone_path = write_layer(
        root / "zones.gpkg",
        {"zone_id": ["a", "b"], "zone_name": ["Zone A", "Zone B"], "zone_code": ["A", "B"]},
        [polygon(0, 0, 3000, 1000), polygon(3000, 0, 8000, 1000)],
    )
    return root, district_path, zone_path
