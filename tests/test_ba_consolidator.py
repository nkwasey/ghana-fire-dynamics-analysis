"""Native c3 preparation behavior, with no generated national input dependency."""
import csv
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from c3_fixture import write_delivery, write_csv
from RP1_Project.rp1_ba_consolidator import core, handoff


@pytest.fixture
def source(tmp_path):
    downloads, units = write_delivery(tmp_path)
    return downloads, units, tmp_path / 'bundle'


def options(source, **kwargs):
    downloads, units, output = source
    return core.ConsolidationOptions(downloads, output, start_year=2024, unit_universe=units, **kwargs)


def read(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        return reader.fieldnames, list(reader)


def test_actual_consumer_admits_twenty_original_files_unchanged(source):
    original = {p.name: p.read_bytes() for p in source[0].glob('*.csv')}
    report = core.consolidate(options(source))
    assert report['consumer_validation_status'] == 'PASS'
    assert report['input_files'] == 20 and report['scope'] == 'pilot'
    assert {p.name: p.read_bytes() for p in (source[2] / 'sources').glob('*.csv')} == original
    verified = handoff.verify_handoff(source[2], unit_universe=source[1])
    assert verified['profile_contract']['source_schema_version'] == 'rp1_ba_c3_extended_v2'
    lock = json.loads((source[2] / 'source_lock.json').read_text())
    assert len(lock['files']) == 20
    assert all(e['role'] == 'extended' and e['year'] == 2024 for e in lock['files'])


def test_full_370_matrix_and_actual_consumer_admission(tmp_path):
    downloads, units = write_delivery(tmp_path, full=True)
    report = core.consolidate(core.ConsolidationOptions(downloads, tmp_path / 'bundle', unit_universe=units, start_year=2001, scope='full'))
    assert report['scope'] == 'full' and report['input_files'] == 370
    assert report['consumer_validation_status'] == 'PASS'
    handoff.verify_handoff(tmp_path / 'bundle', unit_universe=units, require_full=True)


def test_validate_only_never_writes_or_calls_callback(source):
    source[2].mkdir()
    marker = source[2] / 'existing'
    marker.write_bytes(b'preserve')
    def forbidden(*args):
        raise AssertionError('publication callback called')
    report = core.consolidate(options(source, validate_only=True), pre_publish=forbidden)
    assert report['consumer_validation_status'] == 'NOT_RUN'
    assert list(source[2].iterdir()) == [marker] and marker.read_bytes() == b'preserve'


def test_standard_library_validate_only_cli_from_another_directory(source, tmp_path):
    script = ROOT / 'tools/consolidate_ba.py'
    result = subprocess.run([sys.executable, '-S', str(script), '--input-dir', str(source[0]),
        '--output-dir', str(source[2]), '--start-year', '2024', '--validate-only'],
        cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '20 annual c3 sources' in result.stdout and not source[2].exists()


@pytest.mark.parametrize('mutation', ['missing_file', 'duplicate_file', 'missing_month', 'duplicate_key',
    'old_source', 'bad_header', 'row_width', 'wrong_year', 'wrong_parent', 'source_drift', 'lc_drift'])
def test_incomplete_mixed_or_inconsistent_delivery_fails(source, mutation):
    path = next(source[0].glob('*district*CZ*BA2001*'))
    header, rows = read(path)
    if mutation == 'missing_file':
        path.unlink()
    elif mutation == 'duplicate_file':
        duplicate = source[0] / 'duplicate' / path.name
        duplicate.parent.mkdir()
        shutil.copyfile(path, duplicate)
    elif mutation == 'old_source':
        path.rename(path.with_name(path.name.replace('_c3_', '_c2_')))
    elif mutation == 'row_width':
        path.write_text(','.join(header) + '\nshort,row\n')
    else:
        if mutation == 'missing_month': rows.pop()
        if mutation == 'duplicate_key': rows.append(rows[0])
        if mutation == 'bad_header': header[0], header[1] = header[1], header[0]
        if mutation == 'wrong_year': rows[0]['year'] = '2023'
        if mutation == 'wrong_parent': rows[0]['parent_code'] = 'FZ'
        if mutation == 'source_drift': rows[0]['ba_source_index'] = 'different_source'
        if mutation == 'lc_drift': rows[0]['ba_lc_source_indexes'] = rows[0]['ba_lc_source_indexes'].replace('2001', 'changed')
        write_csv(path, rows, fields=header)
    with pytest.raises(ValueError):
        core.consolidate(options(source, validate_only=True))
    assert not source[2].exists()


def test_anomaly_primary_null_does_not_break_fixed_domain(source):
    from c3_fixture import make_row
    path = next(source[0].glob('*district*CZ*BA2001*'))
    _, rows = read(path)
    rows[0] = make_row(state='anomaly')
    write_csv(path, rows)
    report = core.consolidate(options(source))
    assert report['consumer_validation_status'] == 'PASS'
    _, staged = read(source[2] / 'sources' / path.name)
    assert staged[0]['modis_burnable_km2_union'] == ''
    assert staged[0]['ba_known_union_area_km2'] == '4'


def test_prepublication_rejection_and_source_mutation_never_publish(source):
    def reject(stage, report):
        raise ValueError('consumer rejected')
    with pytest.raises(ValueError, match='consumer rejected'):
        core.consolidate(options(source), pre_publish=reject)
    assert not source[2].exists()
    def mutate(stage, report):
        handoff.admit_bundle(stage, report, unit_universe=source[1])
        path = next(source[0].glob('*.csv'))
        path.write_bytes(path.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='Source changed'):
        core.consolidate(options(source), pre_publish=mutate)
    assert not source[2].exists()


def test_existing_output_and_overlapping_paths_are_protected(source):
    source[2].mkdir()
    with pytest.raises(ValueError, match='already exists'):
        core.consolidate(options(source))
    with pytest.raises(ValueError, match='disjoint'):
        core.consolidate(core.ConsolidationOptions(source[0], source[0] / 'output', start_year=2024, validate_only=True))


def test_pilot_cannot_be_labelled_full(source):
    with pytest.raises(ValueError, match='Full scope'):
        core.consolidate(options(source, scope='full', validate_only=True))


def test_overlapping_reference_year_sources_must_match_across_domains(source):
    for path in source[0].glob('*BA2012*'):
        header, rows = read(path)
        for row in rows:
            row['ba_lc_source_indexes'] = row['ba_lc_source_indexes'].replace('2012', 'changed2012')
        write_csv(path, rows, fields=header)
    with pytest.raises(ValueError, match='drift'):
        core.consolidate(options(source, validate_only=True))


def receipt(source):
    path = source[0] / 'rp1_ba_district_monthly_c3_CZ_BA2001_2024-2024_qa_by_acz.csv'
    row = dict(schema_version='c3_unit_inventory_v1', domain='BA2001', zone_id='coastal_zone',
        zone_code='CZ', district_filter='', selected_unit_count='1', raw_asset_zone_count='1',
        identity_preflight='PASSED', geometry_preflight='CLIPPED_NONZERO_AREA_ONLY',
        source_preflight='PASSED', start_year='2024', end_year='2024',
        boundary_asset='projects/synthetic/assets/districts', ghana_asset='projects/synthetic/assets/ghana')
    return path, row


def test_optional_receipt_is_preserved_separately_without_becoming_support(source):
    path, row = receipt(source)
    write_csv(path, [row], fields=list(row))
    original = path.read_bytes()
    report = core.consolidate(options(source))
    assert report['input_files'] == 20 and report['auxiliary_files'] == 1
    assert (source[2] / 'auxiliary' / path.name).read_bytes() == original
    assert len(json.loads((source[2] / 'source_lock.json').read_text())['files']) == 20


@pytest.mark.parametrize('field,value', [('domain', 'BA2012'), ('selected_unit_count', '2'),
    ('boundary_asset', 'projects/changed'), ('identity_preflight', 'FAILED')])
def test_optional_receipt_cannot_contradict_sources_or_geography(source, field, value):
    path, row = receipt(source)
    row[field] = value
    write_csv(path, [row], fields=list(row))
    with pytest.raises(ValueError):
        core.consolidate(options(source, validate_only=True))


def test_canonical_geography_header_is_exact_even_for_validation_only(source):
    header, rows = read(source[1])
    for row in rows:
        row['unbound_extra'] = 'unexpected'
    write_csv(source[1], rows, fields=[*header, 'unbound_extra'])
    with pytest.raises(ValueError, match='exact canonical header'):
        core.consolidate(options(source, validate_only=True))


def test_logically_duplicate_calendar_key_is_rejected_before_admission(source):
    path = next(source[0].glob('*district*CZ*BA2001*'))
    header, rows = read(path)
    extra = dict(rows[0], yyyymm='202401.0')
    rows.append(extra)
    write_csv(path, rows, fields=header)
    with pytest.raises(ValueError, match='duplicate unit-month'):
        core.consolidate(options(source, validate_only=True))
