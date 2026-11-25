"""Acquisition coverage is independently bound to source bytes and obligations."""
from copy import deepcopy
import csv
from datetime import date, timedelta
import hashlib
import io
import json

import pytest

from ghana_fire_archive.acquisition import (
    validate_acquisition_receipt, validate_archive_obligations,
    validate_embedded_acquisition,
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def csv_bytes(rows):
    text = io.StringIO(newline='')
    writer = csv.DictWriter(text, fieldnames=['acq_date', 'value'], lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode('utf-8')


def acquisition(tmp_path, *, api=False, start='2024-01-01', end='2024-12-31'):
    root = tmp_path/'downloads'
    root.mkdir(exist_ok=True)
    year = date.fromisoformat(start).year
    filename = f'MODIS_SP_{year}_Ghana_api.csv' if api else f'modis_{year}_Ghana.csv'
    raw = root/filename
    rows = [{'acq_date': start, 'value': 'preserved-measurement'}]
    raw.write_bytes(csv_bytes(rows))
    item = dict(source='MODIS_SP', year=year, status='available', filename=filename,
                checked_start=start, checked_end=end, provider_updated='2025-01-31',
                coverage_basis='synthetic acquisition contract fixture')
    if api:
        item.update(method='api_sp', availability=dict(
            data_id='MODIS_SP', min_date=f'{year}-01-01', max_date=f'{year}-12-31'))
        batches = []
        day, stop = date.fromisoformat(start), date.fromisoformat(end)
        while day <= stop:
            last = min(day + timedelta(days=4), stop)
            path = root/'api-batches/MODIS_SP'/f'{day}_{last}.csv'
            path.parent.mkdir(parents=True, exist_ok=True)
            selected = [r for r in rows if str(day) <= r['acq_date'] <= str(last)]
            path.write_bytes(csv_bytes(selected))
            own = dict(source='MODIS_SP', processing_status='SP', checked_start=str(day),
                       checked_end=str(last), sha256=sha(path), rows=len(selected),
                       retrieved_utc='2025-02-01T12:00:00+00:00')
            path.with_suffix('.receipt.json').write_text(json.dumps(own), encoding='utf-8')
            batches.append(dict(file=path.relative_to(root).as_posix(), **own))
            day = last + timedelta(days=1)
        receipt = dict(item, sha256=sha(raw), batches=batches)
    else:
        item['size_bytes'] = raw.stat().st_size
        catalogue = root/'yearly_summary_files.txt'
        catalogue.write_text(f"filename,size,updated\n{filename},{item['size_bytes']},{item['provider_updated']}\n")
        item['catalogue_sha256'] = sha(catalogue)
        receipt = dict(item, sha256=sha(raw), retrieved_utc='2025-02-01T12:00:00+00:00')
    return root, raw, item, receipt


def manifest(*, source='MODIS_SP', year=2024, start=None, end=None, status='available', count=1):
    launch = {'MODIS_SP':'2000-11-01', 'VIIRS_SNPP_SP':'2012-01-20',
              'VIIRS_NOAA20_SP':'2018-04-01', 'VIIRS_NOAA21_SP':'2023-03-01'}[source]
    start = start or max(f'{year}-01-01', launch)
    end = end or f'{year}-12-31'
    coverage = dict(source=source, year=year, status=status)
    partitions = []
    if status == 'available':
        coverage.update(checked_start=start, checked_end=end, processing_status='SP',
                        partial_year=start != f'{year}-01-01' or end != f'{year}-12-31',
                        source_sha256='a'*64)
        partitions.append(dict(source=source, year=year, processing_status='SP',
                               coverage_start=start, coverage_end=end, coverage=deepcopy(coverage),
                               source_sha256='a'*64, record_count=count))
    else:
        coverage.update(checked_start=None, checked_end=None)
    return dict(requested_sources=[source], years=[year], processing_status='SP',
                source_coverage=[coverage], partitions=partitions,
                total_records=count if partitions else 0,
                complete_available_sp_scope=status != 'unavailable',
                complete_requested_scope=status == 'structurally_unavailable' or (
                    status == 'available' and start == max(f'{year}-01-01', launch)
                    and end == f'{year}-12-31'))


def test_annual_receipt_has_stable_acquisition_identity(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path)
    first = validate_acquisition_receipt(item, receipt, raw, root)
    receipt['retrieved_utc'] = '2025-03-01T12:00:00+00:00'
    receipt['response'] = {'etag':'metadata-only'}
    assert validate_acquisition_receipt(item, receipt, raw, root) == first
    assert first['source_sha256'] == sha(raw)
    assert first['batch_count'] == 0
    assert validate_embedded_acquisition(first) == first


@pytest.mark.parametrize('field,value', [
    ('source','VIIRS_SNPP_SP'), ('year',2023), ('checked_start','2024-01-02'),
    ('checked_end','2024-01-31'), ('provider_updated','different'),
    ('filename','different.csv'), ('method','api_sp'), ('size_bytes',1),
    ('catalogue_sha256','b'*64),
])
def test_receipt_mismatch_fails_before_admission(tmp_path, field, value):
    root, raw, item, receipt = acquisition(tmp_path)
    receipt[field] = value
    with pytest.raises(ValueError, match='receipt/plan|method'):
        validate_acquisition_receipt(item, receipt, raw, root)


def test_plan_expansion_does_not_establish_acquired_coverage(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path, end='2024-01-31')
    item['checked_end'] = '2024-12-31'
    with pytest.raises(ValueError, match='checked_end'):
        validate_acquisition_receipt(item, receipt, raw, root)


def test_optional_metadata_cannot_be_removed_on_one_side(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path)
    del receipt['provider_updated']
    with pytest.raises(ValueError, match='provider_updated'):
        validate_acquisition_receipt(item, receipt, raw, root)


def test_minimal_legacy_fixture_requires_same_scope_and_hash(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path)
    for key in ('catalogue_sha256','provider_updated','size_bytes','coverage_basis'):
        del item[key]
        del receipt[key]
    result = validate_acquisition_receipt(item, receipt, raw, root)
    assert result['coverage']['checked_end'] == item['checked_end']
    raw.write_bytes(raw.read_bytes()+b'changed\n')
    with pytest.raises(ValueError, match='checksum'):
        validate_acquisition_receipt(item, receipt, raw, root)


@pytest.mark.parametrize('api,field', [(False,'provider_updated'), (False,'coverage_basis'),
                                     (False,'size_bytes'), (False,'catalogue_sha256'),
                                     (True,'provider_updated'), (True,'coverage_basis'),
                                     (True,'availability')])
def test_production_requests_cannot_omit_provider_metadata_on_both_sides(tmp_path, api, field):
    root, raw, item, receipt = acquisition(tmp_path, api=api)
    item['url'] = receipt['url'] = 'https://provider.invalid/source'
    del item[field]
    del receipt[field]
    with pytest.raises(ValueError, match='Production acquisition provider metadata is missing'):
        validate_acquisition_receipt(item, receipt, raw, root)


def test_annual_catalogue_bytes_are_bound(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path)
    (root/'yearly_summary_files.txt').write_text('filename,size,updated\n')
    with pytest.raises(ValueError, match='catalogue checksum'):
        validate_acquisition_receipt(item, receipt, raw, root)


def test_api_leap_day_and_empty_batch_have_explicit_checked_coverage(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path, api=True, start='2024-02-26', end='2024-03-02')
    checked = validate_acquisition_receipt(item, receipt, raw, root)
    assert checked['batch_count'] == 2
    assert checked['batches'][0]['checked_end'] == '2024-03-01'
    assert checked['batches'][1]['rows'] == 0
    assert validate_embedded_acquisition(checked) == checked


def test_empty_acquired_extension_changes_coverage_identity_not_measurements(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path, api=True, end='2024-01-05')
    before = validate_acquisition_receipt(item, receipt, raw, root)
    original = raw.read_bytes()
    root, raw, item, receipt = acquisition(tmp_path, api=True, end='2024-01-10')
    after = validate_acquisition_receipt(item, receipt, raw, root)
    assert raw.read_bytes() == original
    assert before['source_sha256'] == after['source_sha256']
    assert before['acquisition_sha256'] != after['acquisition_sha256']
    assert after['coverage']['checked_end'] == '2024-01-10'


def test_api_windows_use_five_inclusive_utc_dates_in_nonleap_year(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path, api=True, start='2001-02-26', end='2001-03-03')
    result = validate_acquisition_receipt(item, receipt, raw, root)
    assert [(b['checked_start'], b['checked_end']) for b in result['batches']] == [
        ('2001-02-26', '2001-03-02'), ('2001-03-03', '2001-03-03')]
    assert result['batches'][1]['rows'] == 0


def test_api_retrieval_timestamp_is_provenance_not_identity(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path, api=True, start='2024-01-01', end='2024-01-05')
    first = validate_acquisition_receipt(item, receipt, raw, root)
    batch = receipt['batches'][0]
    batch['retrieved_utc'] = '2025-03-01T00:00:00+00:00'
    (root/batch['file']).with_suffix('.receipt.json').write_text(
        json.dumps({k:v for k,v in batch.items() if k != 'file'}), encoding='utf-8')
    assert validate_acquisition_receipt(item, receipt, raw, root) == first


def test_acquisition_cannot_claim_preoperational_dates(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path)
    for record in (item, receipt):
        record.update(source='VIIRS_NOAA21_SP', year=2022, checked_start='2022-01-01', checked_end='2022-12-31')
    with pytest.raises(ValueError, match='effective start'):
        validate_acquisition_receipt(item, receipt, raw, root)


@pytest.mark.parametrize('filename', ['../escape.csv', 'C:/escape.csv', 'batch.csv:stream'])
def test_api_paths_are_portable_and_confined_to_downloads(tmp_path, filename):
    root, raw, item, receipt = acquisition(tmp_path, api=True, start='2024-01-01', end='2024-01-05')
    receipt['batches'][0]['file'] = filename
    with pytest.raises(ValueError, match='path'):
        validate_acquisition_receipt(item, receipt, raw, root)


@pytest.mark.parametrize('mode', ['missing_batch','hash','gap','row_count','source','concat'])
def test_api_chain_errors_fail_closed(tmp_path, mode):
    root, raw, item, receipt = acquisition(tmp_path, api=True, end='2024-01-06')
    batch = receipt['batches'][0]
    path = root/batch['file']
    if mode == 'missing_batch':
        path.unlink()
    elif mode == 'concat':
        raw.write_bytes(csv_bytes([{'acq_date':'2024-01-01','value':'wrong measurement'}]))
        receipt['sha256'] = sha(raw)
    else:
        if mode == 'hash': batch['sha256'] = 'b'*64
        if mode == 'gap': batch['checked_start'] = '2024-01-02'
        if mode == 'row_count': batch['rows'] = 9
        if mode == 'source': batch['source'] = 'VIIRS_SNPP_SP'
        path.with_suffix('.receipt.json').write_text(json.dumps({k:v for k,v in batch.items() if k!='file'}))
    with pytest.raises(ValueError):
        validate_acquisition_receipt(item, receipt, raw, root)


def test_embedded_receipt_must_link_to_partition_and_validate_digest(tmp_path):
    root, raw, item, receipt = acquisition(tmp_path)
    checked = validate_acquisition_receipt(item, receipt, raw, root)
    part = dict(source=item['source'], year=2024, source_sha256=sha(raw),
                coverage_start=item['checked_start'], coverage_end=item['checked_end'])
    assert validate_embedded_acquisition(checked, part) == checked
    part['coverage_end'] = '2024-01-31'
    with pytest.raises(ValueError, match='differs from its partition'):
        validate_embedded_acquisition(checked, part)
    changed = deepcopy(checked)
    changed['coverage']['checked_end'] = '2024-01-31'
    with pytest.raises(ValueError, match='checksum'):
        validate_embedded_acquisition(changed)


def test_explicit_empty_available_partition_is_complete():
    m = manifest(count=0)
    result = validate_archive_obligations(m)
    assert result['available_partitions'] == 1
    assert result['complete_requested_scope']


def test_missing_available_partition_does_not_verify_as_empty_complete():
    m = manifest(count=0)
    m['partitions'] = []
    with pytest.raises(ValueError, match='missing its explicit partition'):
        validate_archive_obligations(m)


@pytest.mark.parametrize('mode', ['extra_partition','duplicate_partition','missing_coverage',
                                 'duplicate_coverage','unknown_status','wrong_interval','false_flag'])
def test_manifest_partition_and_coverage_obligations_fail_closed(mode):
    m = manifest()
    if mode == 'extra_partition':
        m['partitions'].append(dict(m['partitions'][0], source='VIIRS_SNPP_SP'))
    elif mode == 'duplicate_partition': m['partitions'].append(deepcopy(m['partitions'][0]))
    elif mode == 'missing_coverage': m['source_coverage'] = []
    elif mode == 'duplicate_coverage': m['source_coverage'].append(deepcopy(m['source_coverage'][0]))
    elif mode == 'unknown_status': m['source_coverage'][0]['status'] = 'not-checked'
    elif mode == 'wrong_interval': m['partitions'][0]['coverage_start'] = '2024-02-01'
    else: m['complete_requested_scope'] = False
    with pytest.raises(ValueError):validate_archive_obligations(m)


@pytest.mark.parametrize('source,year,start', [
    ('MODIS_SP',2000,'2000-11-01'), ('VIIRS_SNPP_SP',2012,'2012-01-20'),
    ('VIIRS_NOAA20_SP',2018,'2018-04-01'), ('VIIRS_NOAA21_SP',2023,'2023-03-01'),
])
def test_first_operational_partial_calendar_year_can_cover_all_eligible_dates(source, year, start):
    m = manifest(source=source, year=year, start=start)
    assert m['source_coverage'][0]['partial_year']
    assert validate_archive_obligations(m)['complete_requested_scope']


def test_late_start_inside_operational_year_is_not_complete_requested_scope():
    m = manifest(start='2024-02-01')
    assert not validate_archive_obligations(m)['complete_requested_scope']
    m['complete_requested_scope'] = True
    with pytest.raises(ValueError, match='completeness flag'):
        validate_archive_obligations(m)


def test_structural_and_unavailable_states_remain_distinct():
    prelaunch = manifest(source='VIIRS_NOAA21_SP',year=2020,status='structurally_unavailable')
    result = validate_archive_obligations(prelaunch)
    assert result['structurally_unavailable'] == 1 and result['complete_requested_scope']
    unavailable = manifest(status='unavailable')
    result = validate_archive_obligations(unavailable)
    assert not result['complete_requested_scope'] and not result['complete_available_sp_scope']
    unavailable['source_coverage'][0]['status'] = 'structurally_unavailable'
    with pytest.raises(ValueError, match='effective start'):
        validate_archive_obligations(unavailable)


def test_prepare_can_derive_flags_before_publishing_manifest():
    m = manifest(start='2024-02-01')
    del m['complete_requested_scope']
    del m['complete_available_sp_scope']
    result = validate_archive_obligations(m, check_declared=False)
    assert result['complete_available_sp_scope'] and not result['complete_requested_scope']


@pytest.mark.parametrize('mode', ['boolean_year','boolean_total','nonsp','unknown_source'])
def test_invalid_manifest_field_types_fail_closed(mode):
    m = manifest()
    if mode == 'boolean_year':m['years'] = [True]
    if mode == 'boolean_total':m['total_records'] = True
    if mode == 'nonsp':m['processing_status'] = 'NRT'
    if mode == 'unknown_source':m['requested_sources'] = [['MODIS_SP']]
    with pytest.raises(ValueError):validate_archive_obligations(m)
