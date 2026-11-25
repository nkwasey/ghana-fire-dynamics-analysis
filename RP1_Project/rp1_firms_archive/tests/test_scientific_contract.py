"""Scientific-field and QA preservation contracts using synthetic observations."""
from copy import deepcopy
import csv
import hashlib
import json
from pathlib import Path
import platform

import pytest

from ghana_fire_archive import scientific


def record(**changes):
    return {'id': 'gfa2:' + 'a' * 64, 'source_product': 'MODIS_SP',
            'instrument': 'MODIS', 'platform': 'Terra', 'processing_status': 'SP',
            'confidence': 'high', 'confidence_raw': '80', 'fire_type': '0', 'daynight': 'N',
            'frp_mw': '4', 'brightness_k': '330', 'brightness_aux_k': '300',
            'scan_km': '1', 'track_km': '1', **changes}


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def raw_record(source='MODIS_SP', **changes):
    row = {'latitude': '8.1', 'longitude': '-1', 'scan': '1', 'track': '1',
           'acq_date': '2024-01-01', 'acq_time': '0230', 'satellite': 'Terra',
           'instrument': 'MODIS', 'confidence': '80', 'version': '61.03',
           'frp': '4', 'daynight': 'N', 'type': '0', 'brightness': '330',
           'bright_t31': '300'}
    if source != 'MODIS_SP':
        row.update(instrument='VIIRS', satellite='N', confidence='n', version='2',
                   bright_ti4=row.pop('brightness'), bright_ti5=row.pop('bright_t31'))
    return {**row, **changes}


def _archive(tmp_path, rows):
    root = tmp_path / 'archive'
    root.mkdir()
    canonical = root / 'canonical' / 'MODIS_SP' / '2024' / 'fixture.csv'
    canonical.parent.mkdir(parents=True)
    with canonical.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(record()))
        writer.writeheader()
        writer.writerows(rows)
    manifest = root / 'archive-manifest.json'
    manifest.write_text(json.dumps({'contract': 'ghana-firms-research-archive-v1',
        'total_records': len(rows), 'partitions': [{'source': 'MODIS_SP', 'year': 2024,
        'path': canonical.relative_to(root).as_posix(), 'sha256': _sha(canonical),
        'record_count': len(rows)}]}), encoding='utf-8')
    return manifest, canonical


def _files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob('*') if p.is_file()}


def test_valid_record_is_not_mutated():
    row = record()
    before = deepcopy(row)
    scientific.validate_scientific_record(row)
    assert scientific.quality_flags(row) == ()
    assert row == before


@pytest.mark.parametrize('daynight', ['D', 'N'])
@pytest.mark.parametrize('source,instrument,platform,confidence,raw', [
    ('MODIS_SP', 'MODIS', 'Terra', 'high', '80'),
    ('VIIRS_SNPP_SP', 'VIIRS', 'Suomi-NPP', 'nominal', 'n'),
    ('VIIRS_NOAA20_SP', 'VIIRS', 'NOAA-20', 'nominal', 'n'),
    ('VIIRS_NOAA21_SP', 'VIIRS', 'NOAA-21', 'nominal', 'n'),
])
def test_daynight_is_preserved_for_every_source(daynight, source, instrument, platform, confidence, raw):
    observation = record(daynight=daynight, source_product=source, instrument=instrument,
                         platform=platform, confidence=confidence, confidence_raw=raw,
                         brightness_k='0', frp_mw='0')
    before = deepcopy(observation)
    scientific.validate_scientific_record(observation)
    assert scientific.quality_flags(observation) == (
        'brightness_zero_unresolved', 'frp_zero_source_reported')
    assert observation == before


@pytest.mark.parametrize('daynight', ['', None, 'X', 'd', 'n', 'day', 'night',
                                     ' D', 'N ', 'DN', 0, 1, True, False, b'D', [], {}])
def test_invalid_saved_daynight_is_rejected_without_normalization(daynight):
    observation = record(daynight=daynight)
    before = deepcopy(observation)
    for operation in (scientific.validate_scientific_record, scientific.quality_flags):
        with pytest.raises(scientific.ScientificRecordError, match='daynight'):
            operation(observation)
        assert observation == before


def test_saved_daynight_field_is_required():
    observation = record()
    del observation['daynight']
    before = deepcopy(observation)
    with pytest.raises(scientific.ScientificRecordError, match='missing fields: daynight'):
        scientific.validate_scientific_record(observation)
    assert observation == before


def test_invalid_daynight_does_not_replace_accepted_qa(tmp_path):
    manifest, canonical = _archive(tmp_path, [record()])
    destination = manifest.parent / 'qa'
    scientific.write_quality_sidecars(manifest, destination)
    before = _files(destination)
    invalid = record(daynight='X')
    with canonical.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(record()), lineterminator='\n')
        writer.writeheader()
        writer.writerow(invalid)
    metadata = json.loads(manifest.read_text())
    metadata['partitions'][0]['sha256'] = _sha(canonical)
    manifest.write_text(json.dumps(metadata), encoding='utf-8')
    with pytest.raises(scientific.ScientificRecordError, match='daynight'):
        scientific.write_quality_sidecars(manifest, destination)
    assert _files(destination) == before


@pytest.mark.parametrize('score,category', [(0, 'low'), (29.5, 'low'), (30, 'nominal'),
    (79.5, 'nominal'), (80, 'high'), (100, 'high')])
def test_modis_confidence_boundaries(score, category):
    scientific.validate_scientific_record(record(confidence_raw=str(score), confidence=category))


@pytest.mark.parametrize('source,platform', [('VIIRS_SNPP_SP', 'Suomi-NPP'),
    ('VIIRS_NOAA20_SP', 'NOAA-20'), ('VIIRS_NOAA21_SP', 'NOAA-21')])
def test_each_viirs_source_has_its_own_platform(source, platform):
    row = record(source_product=source, instrument='VIIRS', platform=platform,
                 confidence='nominal', confidence_raw='n')
    scientific.validate_scientific_record(row)
    with pytest.raises(scientific.ScientificRecordError, match='instrument/platform'):
        scientific.validate_scientific_record({**row, 'platform': 'Terra'})


@pytest.mark.parametrize('change', [
    {'confidence_raw': '-1'}, {'confidence_raw': '101'}, {'confidence_raw': 'nan'},
    {'confidence': 'low'}, {'source_product': 'MODIS_NRT'}, {'instrument': 'VIIRS'},
    {'fire_type': 'not-code'}, {'fire_type': '4'}, {'fire_type': '-1'}, {'fire_type': True},
    {'frp_mw': '-0.1'}, {'brightness_k': '-1'}, {'brightness_aux_k': '-5'},
    {'scan_km': '0'}, {'track_km': '0'}, {'scan_km': '-1'}, {'track_km': '-1'},
    {'frp_mw': 'nan'}, {'brightness_k': 'inf'}, {'scan_km': True},
])
def test_protocol_invalid_scientific_fields_are_rejected(change):
    with pytest.raises(scientific.ScientificRecordError):
        scientific.validate_scientific_record(record(**change))


def test_raw_and_harmonized_viirs_confidence_must_agree():
    row = record(source_product='VIIRS_SNPP_SP', instrument='VIIRS', platform='Suomi-NPP',
                 confidence_raw='l', confidence='high')
    with pytest.raises(scientific.ScientificRecordError, match='disagree'):
        scientific.validate_scientific_record(row)


def test_reported_zero_measurements_are_preserved_with_flags():
    row = record(brightness_k='0.0', brightness_aux_k=0, frp_mw='0')
    before = deepcopy(row)
    assert scientific.quality_flags(row) == (
        'aux_brightness_zero_unresolved', 'brightness_zero_unresolved', 'frp_zero_source_reported')
    assert row == before
    assert row['id'] == before['id']


def test_explicit_missing_values_are_distinct_from_zero():
    row = record(frp_mw='', brightness_k=None, brightness_aux_k='', scan_km='',
                 track_km=None, fire_type='')
    before = deepcopy(row)
    assert scientific.quality_flags(row) == (
        'brightness_aux_k_missing', 'brightness_k_missing', 'fire_type_missing',
        'frp_mw_missing', 'scan_km_missing', 'track_km_missing')
    assert row == before
    with pytest.raises(scientific.ScientificRecordError, match='missing fields'):
        scientific.validate_scientific_record({k: v for k, v in row.items() if k != 'frp_mw'})


def test_no_invented_upper_caps_on_source_measurements():
    scientific.validate_scientific_record(record(frp_mw='100000', brightness_k='900',
                                                  brightness_aux_k='700'))


@pytest.mark.parametrize('field', list(raw_record()))
def test_required_raw_firms_columns_cannot_disappear(field):
    row = raw_record()
    row.pop(field)
    with pytest.raises(scientific.ScientificRecordError, match='missing'):
        scientific.validate_raw_field_presence(row, 'MODIS_SP')


def test_viirs_channel_aliases_are_explicit_and_nonmutating():
    row = raw_record('VIIRS_SNPP_SP')
    row['brightness'] = row.pop('bright_ti4')
    row['brightness_2'] = row.pop('bright_ti5')
    before = deepcopy(row)
    scientific.validate_raw_field_presence(row, 'VIIRS_SNPP_SP')
    assert row == before
    row['bright_ti4'] = '330.0'
    row['bright_ti5'] = '300.000'
    scientific.validate_raw_field_presence(row, 'VIIRS_SNPP_SP')


@pytest.mark.parametrize('aliases', [
    {'bright_ti4': '330', 'brightness': '331'},
    {'bright_ti4': '', 'brightness': '0'},
    {'bright_ti5': '300', 'brightness_2': '301'},
])
def test_conflicting_raw_channel_aliases_are_rejected(aliases):
    with pytest.raises(scientific.ScientificRecordError, match='Ambiguous'):
        scientific.validate_raw_field_presence(raw_record('VIIRS_SNPP_SP', **aliases), 'VIIRS_SNPP_SP')


def test_modis_auxiliary_name_does_not_replace_missing_viirs_channel():
    row = raw_record('VIIRS_SNPP_SP')
    row['bright_t31'] = row.pop('bright_ti5')
    with pytest.raises(scientific.ScientificRecordError, match='auxiliary'):
        scientific.validate_raw_field_presence(row, 'VIIRS_SNPP_SP')


@pytest.mark.parametrize('change', [{None: ['overflow']}, {'frp': None}, {'type': None}])
def test_raw_csv_overflow_or_truncated_row_is_rejected(change):
    with pytest.raises(scientific.ScientificRecordError, match='Malformed'):
        scientific.validate_raw_field_presence({**raw_record(), **change}, 'MODIS_SP')


def test_blank_measurements_are_explicit_not_missing_headers():
    scientific.validate_raw_field_presence(raw_record(brightness='', bright_t31='',
        frp='', scan='', track='', type=''), 'MODIS_SP')


def test_sparse_sidecars_bind_sources_and_leave_all_observations_unchanged(tmp_path):
    rows = [record(), record(id='gfa2:' + 'b' * 64, brightness_k='0', frp_mw='0')]
    manifest, canonical = _archive(tmp_path, rows)
    before = _files(manifest.parent)
    destination = manifest.parent / 'qa'
    result = scientific.write_quality_sidecars(manifest, destination)
    assert result['records'] == 2
    assert result['flagged_records'] == 1
    assert result['flag_counts'] == {'brightness_zero_unresolved': 1, 'frp_zero_source_reported': 1}
    assert canonical.read_bytes() == before[canonical.relative_to(manifest.parent).as_posix()]
    assert manifest.read_bytes() == before['archive-manifest.json']
    metadata = json.loads((destination / 'qa-manifest.json').read_text())
    assert metadata['research_manifest_sha256'] == _sha(manifest)
    assert metadata['provenance'] == {
        'scientific_module_sha256': _sha(Path(scientific.__file__)),
        'python_version': platform.python_version(),
        'python_implementation': platform.python_implementation(),
    }
    part = metadata['partitions'][0]
    assert part['canonical_sha256'] == _sha(canonical)
    assert part['qa_sha256'] == _sha(destination / part['qa_path'])
    with (destination / part['qa_path']).open() as stream:
        actual = list(csv.DictReader(stream))
    assert len(actual) == 1 and actual[0]['observation_id'] == rows[1]['id']
    qa_before = _files(destination)
    scientific.write_quality_sidecars(manifest, destination)
    assert _files(destination) == qa_before


def test_unflagged_and_empty_partitions_have_explicit_empty_qa_files(tmp_path):
    manifest, _ = _archive(tmp_path, [])
    destination = manifest.parent / 'qa'
    result = scientific.write_quality_sidecars(manifest, destination)
    assert result['records'] == result['flagged_records'] == 0
    metadata = json.loads((destination / 'qa-manifest.json').read_text())
    with (destination / metadata['partitions'][0]['qa_path']).open() as stream:
        assert list(csv.DictReader(stream)) == []


def test_failed_source_check_preserves_previous_qa(tmp_path):
    manifest, canonical = _archive(tmp_path, [record(frp_mw='0')])
    destination = manifest.parent / 'qa'
    scientific.write_quality_sidecars(manifest, destination)
    before = _files(destination)
    canonical.write_text(canonical.read_text().replace(',0,330,', ',2,330,'))
    with pytest.raises(scientific.ScientificRecordError, match='checksum'):
        scientific.write_quality_sidecars(manifest, destination)
    assert _files(destination) == before


def test_qa_does_not_replace_unrelated_or_scientific_directories(tmp_path):
    manifest, _ = _archive(tmp_path, [record()])
    unrelated = tmp_path / 'personal'
    unrelated.mkdir()
    (unrelated / 'notes.txt').write_text('keep')
    with pytest.raises(scientific.ScientificRecordError, match='non-QA'):
        scientific.write_quality_sidecars(manifest, unrelated)
    assert (unrelated / 'notes.txt').read_text() == 'keep'
    for target in (manifest.parent, manifest.parent / 'canonical' / 'nested',
                   manifest.parent / 'annual', manifest.parent / 'geography'):
        with pytest.raises(scientific.ScientificRecordError, match='overlaps'):
            scientific.write_quality_sidecars(manifest, target)


def test_concurrent_qa_lock_is_respected(tmp_path):
    manifest, _ = _archive(tmp_path, [record()])
    lock = manifest.parent / '.qa.qa.lock'
    lock.write_text('other process')
    with pytest.raises(scientific.ScientificRecordError, match='lock'):
        scientific.write_quality_sidecars(manifest, manifest.parent / 'qa')
    assert lock.read_text() == 'other process'


def test_qa_destination_resolves_normal_parent_components(tmp_path):
    manifest, _ = _archive(tmp_path, [record()])
    result = scientific.write_quality_sidecars(manifest, tmp_path / 'unused' / '..' / 'qa')
    assert Path(result['path']) == (tmp_path / 'qa').resolve()
    assert (tmp_path / 'qa' / 'qa-manifest.json').is_file()


def test_partial_publication_rolls_back_previous_qa(tmp_path, monkeypatch):
    manifest, _ = _archive(tmp_path, [record(frp_mw='0')])
    destination = manifest.parent / 'qa'
    scientific.write_quality_sidecars(manifest, destination)
    before = _files(destination)
    original = Path.rename
    def fail_staged_publication(path, target):
        if path.name == 'qa' and path.parent.name.startswith('.qa-stage-'):
            raise OSError('synthetic QA publication failure')
        return original(path, target)
    monkeypatch.setattr(Path, 'rename', fail_staged_publication)
    with pytest.raises(OSError, match='publication failure'):
        scientific.write_quality_sidecars(manifest, destination)
    assert _files(destination) == before
    assert not (destination.parent / '.qa.qa.lock').exists()


def test_scientific_algorithm_change_prevents_qa_publication(tmp_path, monkeypatch):
    manifest, _ = _archive(tmp_path, [record(frp_mw='0')])
    destination = manifest.parent / 'qa'
    scientific.write_quality_sidecars(manifest, destination)
    before = _files(destination)
    original = scientific._sha
    calls = 0

    def changed_module_hash(path):
        nonlocal calls
        if Path(path).resolve() == Path(scientific.__file__).resolve():
            calls += 1
            return 'a' * 64 if calls == 1 else 'b' * 64
        return original(path)

    monkeypatch.setattr(scientific, '_sha', changed_module_hash)
    with pytest.raises(scientific.ScientificRecordError, match='module changed'):
        scientific.write_quality_sidecars(manifest, destination)
    assert _files(destination) == before
