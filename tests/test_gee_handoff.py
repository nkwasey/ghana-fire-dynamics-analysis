"""Local GEE upload packaging uses the selected geography and projected hierarchy."""
import importlib.util
import json
from pathlib import Path
import sys
import warnings
from zipfile import ZipFile

import geopandas as gpd
import pandas as pd
import pytest
import yaml
from shapely.geometry import box

from geo_data_prep.pipeline import run

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec = importlib.util.spec_from_file_location('stage_gee_handoff', TOOLS / 'stage_gee_handoff.py')
gee = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gee)


def make_run(root, *, national=True, analysis='EPSG:32630'):
    (root / 'raw').mkdir(parents=True)
    (root / 'configs').mkdir()
    geometry = [box(450000 + i * 1000, 900000, 451000 + i * 1000, 901000) for i in range(5)]
    districts = gpd.GeoDataFrame({'district_id': [f'd{i}' for i in range(5)],
                                 'district_name': [f'District {i}' for i in range(5)]},
                                geometry=geometry, crs=32630).to_crs(4326)
    zones = gpd.GeoDataFrame({'zone_id': list(gee.ZONES), 'zone_name': list(gee.ZONES),
                             'zone_code': ['CZ', 'FZ', 'GS', 'SS', 'TZ']},
                            geometry=geometry, crs=32630).to_crs(4326)
    districts.to_file(root / 'raw/districts.gpkg', driver='GPKG', index=False)
    zones.to_file(root / 'raw/zones.gpkg', driver='GPKG', index=False)
    inputs = {'districts': {'path': 'raw/districts.gpkg', 'id_field': 'district_id', 'name_field': 'district_name'},
              'zones': {'path': 'raw/zones.gpkg', 'id_field': 'zone_id', 'name_field': 'zone_name', 'code_field': 'zone_code'}}
    if national:
        gpd.GeoDataFrame({'name': ['national']}, geometry=[box(450000, 900000, 455000, 901000)],
                         crs=32630).to_crs(4326).to_file(root / 'raw/national.gpkg', driver='GPKG', index=False)
        inputs['national'] = {'path': 'raw/national.gpkg'}
    config = {'project_root': '..', 'inputs': inputs,
              'crs': {'working': 'EPSG:32630', 'area': 'EPSG:32630', 'output': 'EPSG:4326', 'analysis': analysis},
              'outputs': {'root': 'out', 'plots': False, 'splits': False}}
    path = root / 'configs/geo.yaml'
    path.write_text(yaml.safe_dump(config), encoding='utf-8')
    return run(path, 'example'), path


@pytest.fixture
def source(tmp_path):
    return make_run(tmp_path / 'geography')


def test_bundle_has_three_combined_c3_layers_and_complete_upload_zips(source, tmp_path):
    source_run, config = source
    national_bytes = (config.parent.parent / 'raw/national.gpkg').read_bytes()
    result = gee.build(source_run, tmp_path / 'gee', config)
    assert result['crs'] == 'EPSG:32630' and result['run_id'] == 'example'
    assert result['national_relative_path'] == 'layers/gha_admin0/gha_admin0.shp'
    assert result['schema'] == 'rp1-gee-c3-upload-bundle-v2'
    assert len(result['layers']) == 3
    assert {item['c3_setting'] for item in result['layers']} == {'C3.ghanaAsset', 'C3.zoneAsset', 'C3.districtAsset'}
    assert gee.verify(tmp_path / 'gee') == result
    for item in result['layers']:
        frame = gpd.read_file(tmp_path / 'gee' / item['shapefile'])
        assert frame.crs.to_epsg() == 32630
        with ZipFile(tmp_path / 'gee' / item['upload_zip']) as archive:
            assert len(archive.namelist()) == 5
            assert set(Path(x).suffix for x in archive.namelist()) == set(gee.geo.EXTENSIONS)
    assert (config.parent.parent / 'raw/national.gpkg').read_bytes() == national_bytes
    assert (source_run / 'boundaries/districts_within_acz.shp').is_file()
    assert not (source_run / 'splits').exists()
    assert not list((tmp_path / 'gee/layers').glob('*__zone_*'))
    with pytest.raises(ValueError, match='already exists'):
        gee.build(source_run, tmp_path / 'gee', config)


def test_national_datetime_fields_are_explicitly_preserved_as_iso_text(tmp_path):
    frame = gpd.GeoDataFrame(
        {'valid_on': pd.to_datetime(['2021-03-08T12:34:56.123', None]),
         'valid_to': pd.to_datetime([None, '2023-01-02T03:04:05'])},
        geometry=[box(450000, 900000, 451000, 901000),
                  box(451000, 900000, 452000, 901000)], crs=32630,
    )
    with warnings.catch_warnings():
        warnings.filterwarnings('error', message='Field .* created as String field')
        gee._write_layer(frame, tmp_path, 'national')
    restored = gpd.read_file(tmp_path / 'layers/national/national.shp')
    assert restored['valid_on'].tolist() == ['2021-03-08T12:34:56.123000', None]
    assert restored['valid_to'].tolist() == [None, '2023-01-02T03:04:05']


def test_changed_national_input_is_rejected(source, tmp_path):
    source_run, config = source
    path = config.parent.parent / 'raw/national.gpkg'
    frame = gpd.read_file(path)
    frame['name'] = ['changed']
    path.unlink()
    frame.to_file(path, driver='GPKG', index=False)
    with pytest.raises(ValueError, match='National AOI differs'):
        gee.build(source_run, tmp_path / 'gee', config)
    assert not (tmp_path / 'gee').exists()


def test_missing_national_input_is_actionable(tmp_path):
    source_run, config = make_run(tmp_path / 'source', national=False)
    with pytest.raises(ValueError, match='national AOI is required'):
        gee.build(source_run, tmp_path / 'gee', config)


def test_wrong_analysis_crs_is_rejected(tmp_path):
    source_run, config = make_run(tmp_path / 'source', analysis='EPSG:32631')
    with pytest.raises(ValueError, match='requires Stage 1 analysis CRS EPSG:32630'):
        gee.build(source_run, tmp_path / 'gee', config)


def test_incomplete_or_inconsistent_zip_is_rejected(source, tmp_path):
    source_run, config = source
    folder = tmp_path / 'gee'
    result = gee.build(source_run, folder, config)
    layer = result['layers'][-1]
    with ZipFile(folder / layer['upload_zip'], 'w') as archive:
        archive.writestr('wrong.shp', b'wrong')
    with pytest.raises(ValueError, match='invalid upload ZIP'):
        gee.verify(folder)


def test_missing_component_is_rejected(source, tmp_path):
    source_run, config = source
    folder = tmp_path / 'gee'
    gee.build(source_run, folder, config)
    (folder / 'layers/gha_admin0/gha_admin0.prj').unlink()
    with pytest.raises(ValueError, match='Missing or symlinked file'):
        gee.verify(folder)


def rewrite_layer_and_zip(folder, record, frame):
    path = folder / record['shapefile']
    frame.to_file(path, driver='ESRI Shapefile', encoding='UTF-8', index=False)
    with ZipFile(folder / record['upload_zip'], 'w') as archive:
        for ext in gee.geo.EXTENSIONS:
            member = path.with_suffix(ext)
            archive.write(member, arcname=member.name)


def test_missing_identity_field_is_rejected(source, tmp_path):
    source_run, config = source
    folder = tmp_path / 'gee'
    result = gee.build(source_run, folder, config)
    record = next(item for item in result['layers'] if item['role'] == 'districts')
    frame = gpd.read_file(folder / record['shapefile']).drop(columns='dist_id')
    rewrite_layer_and_zip(folder, record, frame)
    with pytest.raises(ValueError, match='Districts lack identity fields'):
        gee.verify(folder)


def test_inconsistent_combined_parent_membership_is_rejected(source, tmp_path):
    source_run, config = source
    folder = tmp_path / 'gee'
    result = gee.build(source_run, folder, config)
    record = result['layers'][-1]
    frame = gpd.read_file(folder / record['shapefile'])
    frame.loc[0, 'zone_id'] = 'forest_zone'
    rewrite_layer_and_zip(folder, record, frame)
    with pytest.raises(ValueError, match='District IDs or parents are inconsistent|district parent attributes differ|zone differs from district union'):
        gee.verify(folder)


def test_old_thirteen_layer_schema_cannot_be_reused(source, tmp_path):
    source_run, config = source
    folder = tmp_path / 'gee'
    gee.build(source_run, folder, config)
    path = folder / 'gee_upload_manifest.json'
    manifest = json.loads(path.read_text())
    manifest['schema'] = 'rp1-gee-upload-bundle-v1'
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unexpected GEE upload bundle schema'):
        gee.verify(folder)


def test_combined_zone_codes_match_c3_export_contract(source, tmp_path):
    source_run, config = source
    folder = tmp_path / 'gee'
    result = gee.build(source_run, folder, config)
    record = next(item for item in result['layers'] if item['role'] == 'zones')
    frame = gpd.read_file(folder / record['shapefile'])
    frame.loc[0, 'zone_code'] = 'XX'
    rewrite_layer_and_zip(folder, record, frame)
    with pytest.raises(ValueError, match='canonical c3 codes'):
        gee.verify(folder)
