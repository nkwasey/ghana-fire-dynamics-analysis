"""Nonmutating scientific-field validation and separate observation QA records.

The archive preserves source-reported measurements, including unresolved zero
temperatures and zero FRP. Quality flags are not replacement scientific values
and do not remove observations or change their measurement-based identities.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import tempfile
import uuid
from collections import Counter


class ScientificRecordError(ValueError):
    """A record violates the declared scientific field contract."""


_SOURCE_SPECS = {
    'MODIS_SP': ('MODIS', frozenset(('Terra', 'Aqua'))),
    'VIIRS_SNPP_SP': ('VIIRS', frozenset(('Suomi-NPP',))),
    'VIIRS_NOAA20_SP': ('VIIRS', frozenset(('NOAA-20',))),
    'VIIRS_NOAA21_SP': ('VIIRS', frozenset(('NOAA-21',))),
}
_CONFIDENCE = {'l': 'low', 'n': 'nominal', 'h': 'high',
               'low': 'low', 'nominal': 'nominal', 'high': 'high'}
_MEASUREMENTS = ('frp_mw', 'brightness_k', 'brightness_aux_k', 'scan_km', 'track_km')
_RAW_COMMON = ('latitude', 'longitude', 'scan', 'track', 'acq_date', 'acq_time',
               'satellite', 'instrument', 'confidence', 'version', 'frp', 'daynight', 'type')
_REQUIRED = ('source_product', 'instrument', 'platform', 'confidence',
             'confidence_raw', 'fire_type', 'daynight') + _MEASUREMENTS
QA_FIELDS = ('observation_id', 'source', 'year', 'flags')
QA_CONTRACT = 'ghana-firms-quality-sidecars-v1'
FLAG_DEFINITIONS = {
    'brightness_zero_unresolved': 'Source-reported primary brightness is zero; radiometric cause unresolved. Preserve the observation.',
    'aux_brightness_zero_unresolved': 'Source-reported auxiliary brightness is zero; radiometric cause unresolved. Preserve the observation.',
    'frp_zero_source_reported': 'Source-reported FRP is zero; not evidence of no detection or zero physical fire intensity.',
    'fire_type_missing': 'Source did not provide a fire-type value; do not assume vegetation fire.',
    **{field + '_missing': 'Source measurement is explicitly missing; not replaced by zero.'
       for field in _MEASUREMENTS},
}


def _missing(value):
    return value is None or value == ''


def _number(value, field):
    if isinstance(value, bool):
        raise ScientificRecordError(f'{field} must be numeric, not Boolean')
    try:
        result = float(value)
    except (ValueError, TypeError):
        raise ScientificRecordError(f'{field} must be numeric') from None
    if not math.isfinite(result):
        raise ScientificRecordError(f'{field} must be finite')
    return result


def validate_raw_field_presence(record, source):
    """Require the FIRMS SP delivery fields before normalizing their values.

    Blank cells are explicit missing values, unlike absent headers, truncated
    rows or overflow columns. VIIRS web-service channel aliases are supported;
    duplicate aliases must represent the same value so selection cannot lose a
    conflicting measurement. No source dictionary entry is modified.
    """
    if source not in _SOURCE_SPECS:
        raise ScientificRecordError('Unsupported raw scientific source product')
    if None in record or any(value is None for value in record.values()):
        raise ScientificRecordError('Malformed raw CSV row: missing or overflow column values')
    absent = [field for field in _RAW_COMMON if field not in record]
    if absent:
        raise ScientificRecordError('Raw scientific record is missing fields: ' + ', '.join(absent))
    channels = ((('brightness',), 'primary brightness'), (('bright_t31',), 'auxiliary brightness'))
    if source != 'MODIS_SP':
        channels = ((('bright_ti4', 'brightness'), 'primary brightness'),
                    (('bright_ti5', 'brightness_2'), 'auxiliary brightness'))
    for aliases, label in channels:
        values = [record[name] for name in aliases if name in record]
        if not values:
            raise ScientificRecordError(f'Raw scientific record is missing {label} field')
        if len(values) > 1:
            if any(_missing(value) for value in values):
                same = all(_missing(value) for value in values)
            else:
                numbers = [_number(value, label) for value in values]
                same = all(value == numbers[0] for value in numbers)
            if not same:
                raise ScientificRecordError(f'Ambiguous raw aliases for {label}')


def validate_raw_csv_header(fieldnames, source):
    """Validate a source schema even when the response has no observations."""
    if not fieldnames or any(not name.strip() for name in fieldnames) or len(set(fieldnames)) != len(fieldnames):
        raise ScientificRecordError('Missing, blank or repeated raw CSV headers')
    validate_raw_field_presence(dict.fromkeys(fieldnames, ''), source)


def validate_scientific_record(record):
    """Check canonical/normalized fields without changing values or IDs.

    Empty optional measurements and fire type are preserved and explicitly
    flagged by :func:`quality_flags`. Finite zero temperatures are preserved
    as unresolved source anomalies, not interpreted as physical 0 K or a known
    fill code. No empirical upper cutoff is imposed on FRP or brightness.
    Saved day/night codes must already be exactly D or N; validation does not
    normalize them or change their measurement-based observation identities.
    """
    missing = [name for name in _REQUIRED if name not in record]
    if missing:
        raise ScientificRecordError('Scientific record is missing fields: ' + ', '.join(missing))
    source = record['source_product']
    if source not in _SOURCE_SPECS:
        raise ScientificRecordError('Unsupported scientific source product')
    instrument, platforms = _SOURCE_SPECS[source]
    if record['instrument'] != instrument or record['platform'] not in platforms:
        raise ScientificRecordError('Scientific instrument/platform differs from source')
    daynight = record['daynight']
    if not isinstance(daynight, str) or daynight not in ('D', 'N'):
        raise ScientificRecordError('daynight must be exactly D or N')
    raw = str(record['confidence_raw']).strip()
    if source == 'MODIS_SP':
        confidence = _number(raw, 'confidence_raw')
        if not 0 <= confidence <= 100:
            raise ScientificRecordError('MODIS confidence must be within 0–100')
        expected = 'low' if confidence < 30 else 'nominal' if confidence < 80 else 'high'
    else:
        expected = _CONFIDENCE.get(raw.lower())
        if expected is None:
            raise ScientificRecordError('Invalid VIIRS raw confidence')
    if record['confidence'] != expected:
        raise ScientificRecordError('Raw confidence and scientific confidence class disagree')
    fire_type = record['fire_type']
    if not _missing(fire_type) and str(fire_type).strip() not in {'0', '1', '2', '3'}:
        raise ScientificRecordError('Fire type must be a documented code 0, 1, 2 or 3, or missing')
    for field in _MEASUREMENTS:
        value = record[field]
        if _missing(value):
            continue
        value = _number(value, field)
        if field in ('scan_km', 'track_km') and value <= 0:
            raise ScientificRecordError(f'{field} must be positive when present')
        if field not in ('scan_km', 'track_km') and value < 0:
            raise ScientificRecordError(f'{field} must be nonnegative when present')


def quality_flags(record):
    """Return stable flags; do not modify, exclude or reinterpret a detection."""
    validate_scientific_record(record)
    flags = []
    for field in _MEASUREMENTS:
        value = record[field]
        if _missing(value):
            flags.append(field + '_missing')
        elif field == 'brightness_k' and float(value) == 0:
            flags.append('brightness_zero_unresolved')
        elif field == 'brightness_aux_k' and float(value) == 0:
            flags.append('aux_brightness_zero_unresolved')
        elif field == 'frp_mw' and float(value) == 0:
            flags.append('frp_zero_source_reported')
    if _missing(record['fire_type']):
        flags.append('fire_type_missing')
    return tuple(sorted(flags))


def _sha(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def _checked_child(root, relative):
    if (not isinstance(relative, str) or not relative or '\\' in relative
            or ':' in relative):
        raise ScientificRecordError('QA source path must be a safe archive-relative path')
    rel = PurePosixPath(relative)
    if rel.is_absolute() or '..' in rel.parts or rel.as_posix() != relative:
        raise ScientificRecordError('QA source path must be a safe archive-relative path')
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ScientificRecordError('QA source path is unsafe or missing')
    return path


def _json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n',
                    encoding='utf-8', newline='\n')


class _DigestReader(io.RawIOBase):
    def __init__(self, stream, digest):
        self.stream = stream
        self.digest = digest

    def readable(self):
        return True

    def readinto(self, buffer):
        count = self.stream.readinto(buffer)
        if count:
            self.digest.update(memoryview(buffer)[:count])
        return count


def write_quality_sidecars(manifest_path, output_dir):
    """Atomically publish sparse QA CSVs bound to immutable canonical sources.

    One CSV is written for each accepted source/year; unflagged observations do
    not need duplicate scientific rows. The manifest records counts, flag
    definitions, accepted-manifest identity and each source/QA-file hash. Full
    archive integrity/spatial verification remains the caller's prerequisite.
    Existing non-QA directories and all accepted scientific inputs are protected.
    """
    manifest_path = Path(manifest_path).resolve()
    root = manifest_path.parent
    archive_hash = _sha(manifest_path)
    scientific_hash = _sha(__file__)
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('contract') != 'ghana-firms-research-archive-v1':
        raise ScientificRecordError('Unsupported archive for quality sidecars')
    requested = Path(output_dir)
    if requested.is_symlink():
        raise ScientificRecordError('QA destination must not be a symbolic link')
    destination = requested.resolve()
    if manifest_path.is_relative_to(destination):
        raise ScientificRecordError('QA destination overlaps the accepted archive')
    for name in ('canonical', 'artifacts', 'annual', 'geography'):
        if destination.is_relative_to(root / name):
            raise ScientificRecordError('QA destination overlaps scientific or annual data')
    if destination.exists():
        if not destination.is_dir():
            raise ScientificRecordError('QA destination must be a directory')
        if any(destination.iterdir()):
            prior = destination / 'qa-manifest.json'
            if not prior.is_file() or json.loads(prior.read_text(encoding='utf-8')).get('contract') != QA_CONTRACT:
                raise ScientificRecordError('Refusing to replace a non-QA destination')
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.parent / ('.' + destination.name + '.qa.lock')
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError:
        raise ScientificRecordError('Another QA publication holds the lock') from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        with tempfile.TemporaryDirectory(prefix='.qa-stage-', dir=destination.parent) as folder:
            stage = Path(folder) / 'qa'
            stage.mkdir()
            partitions = []
            identities = set()
            totals = Counter()
            records_total = flagged_total = 0
            for part in manifest['partitions']:
                source, year = part['source'], part['year']
                if (source not in _SOURCE_SPECS or isinstance(year, bool)
                        or not isinstance(year, int) or not 2000 <= year <= 9999
                        or (source, year) in identities):
                    raise ScientificRecordError('Invalid or duplicate QA source/year')
                identities.add((source, year))
                canonical = _checked_child(root, part['path'])
                if canonical.is_relative_to(destination):
                    raise ScientificRecordError('QA destination overlaps a canonical input')
                name = f'Ghana_{source}_{year}_qa.csv'
                output = stage / name
                counts = Counter()
                number = flagged = 0
                seen = set()
                digest = hashlib.sha256()
                with canonical.open('rb') as raw, output.open('w', encoding='utf-8', newline='') as target:
                    writer = csv.DictWriter(target, fieldnames=QA_FIELDS, lineterminator='\n')
                    writer.writeheader()
                    with io.TextIOWrapper(io.BufferedReader(_DigestReader(raw, digest)), encoding='utf-8-sig', newline='') as text:
                        for row in csv.DictReader(text):
                            if row.get('source_product') != source:
                                raise ScientificRecordError('QA row source differs from partition')
                            identifier = row.get('id', '')
                            if not re.fullmatch(r'gfa2:[0-9a-f]{64}', identifier) or identifier in seen:
                                raise ScientificRecordError('Invalid or duplicate QA observation identity')
                            seen.add(identifier)
                            flags = quality_flags(row)
                            number += 1
                            if flags:
                                flagged += 1
                                counts.update(flags)
                                writer.writerow({'observation_id': identifier, 'source': source,
                                                 'year': year, 'flags': ';'.join(flags)})
                if digest.hexdigest() != part['sha256']:
                    raise ScientificRecordError('Canonical source checksum mismatch during QA')
                if number != part['record_count']:
                    raise ScientificRecordError('QA canonical source count mismatch')
                records_total += number
                flagged_total += flagged
                totals.update(counts)
                partitions.append({'source': source, 'year': year, 'records': number,
                                   'flagged_records': flagged, 'flag_counts': dict(sorted(counts.items())),
                                   'canonical_path': part['path'], 'canonical_sha256': part['sha256'],
                                   'qa_path': name, 'qa_sha256': _sha(output)})
            if records_total != manifest['total_records']:
                raise ScientificRecordError('QA archive total mismatch')
            if _sha(manifest_path) != archive_hash:
                raise ScientificRecordError('Accepted manifest changed during QA publication')
            if _sha(__file__) != scientific_hash:
                raise ScientificRecordError('Scientific validation module changed during QA publication')
            result = {'contract': QA_CONTRACT, 'research_manifest_sha256': archive_hash,
                      'provenance': {'scientific_module_sha256': scientific_hash,
                                     'python_version': platform.python_version(),
                                     'python_implementation': platform.python_implementation()},
                      'records': records_total, 'flagged_records': flagged_total,
                      'flag_counts': dict(sorted(totals.items())), 'flag_definitions': FLAG_DEFINITIONS,
                      'policy': 'Preserve original observations and values; flags do not establish anomaly causes or exclude detections.',
                      'partitions': partitions}
            _json(stage / 'qa-manifest.json', result)
            backup = destination.parent / ('.' + destination.name + '.qa-backup-' + uuid.uuid4().hex)
            moved = False
            published = False
            try:
                if destination.exists():
                    destination.rename(backup)
                    moved = True
                stage.rename(destination)
                published = True
            except BaseException:
                if published:
                    shutil.rmtree(destination)
                if moved:
                    backup.rename(destination)
                raise
            retained_backup = None
            if moved:
                try:
                    shutil.rmtree(backup)
                except OSError:
                    retained_backup = str(backup)
    finally:
        lock.unlink(missing_ok=True)
    return {'passed': True, 'path': str(destination), 'partitions': len(partitions),
            'records': records_total, 'flagged_records': flagged_total,
            'flag_counts': dict(sorted(totals.items())), 'retained_backup': retained_backup}


def verify_quality_sidecars(manifest_path, output_dir):
    """Validate existing QA hashes and sparse flag semantics without writing.

Producer module identity remains historical provenance. This validator instead
recomputes every expected sparse row and count from accepted canonical inputs.
It creates no temporary directory, report, lock, or replacement QA artifact.
"""
    manifest_path = Path(manifest_path).resolve()
    root = manifest_path.parent
    destination = Path(output_dir).resolve()
    qa_path = destination / 'qa-manifest.json'
    qa_hash = _sha(qa_path)
    manifest_hash = _sha(manifest_path)
    archive = json.loads(manifest_path.read_text(encoding='utf-8'))
    report = json.loads(qa_path.read_text(encoding='utf-8'))
    if report.get('contract') != QA_CONTRACT or report.get('research_manifest_sha256') != manifest_hash:
        raise ScientificRecordError('QA manifest does not match the accepted archive')
    provenance = report.get('provenance', {})
    if (not isinstance(provenance, dict)
            or not re.fullmatch(r'[0-9a-f]{64}', str(provenance.get('scientific_module_sha256', '')))
            or not all(isinstance(provenance.get(k), str) and provenance[k] for k in ('python_version', 'python_implementation'))):
        raise ScientificRecordError('QA producer provenance is invalid')
    if report.get('flag_definitions') != FLAG_DEFINITIONS:
        raise ScientificRecordError('QA flag definitions differ from the supported semantics')
    expected = {(p['source'], p['year']): p for p in archive['partitions']}
    parts = report.get('partitions', [])
    if (len(parts) != len(expected)
            or {(p['source'], p['year']) for p in parts} != set(expected)):
        raise ScientificRecordError('QA source/year coverage mismatch')
    totals = Counter()
    records_total = flagged_total = 0
    expected_files = {'qa-manifest.json'}
    for part in parts:
        source, year = part['source'], part['year']
        original = expected[(source, year)]
        name = f'Ghana_{source}_{year}_qa.csv'
        if (part.get('canonical_path') != original['path']
                or part.get('canonical_sha256') != original['sha256']
                or part.get('qa_path') != name):
            raise ScientificRecordError('QA source identity differs from the accepted partition')
        canonical = _checked_child(root, original['path'])
        sparse = _checked_child(destination, name)
        expected_files.add(name)
        if _sha(sparse) != part.get('qa_sha256'):
            raise ScientificRecordError('QA sidecar checksum mismatch')
        counts = Counter()
        number = flagged = 0
        digest = hashlib.sha256()
        with canonical.open('rb') as raw, sparse.open(encoding='utf-8-sig', newline='') as sidecar:
            reader = csv.DictReader(sidecar)
            if reader.fieldnames != list(QA_FIELDS):
                raise ScientificRecordError('QA sidecar schema mismatch')
            with io.TextIOWrapper(io.BufferedReader(_DigestReader(raw, digest)), encoding='utf-8-sig', newline='') as text:
                for row in csv.DictReader(text):
                    number += 1
                    flags = quality_flags(row)
                    if flags:
                        flagged += 1
                        counts.update(flags)
                        wanted = {'observation_id': row['id'], 'source': source,
                                  'year': str(year), 'flags': ';'.join(flags)}
                        if next(reader, None) != wanted:
                            raise ScientificRecordError('QA sidecar flags differ from accepted observations')
            if next(reader, None) is not None:
                raise ScientificRecordError('QA sidecar contains undeclared observations')
        if digest.hexdigest() != original['sha256']:
            raise ScientificRecordError('Canonical source checksum mismatch during QA validation')
        if (number != original['record_count'] or part.get('records') != number
                or part.get('flagged_records') != flagged or part.get('flag_counts') != dict(sorted(counts.items()))):
            raise ScientificRecordError('QA partition counts differ from accepted observations')
        records_total += number
        flagged_total += flagged
        totals.update(counts)
    actual_files = set()
    for path in destination.rglob('*'):
        if path.is_symlink():
            raise ScientificRecordError('QA directory contains an unexpected symbolic link')
        if path.is_file():
            actual_files.add(path.relative_to(destination).as_posix())
    if actual_files != expected_files:
        raise ScientificRecordError('QA directory contains missing or undeclared files')
    if (records_total != archive['total_records'] or report.get('records') != records_total
            or report.get('flagged_records') != flagged_total or report.get('flag_counts') != dict(sorted(totals.items()))):
        raise ScientificRecordError('QA aggregate counts differ from accepted observations')
    if _sha(manifest_path) != manifest_hash or _sha(qa_path) != qa_hash:
        raise ScientificRecordError('Accepted archive or QA manifest changed during validation')
    return {'passed': True, 'partitions': len(parts), 'records': records_total,
            'flagged_records': flagged_total, 'flag_counts': dict(sorted(totals.items())),
            'qa_manifest_sha256': qa_hash, 'producer_provenance': provenance,
            'semantics_recomputed': True}
