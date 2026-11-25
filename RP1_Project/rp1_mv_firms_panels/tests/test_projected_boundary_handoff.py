"""Boundary representation must preserve assignment away from polygon edges."""
import geopandas as gpd
from shapely.geometry import Point, box

from mv_firms_panels.geo.joins import join_points_to_units


def test_utm_handoff_and_geographic_boundaries_assign_same_detections(tmp_path):
    districts = gpd.GeoDataFrame(
        {'dist_id': ['west', 'east'], 'dist_name': ['West', 'East']},
        geometry=[box(-1.2, 6, -1.0, 6.2), box(-1.0, 6, -.8, 6.2)], crs=4326)
    geographic = tmp_path / 'geographic.shp'
    projected = tmp_path / 'projected.shp'
    districts.to_file(geographic, index=False)
    districts.to_crs(32630).to_file(projected, index=False)
    # Include points close to either side of the shared border and an unmatched
    # detection. Exact edge coincidence is governed by the join tie-break tests.
    points = gpd.GeoDataFrame({'detection_id': range(5)}, geometry=[
        Point(-1.1, 6.1), Point(-.9, 6.1), Point(-1.0001, 6.1),
        Point(-.9999, 6.1), Point(-.7, 6.1)], crs=4326)
    assignments = []
    for path in (geographic, projected):
        result = join_points_to_units(points=points, polygons=gpd.read_file(path),
                                     level='district', unit_id_field='dist_id',
                                     unit_name_field='dist_name')
        assignments.append(result.unit_id.tolist())
    assert assignments[0] == assignments[1] == ['west', 'east', 'west', 'east', None]
