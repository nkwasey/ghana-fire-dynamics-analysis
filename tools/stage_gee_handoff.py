#!/usr/bin/env python3
"""Package projected Stage 1 boundaries for manual Earth Engine table uploads."""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import shutil
import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

import stage_geo_handoff as geo

CRS = 'EPSG:32630'
SCHEMA = 'rp1-gee-c3-upload-bundle-v2'
ZONES = ('coastal_zone', 'forest_zone', 'guinea_savannah', 'sudan_savannah', 'transition_zone')
ZONE_CODES = dict(zip(ZONES, ('CZ', 'FZ', 'GS', 'SS', 'TZ')))
NATIONAL = 'layers/gha_admin0/gha_admin0.shp'


def _valid_layer(frame, label):
    from pyproj import CRS as Projection
    geo.require(frame.crs is not None and Projection(frame.crs) == Projection(CRS), f'{label}: expected {CRS}')
    geo.require(not frame.empty and frame.geometry.notna().all() and not frame.is_empty.any()
                and frame.is_valid.all(), f'{label}: invalid or empty geometry')
    geo.require(frame.geom_type.isin(['Polygon', 'MultiPolygon']).all(), f'{label}: polygon geometry required')


def _specifications():
    return [('national', 'gha_admin0', None), ('zones', 'acz', None),
            ('districts', 'districts_within_acz', None)]


def _row(role, stem, zone, count):
    return {'role': role, 'zone_id': zone, 'features': count,
            'shapefile': f'layers/{stem}/{stem}.shp', 'upload_zip': f'uploads/{stem}.zip',
            'c3_asset_name': stem,
            'c3_setting': {'national': 'C3.ghanaAsset', 'zones': 'C3.zoneAsset',
                           'districts': 'C3.districtAsset'}[role]}


def _write_layer(frame, root, stem):
    import geopandas as gpd
    import pandas as pd
    path = root / f'layers/{stem}/{stem}.shp'
    path.parent.mkdir(parents=True)
    # Shapefiles do not support datetime fields. Preserve the full timestamp
    # explicitly as ISO 8601 text instead of relying on GDAL's implicit cast.
    serialized = frame.copy()
    datetime_columns = [column for column in frame.columns
                        if pd.api.types.is_datetime64_any_dtype(frame[column].dtype)]
    for column in datetime_columns:
        geo.require(len(column) <= 10, f'{stem}: datetime field name exceeds shapefile limit: {column}')
        serialized[column] = frame[column].map(
            lambda value: None if pd.isna(value) else value.isoformat()
        ).astype(object)
    serialized.to_file(path, driver='ESRI Shapefile', encoding='UTF-8', index=False)
    restored = gpd.read_file(path)
    _valid_layer(restored, stem)
    geo.require(len(restored) == len(frame), f'{stem}: serialization changed feature count')
    for expected, actual in zip(frame.geometry, restored.geometry):
        geo.require(expected.equals(actual), f'{stem}: serialization changed geometry')
    for column in datetime_columns:
        geo.require(column in restored.columns, f'{stem}: datetime field missing after serialization: {column}')
        for expected, actual in zip(serialized[column], restored[column]):
            geo.require((pd.isna(expected) and pd.isna(actual)) or expected == actual,
                        f'{stem}: datetime value changed during serialization: {column}')


def _write_mapping(root, layers):
    with (root / 'asset_name_mapping.csv').open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=['shapefile', 'upload_zip', 'c3_asset_name', 'c3_setting'])
        writer.writeheader()
        for layer in layers:
            writer.writerow({key: layer[key] for key in writer.fieldnames})


def _mapping_rows(layers):
    return [{key: str(layer[key]) for key in ('shapefile', 'upload_zip', 'c3_asset_name', 'c3_setting')}
            for layer in layers]


def verify(bundle_arg):
    """Check the three combined c3 layers and ZIP contents; no remote API access."""
    import geopandas as gpd
    bundle = Path(bundle_arg).resolve(strict=True)
    manifest = geo.read_json(geo.guarded_file(bundle, 'gee_upload_manifest.json'))
    geo.require(manifest.get('schema') == SCHEMA and manifest.get('crs') == CRS,
                'Unexpected GEE upload bundle schema or CRS')
    layers = manifest.get('layers')
    geo.require(isinstance(layers, list) and len(layers) == 3, 'c3 GEE upload bundle must contain exactly three combined layers')
    expected_specs = _specifications()
    frames = {}
    for record, (role, stem, zone) in zip(layers, expected_specs):
        expected = _row(role, stem, zone, record.get('features'))
        geo.require(record == expected, f'Unexpected GEE upload layer mapping: {stem}')
        path = geo.guarded_file(bundle, record['shapefile'])
        parts = [geo.guarded_file(bundle, str(path.relative_to(bundle).with_suffix(ext)).replace('\\', '/'))
                 for ext in geo.EXTENSIONS]
        geo.require(set(path.parent.iterdir()) == set(parts), f'{stem}: unexpected or missing shapefile components')
        frame = gpd.read_file(path)
        _valid_layer(frame, stem)
        geo.require(len(frame) == record['features'], f'{stem}: feature count differs')
        with ZipFile(geo.guarded_file(bundle, record['upload_zip'])) as archive:
            names = [part.name for part in parts]
            geo.require(len(archive.namelist()) == len(names) and set(archive.namelist()) == set(names)
                        and archive.testzip() is None, f'{stem}: invalid upload ZIP')
            geo.require(all(archive.read(part.name) == part.read_bytes() for part in parts), f'{stem}: ZIP content differs from shapefile')
        frames[stem] = frame
    zones, districts = frames['acz'], frames['districts_within_acz']
    geo.require({'zone_id', 'zone_name', 'zone_code'}.issubset(zones.columns), 'Zones lack identity fields')
    geo.require({'dist_id', 'dist_name', 'zone_id', 'zone_name', 'zone_code'}.issubset(districts.columns), 'Districts lack identity fields')
    geo.require(zones.zone_id.is_unique and set(zones.zone_id) == set(ZONES), 'Expected five unique canonical zones')
    geo.require(all(str(row.zone_code) == ZONE_CODES[str(row.zone_id)] for row in zones.itertuples()),
                'Zones do not use the five canonical c3 codes')
    geo.require(districts.dist_id.is_unique and set(districts.zone_id) == set(ZONES), 'District IDs or parents are inconsistent')
    geo.require(len(districts) == manifest.get('district_count') and len(zones) == manifest.get('zone_count'), 'Bundle counts differ')
    for zone in ZONES:
        parent = zones.loc[zones.zone_id == zone].iloc[0]
        selected = districts.loc[districts.zone_id == zone]
        geo.require(selected.zone_code.eq(parent.zone_code).all() and selected.zone_name.eq(parent.zone_name).all(), f'{zone}: district parent attributes differ')
        geo.require(parent.geometry.equals(selected.geometry.union_all()), f'{zone}: zone differs from district union')
    with geo.guarded_file(bundle, 'asset_name_mapping.csv').open(encoding='utf-8', newline='') as stream:
        geo.require(list(csv.DictReader(stream)) == _mapping_rows(layers), 'Asset-name mapping differs from bundle')
    geo.require(manifest.get('national_relative_path') == NATIONAL, 'Unexpected national AOI path')
    return manifest


def build(run_arg, bundle_arg, config_arg):
    """Create a new local upload bundle from one verified Stage 1 run."""
    import geopandas as gpd
    from pyproj import CRS as Projection
    from geo_data_prep.pipeline import load_config, _input_identity, read_layer
    run = Path(run_arg).resolve(strict=True)
    bundle = Path(bundle_arg).absolute()
    geo.require(not bundle.exists() and not bundle.is_symlink(), f'GEE upload bundle already exists: {bundle}')
    geo.require(not bundle.resolve().is_relative_to(run), 'GEE upload bundle cannot be created inside the source run')
    output_manifest = geo.read_json(geo.guarded_file(run, 'outputs_manifest.json'))
    geo.require(output_manifest.get('schema') == 'geo-data-output-manifest-v1', 'Unexpected Stage 1 output manifest')
    for relative, record in output_manifest['files'].items():
        geo.verify_record(geo.guarded_file(run, relative), record)
    evidence = geo.check_identities(run)
    geo.require(output_manifest.get('run_id') == evidence['run_id'], 'Stage 1 run identities differ')
    contract = geo.read_json(geo.guarded_file(run, 'contract/stage1_contract_manifest.json'))
    geo.require(Projection(contract['analysis_handoff']['crs']) == Projection(CRS), f'GEE upload handoff requires Stage 1 analysis CRS {CRS}')
    fingerprint = geo.read_json(geo.guarded_file(run, 'inputs_fingerprint.json'))
    cfg = load_config(config_arg)
    geo.require(cfg['_config_sha256'] == fingerprint.get('config_sha256'), 'GEE handoff configuration differs from the Stage 1 run')
    geo.require('national' in cfg['inputs'] and 'national' in fingerprint, 'Configured national AOI is required for the GEE upload bundle')
    national_identity = _input_identity(cfg, 'national')
    geo.require(national_identity == fingerprint['national'], 'National AOI differs from the Stage 1 input')
    national, _ = read_layer(cfg, 'national')
    national = national.to_crs(CRS)
    _valid_layer(national, 'national AOI')
    zones = gpd.read_file(geo.guarded_file(run, 'analysis_boundaries/acz.shp'))
    districts = gpd.read_file(geo.guarded_file(run, 'analysis_boundaries/districts_within_acz.shp'))
    _valid_layer(zones, 'zones'); _valid_layer(districts, 'districts')
    geo.require(set(zones.zone_id) == set(ZONES), 'GEE scripts require the five canonical zone IDs')
    bundle.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.gee-upload-', dir=bundle.parent))
    try:
        layers = []
        (stage / 'uploads').mkdir()
        for role, stem, zone in _specifications():
            if role == 'national':
                frame = national
                _write_layer(frame, stage, stem)
            else:
                frame = zones if role == 'zones' else districts
                folder = stage / 'layers' / stem
                folder.mkdir(parents=True)
                for ext in geo.EXTENSIONS:
                    shutil.copyfile(geo.guarded_file(run, f'analysis_boundaries/{stem}{ext}'), folder / (stem + ext))
            record = _row(role, stem, zone, len(frame))
            with ZipFile(stage / record['upload_zip'], 'w', ZIP_DEFLATED) as archive:
                for ext in geo.EXTENSIONS:
                    part = stage / f'layers/{stem}/{stem}{ext}'
                    archive.write(part, arcname=part.name)
            layers.append(record)
        manifest = {'schema': SCHEMA, 'run_id': evidence['run_id'], 'crs': CRS,
                    'zone_count': len(zones), 'district_count': len(districts),
                    'national_relative_path': NATIONAL, 'layers': layers}
        (stage / 'gee_upload_manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        _write_mapping(stage, layers)
        (stage / 'README.txt').write_text(
            'Manual Earth Engine boundary upload bundle\n'
            'The three combined shapefiles use EPSG:32630. Upload each uploads/*.zip as a table asset.\n'
            'asset_name_mapping.csv binds asset names to C3.ghanaAsset, C3.zoneAsset and C3.districtAsset.\n'
            'The national layer is the configured Stage 1 national AOI, transformed without clipping or repair.\n'
            'Confirm it is the intended Ghana AOI before setting C3.ghanaAsset.\n'
            'The GEE scripts retain their existing MODIS raster grid and analytical methods.\n'
            'This package does not upload, hash-bind, or verify any remote Earth Engine asset.\n', encoding='utf-8')
        verify(stage)
        geo.require(_input_identity(cfg, 'national') == national_identity, 'National AOI changed during packaging')
        geo.require(not bundle.exists() and not bundle.is_symlink(), f'GEE upload bundle appeared during packaging: {bundle}')
        os.rename(stage, bundle)
        return manifest
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', required=True, help='Completed Stage 1 run directory')
    parser.add_argument('--bundle', required=True, help='New GEE upload bundle directory')
    parser.add_argument('--config', required=True, help='Original geography configuration used for this run')
    args = parser.parse_args()
    try:
        result = build(args.run, args.bundle, args.config)
    except (ValueError, OSError, KeyError) as exc:
        parser.exit(2, f'GEE boundary packaging failed: {exc}\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
