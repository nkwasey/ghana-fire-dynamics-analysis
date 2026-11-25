"""Scientific projection checks must hold even when file hashes are refreshed."""
import csv
import io
import json
from pathlib import Path
import struct
from zipfile import ZipFile

import pytest
import shapefile

from ghana_fire_archive import core, exports, semantic
from test_archive import config, fixture_source, row


def _prepared(tmp_path, records=None):
    c = config(tmp_path)
    manifest = core.prepare(c, fixture_source(c, records or [row()]))
    root = Path(c['output'])
    part = manifest['partitions'][0]
    return c, manifest, root, part


def _check(c, root, part, **overrides):
    arguments = dict(csvpath=root / part['path'], zippath=root / part['shapefile_path'],
                     record_count=part['record_count'], source=part['source'], year=part['year'],
                     geography=core.Geography(c['geography']),
                     coverage_start=part['coverage_start'], coverage_end=part['coverage_end'],
                     source_sha256=part['source_sha256'])
    arguments.update(overrides)
    return semantic.verify_partition(**arguments)


def _rewrite_shape(path, *, changes=None, schema_change=None, reverse=False, coordinate_change=None):
    with ZipFile(path) as archive:
        payload = {name: archive.read(name) for name in archive.namelist()}
    stem = next(name[:-4] for name in payload if name.endswith('.shp'))
    with shapefile.Reader(shp=io.BytesIO(payload[stem + '.shp']),
                          shx=io.BytesIO(payload[stem + '.shx']),
                          dbf=io.BytesIO(payload[stem + '.dbf']), encoding='utf-8') as reader:
        fields = [list(field) for field in reader.fields[1:]]
        features = [(list(feature.shape.points[0]), list(feature.record))
                    for feature in reader.iterShapeRecords()]
    if schema_change:
        name, attribute, value = schema_change
        field = next(f for f in fields if f[0] == name)
        field[attribute] = value
    if changes:
        for field_name, value in changes.items():
            index = next(i for i, field in enumerate(fields) if field[0] == field_name)
            for _, record in features:
                record[index] = value
    if coordinate_change:
        features[0][0][:] = coordinate_change
    if reverse:
        features.reverse()
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    writer = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POINT, encoding='utf-8')
    for field in fields:
        writer.field(*field)
    for point, record in features:
        writer.point(*point)
        writer.record(*record)
    writer.close()
    for extension, stream in (('.shp', shp), ('.shx', shx), ('.dbf', dbf)):
        payload[stem + extension] = stream.getvalue()
    core.zip_files(path, payload)


def _refresh_partition_hashes(root, manifest, part):
    part['sha256'] = core.sha(root / part['path'])
    part['shapefile_sha256'] = core.sha(root / part['shapefile_path'])
    core.write_json(root / 'archive-manifest.json', manifest)


def _rewrite_saved_daynight(root, manifest, part, value):
    """Keep identities, DBF attributes and hashes consistent with one changed code."""
    csvpath = root / part['path']
    with csvpath.open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        fields, records = reader.fieldnames, list(reader)
    assert len(records) == 1
    observation = records[0]
    original_id = observation['id']
    observation['daynight'] = value
    observation['id'] = core.observation_id(
        observation['source_product'], observation['platform'], observation['acq_date'],
        observation['time_utc'], observation['latitude'], observation['longitude'], observation)
    with csvpath.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    _rewrite_shape(root / part['shapefile_path'], changes={
        'daynight': value, 'obs_id': observation['id']})
    _refresh_partition_hashes(root, manifest, part)
    assert observation['id'] != original_id
    return observation


def _saved_partition_bytes(root, part):
    return {path: path.read_bytes() for path in (
        root / 'archive-manifest.json', root / part['path'], root / part['shapefile_path'])}


def test_all_attributes_and_geography_reconcile(tmp_path):
    c, _, root, part = _prepared(tmp_path)
    assert _check(c, root, part) == {
        'records': 1, 'attributes_checked': 19, 'spatial_assignment_checked': True}


@pytest.mark.parametrize('daynight', ['D', 'N'])
def test_saved_day_and_night_records_verify_without_mutation(tmp_path, daynight):
    records = [row(daynight=daynight)]
    input_before = [dict(record) for record in records]
    c, _, root, part = _prepared(tmp_path, records)
    before = _saved_partition_bytes(root, part)
    with (root / part['path']).open(encoding='utf-8', newline='') as handle:
        stored = list(csv.DictReader(handle))
    assert stored[0]['daynight'] == daynight
    identifier = stored[0]['id']
    assert _check(c, root, part)['records'] == 1
    assert core.verify(root / 'archive-manifest.json', write_report=False)['passed']
    assert records == input_before
    assert _saved_partition_bytes(root, part) == before
    with (root / part['path']).open(encoding='utf-8', newline='') as handle:
        assert list(csv.DictReader(handle))[0]['id'] == identifier


@pytest.mark.parametrize('daynight', ['X', '', 'd', 'n', '0'])
def test_invalid_saved_daynight_rejected_after_coordinated_rewrite(tmp_path, daynight):
    c, manifest, root, part = _prepared(tmp_path)
    assert core.verify(root / 'archive-manifest.json', write_report=False)['passed']
    observation = _rewrite_saved_daynight(root, manifest, part, daynight)
    before = _saved_partition_bytes(root, part)
    # Each case fits the existing one-character DBF field. Its ID, matching DBF
    # attributes and refreshed hashes cannot account for the expected rejection.
    assert part['sha256'] == core.sha(root / part['path'])
    assert part['shapefile_sha256'] == core.sha(root / part['shapefile_path'])
    with ZipFile(root / part['shapefile_path']) as archive:
        dbf = next(name for name in archive.namelist() if name.endswith('.dbf'))
        with shapefile.Reader(dbf=io.BytesIO(archive.read(dbf)), encoding='utf-8') as reader:
            assert reader.record(0)['daynight'] == daynight
            assert reader.record(0)['obs_id'] == observation['id']
    with pytest.raises(core.ArchiveError, match='daynight'):
        core.verify(root / 'archive-manifest.json', write_report=False)
    with pytest.raises(core.ArchiveError, match='daynight'):
        _check(c, root, part)
    assert _saved_partition_bytes(root, part) == before
    with (root / part['path']).open(encoding='utf-8', newline='') as handle:
        assert list(csv.DictReader(handle)) == [observation]


@pytest.mark.parametrize('field,value', [('frp_mw', 900), ('confidence', 'low'),
                                        ('acq_date', '2024-01-02'), ('fire_type', '2')])
def test_wrong_dbf_scientific_attribute_rejected_after_hash_refresh(tmp_path, field, value):
    c, manifest, root, part = _prepared(tmp_path)
    _rewrite_shape(root / part['shapefile_path'], changes={field: value})
    _refresh_partition_hashes(root, manifest, part)
    with pytest.raises(core.ArchiveError, match='scientific attribute mismatch'):
        _check(c, root, part)
    # The public archive verifier must invoke the same semantic contract.
    with pytest.raises(core.ArchiveError, match='scientific attribute mismatch'):
        core.verify(root / 'archive-manifest.json', write_report=False)


def test_valid_but_wrong_district_and_zone_rejected_after_hash_refresh(tmp_path):
    c, manifest, root, part = _prepared(tmp_path)
    csvpath = root / part['path']
    with csvpath.open(encoding='utf-8', newline='') as handle:
        reader = csv.DictReader(handle)
        fields, records = reader.fieldnames, list(reader)
    original_id = records[0]['id']
    units = json.loads((Path(c['geography']) / 'units.json').read_text())
    replacement = next(item for item in units['districts']
                       if item['district_id'] == 'D2')
    records[0].update(district_id=replacement['district_id'], zone_id=replacement['zone_id'])
    with csvpath.open('w', encoding='utf-8', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator='\n')
        writer.writeheader()
        writer.writerows(records)
    assert records[0]['id'] == original_id  # Membership is not an observation-ID component.
    _rewrite_shape(root / part['shapefile_path'], changes={
        'district': replacement['district_id'], 'zone': replacement['zone_id']})
    _refresh_partition_hashes(root, manifest, part)
    with pytest.raises(core.ArchiveError, match='assignment mismatch'):
        _check(c, root, part)
    with pytest.raises(core.ArchiveError, match='assignment mismatch'):
        core.verify(root / 'archive-manifest.json', write_report=False)


@pytest.mark.parametrize('attribute,value', [(1, 'N'), (2, 17), (3, 5)])
def test_dbf_type_width_and_precision_are_checked(tmp_path, attribute, value):
    c, manifest, root, part = _prepared(tmp_path)
    _rewrite_shape(root / part['shapefile_path'], schema_change=('frp_mw', attribute, value))
    _refresh_partition_hashes(root, manifest, part)
    with pytest.raises(core.ArchiveError, match='types/widths/precision'):
        _check(c, root, part)
    with pytest.raises(core.ArchiveError, match='types/widths/precision'):
        exports.validate_upload_zip(root / part['shapefile_path'], part['source'], part['year'], 1)


def test_declared_six_decimal_numeric_projection_is_accepted(tmp_path):
    c, _, root, part = _prepared(tmp_path, [row(frp='6.123456789', brightness='330.123456789')])
    assert _check(c, root, part)['records'] == 1


@pytest.mark.parametrize('frp', ['', '0'])
def test_missing_measurement_and_zero_are_distinct_valid_projections(tmp_path, frp):
    c, _, root, part = _prepared(tmp_path, [row(frp=frp, brightness='', bright_t31='', scan='', track='')])
    assert _check(c, root, part)['records'] == 1


def test_shapefile_record_order_need_not_equal_csv_order(tmp_path):
    c, _, root, part = _prepared(tmp_path, [row(), row(latitude='8.2')])
    _rewrite_shape(root / part['shapefile_path'], reverse=True)
    assert _check(c, root, part)['records'] == 2


def test_coordinate_difference_is_not_tolerated_as_dbf_rounding(tmp_path):
    c, _, root, part = _prepared(tmp_path)
    _rewrite_shape(root / part['shapefile_path'], coordinate_change=(-1.00000001, 8.1))
    with pytest.raises(core.ArchiveError, match='coordinate mismatch'):
        _check(c, root, part)


def test_extra_geometry_cannot_hide_behind_the_dbf_record_count(tmp_path):
    c, manifest, root, part = _prepared(tmp_path)
    path=root/part['shapefile_path']
    with ZipFile(path) as archive:
        payload={name:archive.read(name) for name in archive.namelist()}
    stem=next(name[:-4] for name in payload if name.endswith('.shp'))
    shp=bytearray(payload[stem+'.shp'])
    shx=bytearray(payload[stem+'.shx'])
    # Add a complete second point and index entry while leaving DBF at one row.
    point=bytearray(shp[100:])
    struct.pack_into('>i',point,0,2)
    offset=len(shp)//2
    shp.extend(point)
    shx.extend(struct.pack('>ii',offset,len(point[8:])//2))
    struct.pack_into('>i',shp,24,len(shp)//2)
    struct.pack_into('>i',shx,24,len(shx)//2)
    payload[stem+'.shp']=bytes(shp)
    payload[stem+'.shx']=bytes(shx)
    core.zip_files(path,payload)
    _refresh_partition_hashes(root,manifest,part)
    with pytest.raises(core.ArchiveError,match='physical component length/count mismatch'):
        _check(c,root,part)
    with pytest.raises(core.ArchiveError,match='physical component length/count mismatch'):
        exports.validate_upload_zip(path,part['source'],part['year'],1)


@pytest.mark.parametrize('corruption', ['unindexed_point', 'shp_header_length',
                                      'shx_header_length', 'index_offset', 'index_length',
                                      'record_number', 'record_length'])
def test_point_framing_is_checked_independently_of_reader_record_count(tmp_path,corruption):
    c, manifest, root, part = _prepared(tmp_path)
    path=root/part['shapefile_path']
    with ZipFile(path) as archive:
        payload={name:archive.read(name) for name in archive.namelist()}
    stem=next(name[:-4] for name in payload if name.endswith('.shp'))
    shp=bytearray(payload[stem+'.shp'])
    shx=bytearray(payload[stem+'.shx'])
    if corruption=='unindexed_point':
        point=bytearray(shp[100:])
        struct.pack_into('>i',point,0,2)
        shp.extend(point)
        struct.pack_into('>i',shp,24,len(shp)//2)
    elif corruption=='shp_header_length':
        struct.pack_into('>i',shp,24,100)
    elif corruption=='shx_header_length':
        struct.pack_into('>i',shx,24,100)
    elif corruption=='index_offset':
        struct.pack_into('>i',shx,100,51)
    elif corruption=='index_length':
        struct.pack_into('>i',shx,104,11)
    elif corruption=='record_number':
        struct.pack_into('>i',shp,100,2)
    else:
        struct.pack_into('>i',shp,104,11)
    payload[stem+'.shp']=bytes(shp)
    payload[stem+'.shx']=bytes(shx)
    core.zip_files(path,payload)
    _refresh_partition_hashes(root,manifest,part)
    with pytest.raises(core.ArchiveError,match='physical component|declared component|framing mismatch'):
        _check(c,root,part)
    with pytest.raises(core.ArchiveError,match='physical component|declared component|framing mismatch'):
        core.verify(root/'archive-manifest.json',write_report=False)
    with pytest.raises(core.ArchiveError,match='physical component|declared component|framing mismatch'):
        exports.validate_upload_zip(path,part['source'],part['year'],part['record_count'])


def test_unrepresentable_text_and_numbers_fail_instead_of_truncating():
    with pytest.raises(core.ArchiveError, match='text exceeds DBF'):
        semantic._projected_attribute('Ã©', 'Ã©Ã©', 'C', 3, 0, 'fixture')
    with pytest.raises(core.ArchiveError, match='numeric value exceeds DBF'):
        semantic._projected_attribute(1e11, str(1e11), 'F', 18, 6, 'fixture')


def test_readable_export_must_preserve_checked_component_payload(tmp_path):
    c, _, root, _ = _prepared(tmp_path)
    manifest_path = root / 'archive-manifest.json'
    exports.export_annual(manifest_path, root)
    annual = root / 'annual'
    exported = json.loads((annual / 'annual-export.json').read_text())
    part = exported['partitions'][0]
    upload = annual / part['annual_shapefile_zip']
    _rewrite_shape(upload, changes={'frp_mw': 900})
    part['sha256'] = core.sha(upload)
    core.write_json(annual / 'annual-export.json', exported)
    metadata = annual / 'metadata/MODIS/Ghana_MODIS_SP_2024_provenance.json'
    provenance = json.loads(metadata.read_text())
    provenance['export'] = part
    core.write_json(metadata, provenance)
    (annual / 'annual-index.csv').write_bytes(exports._index_bytes(exported['partitions']))
    (root / 'annual-current.csv').write_bytes(exports._index_bytes(exported['partitions'], 'annual/'))
    with pytest.raises(core.ArchiveError, match='component differs from accepted'):
        exports.verify_annual(root, manifest_path)


def test_unmanifested_annual_file_is_rejected(tmp_path):
    c, _, root, _ = _prepared(tmp_path)
    manifest_path = root / 'archive-manifest.json'
    exports.export_annual(manifest_path, root)
    (root / 'annual/unlisted.csv').write_text('unexpected generated file')
    with pytest.raises(core.ArchiveError, match='undeclared files'):
        exports.verify_annual(root, manifest_path)
