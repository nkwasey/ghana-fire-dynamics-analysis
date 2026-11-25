import csv
import hashlib
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

from ghana_fire_archive import core


ROOT = Path(__file__).resolve().parents[1]


def synthetic_geography(root):
    """Write two neighbouring test districts and zones."""
    root.mkdir()

    def feature(west, east, **properties):
        return {
            'type': 'Feature',
            'properties': properties,
            'geometry': {
                'type': 'Polygon',
                'coordinates': [[[west, 7], [east, 7], [east, 10], [west, 10], [west, 7]]],
            },
        }

    layers = {
        'ghana': [feature(-2, 2)],
        'acz': [feature(-2, 0, zone_id='west'), feature(0, 2, zone_id='east')],
        'districts': [
            feature(-2, 0, district_id='D1', zone_id='west'),
            feature(0, 2, district_id='D2', zone_id='east'),
        ],
    }
    for layer, features in layers.items():
        core.write_json(root / f'{layer}.geojson', {'type': 'FeatureCollection', 'features': features})
    core.write_json(root / 'units.json', {'districts': [item['properties'] for item in layers['districts']]})
    entries = [f'{core.sha(path)}  {path.name}\n' for path in sorted(root.iterdir())]
    (root / 'checksums.sha256').write_text(''.join(entries), encoding='utf-8')
    return root


def row(**kw):
    return {'latitude':'8.1','longitude':'-1','brightness':'330','bright_t31':'300','scan':'1','track':'1','acq_date':'2024-01-01','acq_time':'230','satellite':'Terra','instrument':'MODIS','confidence':'80','version':'61.03','frp':'4','daynight':'N','type':'0',**kw}


def config(tmp_path):
    geography = synthetic_geography(tmp_path / 'geography')
    return {'output':str(tmp_path/'output'),'downloads':str(tmp_path/'downloads'),'geography':str(geography),'sources':['MODIS_SP'],'selected_years':[2024],'keep_downloads':True}


def fixture_source(c,records):
    root=Path(c['downloads']);root.mkdir(parents=True,exist_ok=True);p=root/'modis_2024_Ghana.csv'
    with p.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=row().keys());w.writeheader();w.writerows(records)
    item={'source':'MODIS_SP','year':2024,'status':'available','filename':p.name,'checked_start':'2024-01-01','checked_end':'2024-12-31','coverage_basis':'test-only provider-declared annual SP'}
    core.write_json(p.with_suffix('.receipt.json'),{**item,'sha256':core.sha(p)})
    return {'items':[item]}


def test_year_selection_and_portable_paths(tmp_path):
    p=tmp_path/'config.yaml';p.write_text('schema_version: 1\nyears: 2024\nsources: [MODIS_SP]\noutput: result\n')
    c=core.load_config(p);assert c['selected_years']==[2024];assert Path(c['output'])==tmp_path/'result'
    assert core.load_config(p,start=2020,end=2022)['selected_years']==[2020,2021,2022]
    with pytest.raises(core.ArchiveError):core.years({'start':2024,'end':2023})
    with pytest.raises(core.ArchiveError):core.years(True)


def test_sp_gate_and_source_identity():
    r=core.normalize(row(),'MODIS_SP','a'*64,2024)
    assert r['time_utc']=='02:30';assert r['confidence']=='high';assert r['confidence_raw']=='80';assert r['source_version']=='61.03'
    assert core.normalize(row(version='6.1NRT'),'MODIS_SP','a'*64,2024) is None
    for bad in [row(version='unknown'),row(satellite='N20'),row(confidence='101'),row(frp='nan'),row(acq_time='2460')]:
        with pytest.raises(ValueError):core.normalize(bad,'MODIS_SP','a'*64,2024)
    assert core.observation_id('VIIRS_NOAA20_SP','NOAA-20','2024-01-01','12:00',8,-1)!=core.observation_id('VIIRS_NOAA21_SP','NOAA-21','2024-01-01','12:00',8,-1)


def test_roundtrip_and_tamper_failure(tmp_path):
    c=config(tmp_path);plan=fixture_source(c,[row(),row(),row(latitude='8.2')]);m=core.prepare(c,plan)
    assert m['total_records']==2;assert m['partitions'][0]['qa']['duplicates']==1
    result=core.verify(Path(c['output'])/'archive-manifest.json');assert result['passed']
    zippath=Path(c['output'])/m['partitions'][0]['shapefile_path']
    with ZipFile(zippath) as z:
        dbf=next(name for name in z.namelist() if name.endswith('.dbf'))
        assert z.read(dbf)[1:4]==bytes([80,1,1])
    f=Path(c['output'])/m['partitions'][0]['path'];f.write_text(f.read_text()+'tamper')
    with pytest.raises(core.ArchiveError,match='checksum'):core.verify(Path(c['output'])/'archive-manifest.json')


def test_failed_rebuild_preserves_accepted_manifest(tmp_path):
    c=config(tmp_path);m=core.prepare(c,fixture_source(c,[row()]));pointer=Path(c['output'])/'archive-manifest.json';before=pointer.read_bytes()
    plan=fixture_source(c,[row(version='6.1NRT')])
    with pytest.raises(core.ArchiveError,match='NRT'):core.prepare(c,plan)
    assert pointer.read_bytes()==before;assert core.verify(pointer)['passed']


def test_missing_source_is_not_zero_or_complete(tmp_path):
    c=config(tmp_path);c['sources']=['VIIRS_NOAA21_SP'];plan={'items':[{'source':'VIIRS_NOAA21_SP','year':2024,'status':'unavailable','reason':'Not catalogued'}]}
    m=core.prepare(c,plan);assert not m['complete_requested_scope'];assert m['partitions']==[]
    assert m['source_coverage'][0]['checked_end'] is None


def test_geography_rejects_incomplete_hash_contract(tmp_path):
    copy=synthetic_geography(tmp_path/'geography')
    (copy/'checksums.sha256').write_text('')
    with pytest.raises(core.ArchiveError,match='incomplete'):core.Geography(copy)


def test_zero_api_window_has_checked_period_and_no_secrets(tmp_path,monkeypatch):
    c=config(tmp_path);monkeypatch.setenv('FIRMS_MAP_KEY','testing-secret-key-123')
    header=','.join(row().keys())+'\n'
    monkeypatch.setattr(core,'get_bytes',lambda url,c:(header.encode(),{}))
    item={'source':'MODIS_SP','year':2024,'status':'available','method':'api_sp','checked_start':'2024-01-01','checked_end':'2024-01-06','filename':'api.csv'}
    dst=Path(c['downloads'])/'api.csv';dst.parent.mkdir();receipt=dst.with_suffix('.receipt.json');core.download_api(c,item,dst,receipt)
    d=json.loads(receipt.read_text());assert len(d['batches'])==2;assert all(r['rows']==0 for r in d['batches'])
    assert 'testing-secret' not in receipt.read_text()


@pytest.mark.parametrize('header', [
    'latitude,longitude,acq_date,version\n',
    ','.join([*row(), 'version']) + '\n',
])
def test_bad_api_header_cannot_create_empty_coverage(tmp_path, monkeypatch, header):
    c = config(tmp_path)
    monkeypatch.setenv('FIRMS_MAP_KEY', 'testing-secret-key-123')
    monkeypatch.setattr(core, 'get_bytes', lambda url, config: (header.encode(), {}))
    root = Path(c['downloads'])
    dst = root / 'api.csv'
    receipt = dst.with_suffix('.receipt.json')
    item = {'source':'MODIS_SP', 'year':2024, 'status':'available', 'method':'api_sp',
            'checked_start':'2024-01-01', 'checked_end':'2024-01-01', 'filename':dst.name}

    with pytest.raises(core.ArchiveError, match='checkpoint not advanced'):
        core.download_api(c, item, dst, receipt)

    assert not dst.exists() and not receipt.exists()
    assert not list((root / 'api-batches').rglob('*.csv'))
    assert not list((root / 'api-batches').rglob('*.receipt.json'))


def test_bad_annual_header_is_rejected_before_publishing_cache(tmp_path, monkeypatch):
    c = config(tmp_path)
    root = Path(c['downloads'])
    root.mkdir()
    raw = b'latitude,longitude,acq_date,version\n'
    item = {'source':'MODIS_SP', 'year':2024, 'status':'available', 'filename':'modis_2024_Ghana.csv',
            'size_bytes':len(raw), 'url':'https://example.invalid/country.csv'}
    monkeypatch.setattr(core, 'make_plan', lambda config, refresh: {'items':[item]})
    monkeypatch.setattr(core, 'get_bytes', lambda url, config: (raw, {}))

    with pytest.raises(core.ArchiveError, match='not a valid FIRMS CSV'):
        core.download(c)

    path = root / item['filename']
    assert not path.exists() and not path.with_suffix('.receipt.json').exists()


def test_provider_annual_modis_version_is_preserved():
    # NASA's SP country export uses 6.2 in historical MODIS files. Preserve the
    # version verbatim; it must not be rewritten into an invented collection.
    r=core.normalize(row(version='6.2'),'MODIS_SP','a'*64,2024)
    assert r['source_version']=='6.2' and r['processing_status']=='SP'


def test_prepare_respects_configured_subset_of_cached_plan(tmp_path):
    c=config(tmp_path);plan=fixture_source(c,[row()]);plan['items'].append({'source':'MODIS_SP','year':2023,'status':'unavailable'})
    m=core.prepare(c,plan)
    assert m['years']==[2024] and len(m['source_coverage'])==1
    c['selected_years']=[2025]
    with pytest.raises(core.ArchiveError,match='does not cover'):core.prepare(c,plan)


def test_gfa2_preserves_measurement_variants_and_counts_collision_groups(tmp_path):
    c=config(tmp_path)
    # Same position/time, distinct reported measurement. No FRP-max choice.
    records=[row(frp='6.3',brightness='334.33'),row(frp='6.12',brightness='335.96'),row(frp='6.30',brightness='334.330',confidence='80.0')]
    m=core.prepare(c,fixture_source(c,records));part=m['partitions'][0]
    assert part['record_count']==2
    assert part['qa']['duplicates']==1
    assert part['qa']['measurement_variants_retained']==1
    assert part['qa']['position_time_groups_with_variants']==1
    with (Path(c['output'])/part['path']).open() as f:prepared=list(csv.DictReader(f))
    assert {float(r['frp_mw']) for r in prepared}=={6.3,6.12}
    assert len({r['id'] for r in prepared})==2 and all(r['id'].startswith('gfa2:') for r in prepared)
    forward={core.normalize(r,'MODIS_SP','a'*64,2024)['id'] for r in records}
    backward={core.normalize(r,'MODIS_SP','b'*64,2024)['id'] for r in reversed(records)}
    assert forward==backward=={r['id'] for r in prepared}


def test_gfa2_auxiliary_confidence_and_type_variants_are_not_lost():
    baseline=core.normalize(row(),'MODIS_SP','a'*64,2024)
    for change in [dict(bright_t31='301'),dict(confidence='90'),dict(type='1')]:
        assert core.normalize(row(**change),'MODIS_SP','a'*64,2024)['id']!=baseline['id']
    assert core.normalize(row(version='6.2'),'MODIS_SP','b'*64,2024)['id']==baseline['id']
    assert core.normalize(row(confidence='80.00'),'MODIS_SP','a'*64,2024)['id']==baseline['id']
