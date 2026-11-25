"""Acquisition identity and archive-coverage contracts, independent of measurements.

A plan is an acquisition request, not evidence that its date interval was read.
Receipt validation binds that request to the retained source and, for the Area
API, the complete contiguous set of checked batches. Retrieval timestamps are
provenance but do not change an acquisition identity when scope and bytes agree.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
import hashlib
import json
from pathlib import Path
import re


_SHA256 = re.compile(r"[0-9a-f]{64}")
_SCOPE_FIELDS = (
    'source', 'year', 'filename', 'checked_start', 'checked_end',
    'provider_updated', 'size_bytes', 'catalogue_sha256', 'availability',
    'coverage_basis',
)


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _date(value, label):
    _require(isinstance(value, str), f'{label} must be an ISO date')
    try:
        parsed = date.fromisoformat(value)
    except ValueError:
        raise ValueError(f'{label} must be an ISO date') from None
    _require(parsed.isoformat() == value, f'{label} must use YYYY-MM-DD')
    return parsed


def _year(value):
    _require(isinstance(value, int) and not isinstance(value, bool)
             and 2000 <= value <= 9999, 'Invalid acquisition year')
    return value


def _interval(record, *, prefix='checked_'):
    year = _year(record.get('year'))
    start = _date(record.get(prefix + 'start'), 'Coverage start')
    end = _date(record.get(prefix + 'end'), 'Coverage end')
    _require(start <= end and start.year == year and end.year == year,
             'Coverage interval must be ordered within its annual partition')
    return start, end


def _inside(root, relative, label):
    _require(isinstance(relative, str) and relative and '\\' not in relative and ':' not in relative,
             f'Invalid {label} path')
    rel = Path(relative)
    _require(not rel.is_absolute() and '..' not in rel.parts,
             f'Unsafe {label} path')
    path = (root / rel).resolve()
    _require(path.is_relative_to(root) and path.is_file(),
             f'Missing or unsafe {label} file')
    return path


def _binding(item, receipt, field):
    """Optional historical fixture fields are allowed only when both omit them."""
    _require((field in item) == (field in receipt),
             f'Acquisition receipt/plan metadata differs: {field}')
    if field in item:
        _require(item[field] == receipt[field],
                 f'Acquisition receipt/plan metadata differs: {field}')


def _api_batches(item, receipt, raw_path, downloads_root):
    batches = receipt.get('batches')
    _require(isinstance(batches, list) and bool(batches),
             'API acquisition receipt must contain checked batches')
    start, end = _interval(item)
    cursor = start
    identities = []
    seen = set()
    with raw_path.open(encoding='utf-8-sig', newline='') as annual_stream:
        annual = csv.DictReader(annual_stream)
        _require(annual.fieldnames and len(set(annual.fieldnames)) == len(annual.fieldnames),
                 'Invalid annual API CSV header')
        for entry in batches:
            _require(isinstance(entry, dict), 'Invalid API batch receipt')
            path = _inside(downloads_root, entry.get('file'), 'API batch')
            _require(path not in seen, 'Repeated API batch file')
            seen.add(path)
            own_path = path.with_suffix('.receipt.json')
            _require(own_path.is_file(), 'API batch receipt file is missing')
            own = json.loads(own_path.read_text(encoding='utf-8'))
            _require(own == {k: v for k, v in entry.items() if k != 'file'},
                     'Embedded API batch receipt differs from its retained receipt')
            _require(entry.get('source') == item['source']
                     and entry.get('processing_status') == 'SP',
                     'API batch source/processing status mismatch')
            a = _date(entry.get('checked_start'), 'API batch start')
            b = _date(entry.get('checked_end'), 'API batch end')
            _require(a == cursor and a <= b <= end and (b - a).days < 5,
                     'API batches must cover the requested interval contiguously in at most five-day windows')
            digest = entry.get('sha256')
            _require(isinstance(digest, str) and _SHA256.fullmatch(digest)
                     and _sha(path) == digest, 'API batch checksum mismatch')
            rows_expected = entry.get('rows')
            _require(isinstance(rows_expected, int) and not isinstance(rows_expected, bool)
                     and rows_expected >= 0, 'API batch row count must be nonnegative')
            if 'retrieved_utc' in entry:
                try:
                    retrieved = datetime.fromisoformat(entry['retrieved_utc'])
                except (ValueError, TypeError):
                    raise ValueError('Invalid API batch retrieval timestamp') from None
                _require(retrieved.tzinfo is not None, 'API batch retrieval timestamp must be timezone-aware')
            count = 0
            with path.open(encoding='utf-8-sig', newline='') as batch_stream:
                batch = csv.DictReader(batch_stream)
                _require(batch.fieldnames == annual.fieldnames and 'acq_date' in batch.fieldnames,
                         'API batch/annual CSV schema mismatch')
                for row in batch:
                    d = _date(row.get('acq_date'), 'API acquisition date')
                    _require(a <= d <= b and None not in row,
                             'API observation is outside its checked batch or malformed')
                    _require(next(annual, None) == row,
                             'Annual API CSV does not equal its checked batch concatenation')
                    count += 1
            _require(count == rows_expected, 'API batch row count mismatch')
            identities.append({k: entry[k] for k in (
                'file', 'source', 'processing_status', 'checked_start', 'checked_end', 'sha256', 'rows')})
            cursor = b + timedelta(days=1)
        _require(next(annual, None) is None, 'Annual API CSV contains rows outside the checked batches')
    _require(cursor == end + timedelta(days=1), 'API batch coverage does not reach the requested end')
    return identities


def validate_acquisition_receipt(item, receipt, raw_path, downloads_root):
    """Return a stable, independently checked acquisition identity.

    Both inputs must describe the same checked interval and source. Metadata
    absent from both historical synthetic fixtures remains optional; a field
    present on either side cannot silently be omitted or changed on the other.
    No key-bearing URL is included in the returned identity.
    """
    _require(isinstance(item, dict) and isinstance(receipt, dict), 'Invalid acquisition receipt/plan')
    _require(item.get('status') == receipt.get('status') == 'available',
             'Acquisition receipt/plan must both declare an available source')
    from .core import SOURCES
    _require(isinstance(item.get('source'), str) and item['source'] in SOURCES,
             'Unsupported acquisition source')
    start, _ = _interval(item)
    _require(start >= max(date(item['year'], 1, 1), _date(SOURCES[item['source']]['start'], 'Source effective start')),
             'Acquisition coverage precedes the source effective start')
    for field in _SCOPE_FIELDS:
        _binding(item, receipt, field)
    method = item.get('method', 'annual')
    _require(method in ('annual', 'api_sp') and receipt.get('method', 'annual') == method,
             'Acquisition receipt/plan method differs')
    if 'url' in item or 'url' in receipt:
        # Generated provider requests always carry their provider metadata.
        # Only URL-free historical synthetic fixtures may omit it on both sides.
        required = ('provider_updated', 'coverage_basis') + (
            ('availability',) if method == 'api_sp' else ('size_bytes', 'catalogue_sha256'))
        for field in required:
            _require(field in item and item[field] is not None and field in receipt and receipt[field] is not None,
                     f'Production acquisition provider metadata is missing: {field}')
    if 'processing_status' in receipt:
        _require(receipt['processing_status'] == 'SP', 'Acquisition receipt is not SP')
    root = Path(downloads_root).resolve()
    filename = item.get('filename')
    _require(isinstance(filename, str) and Path(filename).name == filename,
             'Acquisition filename must be a basename')
    raw_path = Path(raw_path).resolve()
    _require(raw_path == _inside(root, filename, 'acquisition source'),
             'Acquisition receipt points to a different source file')
    sourcehash = _sha(raw_path)
    _require(receipt.get('sha256') == sourcehash, 'Downloaded source checksum mismatch')
    if 'size_bytes' in item:
        size = item['size_bytes']
        _require(isinstance(size, int) and not isinstance(size, bool) and size >= 0
                 and raw_path.stat().st_size == size, 'Catalogue/source byte size mismatch')
    batches = []
    if method == 'api_sp':
        availability = item.get('availability')
        if availability is not None:
            _require(isinstance(availability, dict) and availability.get('data_id') == item['source'],
                     'API source availability identity mismatch')
            minimum = _date(availability.get('min_date'), 'API available start')
            maximum = _date(availability.get('max_date'), 'API available end')
            start, end = _interval(item)
            _require(minimum <= start <= end <= maximum, 'API interval exceeds declared source availability')
        batches = _api_batches(item, receipt, raw_path, root)
    elif 'catalogue_sha256' in item:
        catalogue = _inside(root, 'yearly_summary_files.txt', 'NASA catalogue')
        _require(_sha(catalogue) == item['catalogue_sha256'], 'Acquisition catalogue checksum mismatch')
        with catalogue.open(encoding='utf-8-sig', newline='') as stream:
            matches = [row for row in csv.DictReader(stream) if row.get('filename') == filename]
        _require(len(matches) == 1, 'Acquisition filename is not unique in the NASA catalogue')
        selected = matches[0]
        if 'size_bytes' in item:
            try:
                selected_size = int(selected.get('size', ''))
            except (TypeError, ValueError):
                raise ValueError('Acquisition catalogue size is invalid') from None
            _require(selected_size == item['size_bytes'], 'Acquisition catalogue size differs')
        if 'provider_updated' in item:
            _require(selected.get('updated') == item['provider_updated'], 'Acquisition catalogue update differs')
    scope = {k: item[k] for k in _SCOPE_FIELDS if k in item}
    scope.update(method=method, source_sha256=sourcehash)
    payload = {'contract': 'ghana-firms-acquisition-v1', 'scope': scope, 'batches': batches}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode('utf-8')).hexdigest()
    return {'identity_contract': payload['contract'], 'acquisition_sha256': digest,
            'source_sha256': sourcehash, 'coverage': scope, 'batches': batches,
            'batch_count': len(batches)}


def validate_embedded_acquisition(acquisition, partition=None):
    """Check stored acquisition identity and its linkage without source downloads.

    This is an integrity/linkage check, not independent NASA authentication.
    Actual retained receipt, catalogue and batch validation is performed by
    :func:`validate_acquisition_receipt` before admission or cache reuse.
    """
    _require(isinstance(acquisition, dict)
             and acquisition.get('identity_contract') == 'ghana-firms-acquisition-v1',
             'Invalid embedded acquisition contract')
    scope = acquisition.get('coverage')
    batches = acquisition.get('batches')
    _require(isinstance(scope, dict) and isinstance(batches, list),
             'Embedded acquisition scope/batches are missing')
    from .core import SOURCES
    _require(isinstance(scope.get('source'), str) and scope['source'] in SOURCES,
             'Invalid embedded acquisition source')
    start, end = _interval(scope)
    _require(start >= max(date(scope['year'], 1, 1), _date(SOURCES[scope['source']]['start'], 'Source effective start')),
             'Embedded acquisition coverage precedes the source effective start')
    sourcehash = acquisition.get('source_sha256')
    _require(isinstance(sourcehash, str) and _SHA256.fullmatch(sourcehash)
             and scope.get('source_sha256') == sourcehash,
             'Embedded acquisition source hash differs')
    method = scope.get('method')
    _require(method in ('annual', 'api_sp'), 'Invalid embedded acquisition method')
    _require(type(acquisition.get('batch_count')) is int
             and acquisition['batch_count'] == len(batches),
             'Embedded acquisition batch count differs')
    if method == 'annual':
        _require(not batches, 'Annual acquisition must not claim API batches')
    else:
        _require(bool(batches), 'API acquisition must retain batch identities')
        cursor = start
        seen = set()
        for item in batches:
            _require(isinstance(item, dict), 'Invalid embedded API batch')
            filename = item.get('file')
            _require(isinstance(filename, str) and filename and '\\' not in filename and ':' not in filename,
                     'Invalid embedded API batch filename')
            rel = Path(filename)
            _require(not rel.is_absolute() and '..' not in rel.parts and filename not in seen,
                     'Unsafe or repeated embedded API batch filename')
            seen.add(filename)
            a = _date(item.get('checked_start'), 'Embedded API batch start')
            b = _date(item.get('checked_end'), 'Embedded API batch end')
            _require(a == cursor and a <= b <= end and (b - a).days < 5,
                     'Embedded API batches do not cover the checked interval')
            _require(item.get('source') == scope['source'] and item.get('processing_status') == 'SP',
                     'Embedded API batch source/status differs')
            _require(isinstance(item.get('sha256'), str) and _SHA256.fullmatch(item['sha256'])
                     and type(item.get('rows')) is int and item['rows'] >= 0,
                     'Invalid embedded API batch hash/count')
            cursor = b + timedelta(days=1)
        _require(cursor == end + timedelta(days=1), 'Embedded API batch coverage is incomplete')
    payload = {'contract': acquisition['identity_contract'], 'scope': scope, 'batches': batches}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                       allow_nan=False).encode('utf-8')).hexdigest()
    _require(acquisition.get('acquisition_sha256') == digest,
             'Embedded acquisition checksum mismatch')
    if partition is not None:
        _require(scope['source'] == partition.get('source') and scope['year'] == partition.get('year')
                 and start.isoformat() == partition.get('coverage_start')
                 and end.isoformat() == partition.get('coverage_end')
                 and sourcehash == partition.get('source_sha256'),
                 'Embedded acquisition identity differs from its partition')
    return acquisition


def validate_archive_obligations(manifest, *, check_declared=True):
    """Reconstruct available partition obligations and completeness from scope."""
    from .core import SOURCES
    _require(isinstance(manifest, dict), 'Invalid archive manifest')
    sources = manifest.get('requested_sources')
    years = manifest.get('years')
    _require(isinstance(sources, list) and bool(sources)
             and all(isinstance(s, str) and s in SOURCES for s in sources),
             'Invalid archive source selection')
    _require(len(set(sources)) == len(sources), 'Repeated archive source')
    _require(isinstance(years, list) and bool(years), 'Invalid archive year selection')
    for year in years:
        _year(year)
    _require(len(set(years)) == len(years), 'Repeated archive year')
    _require(manifest.get('processing_status') == 'SP', 'Archive processing status must be SP')
    expected = {(s, y) for s in sources for y in years}
    coverage = manifest.get('source_coverage')
    partitions = manifest.get('partitions')
    _require(isinstance(coverage, list) and isinstance(partitions, list),
             'Archive coverage and partitions must be lists')
    indexed = {}
    for item in coverage:
        _require(isinstance(item, dict), 'Invalid source coverage entry')
        _require(isinstance(item.get('source'), str) and item['source'] in SOURCES,
                 'Invalid source coverage identity')
        key = (item.get('source'), _year(item.get('year')))
        _require(key in expected and key not in indexed, 'Missing, repeated or unexpected coverage obligation')
        indexed[key] = item
    _require(set(indexed) == expected, 'Archive source/year coverage grid is incomplete')
    available = {}
    complete_available = True
    complete_requested = True
    for (source, year), item in indexed.items():
        status = item.get('status')
        _require(status in ('available', 'unavailable', 'structurally_unavailable'),
                 'Unknown source coverage status')
        launch = _date(SOURCES[source]['start'], 'Source effective start')
        year_start, year_end = date(year, 1, 1), date(year, 12, 31)
        structural = year_end < launch
        _require((status == 'structurally_unavailable') == structural,
                 'Structural source coverage disagrees with its effective start')
        if status != 'available':
            _require(item.get('checked_start') is None and item.get('checked_end') is None,
                     'Unavailable coverage must not claim a checked interval')
            if status == 'unavailable':
                complete_available = False
                complete_requested = False
            continue
        start, end = _interval(item)
        expected_start = max(year_start, launch)
        _require(start >= expected_start, 'Coverage precedes the source effective start')
        partial = start != year_start or end != year_end
        if 'partial_year' in item:
            _require(type(item['partial_year']) is bool and item['partial_year'] == partial,
                     'Coverage partial-year flag is inconsistent')
        if item.get('processing_status', 'SP') != 'SP':
            raise ValueError('Available source coverage must be SP')
        complete_requested = complete_requested and start == expected_start and end == year_end
        available[(source, year)] = item
    seen = set()
    total = 0
    for partition in partitions:
        _require(isinstance(partition, dict), 'Invalid archive partition')
        _require(isinstance(partition.get('source'), str) and partition['source'] in SOURCES,
                 'Invalid archive partition source')
        key = (partition.get('source'), _year(partition.get('year')))
        _require(key in available and key not in seen,
                 'Missing, repeated or unexpected available source/year partition')
        seen.add(key)
        cov = available[key]
        _require(partition.get('processing_status') == 'SP', 'Partition processing status must be SP')
        _require(partition.get('coverage_start') == cov['checked_start']
                 and partition.get('coverage_end') == cov['checked_end'],
                 'Partition and source coverage intervals differ')
        stored = partition.get('coverage')
        _require(isinstance(stored, dict), 'Partition acquisition coverage is missing')
        for field in ('source', 'year', 'status', 'checked_start', 'checked_end',
                      'provider_updated', 'filename', 'method', 'catalogue_sha256',
                      'size_bytes', 'availability', 'source_sha256', 'partial_year'):
            _binding(cov, stored, field)
        if 'source_sha256' in cov:
            _require(partition.get('source_sha256') == cov['source_sha256'],
                     'Partition source hash and coverage source hash differ')
        count = partition.get('record_count')
        _require(isinstance(count, int) and not isinstance(count, bool) and count >= 0,
                 'Invalid partition record count')
        total += count
        if 'acquisition' in partition:
            validate_embedded_acquisition(partition['acquisition'], partition)
    _require(seen == set(available), 'An available source/year is missing its explicit partition')
    _require(type(manifest.get('total_records')) is int and manifest['total_records'] == total,
             'Archive declared record total is inconsistent')
    if check_declared:
        for field, expected_value in [('complete_available_sp_scope', complete_available),
                                      ('complete_requested_scope', complete_requested)]:
            _require(type(manifest.get(field)) is bool and manifest[field] == expected_value,
                     f'Archive completeness flag is inconsistent: {field}')
    return {'complete_available_sp_scope': complete_available,
            'complete_requested_scope': complete_requested,
            'requested_source_years': len(expected), 'available_partitions': len(available),
            'structurally_unavailable': sum(x['status'] == 'structurally_unavailable' for x in coverage),
            'unavailable': sum(x['status'] == 'unavailable' for x in coverage), 'total_records': total}
