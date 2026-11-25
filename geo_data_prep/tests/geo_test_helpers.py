"""Synthetic polygon inputs with analytically known intersection areas."""
from pathlib import Path
import geopandas as gpd
from shapely.geometry import box

CRS = "EPSG:32630"


def polygon(x0, y0, x1, y1):
    return box(500000 + x0, 1000000 + y0, 500000 + x1, 1000000 + y1)


def write_layer(path: Path, attributes, geometries, crs=CRS):
    frame = gpd.GeoDataFrame(attributes, geometry=geometries, crs=crs)
    frame.to_file(path, driver="GPKG", index=False)
    return path


