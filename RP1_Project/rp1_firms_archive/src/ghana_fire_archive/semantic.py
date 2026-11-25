"""Reconstruct canonical-to-shapefile semantics independently of file hashes.

Checks are read-only. A matching checksum cannot substitute for checking the
declared field projection, point assignment and source observation identity.
"""
from __future__ import annotations

import csv
from contextlib import contextmanager, ExitStack
from datetime import date
import hashlib
import io
import json
import math
from pathlib import Path
import re
import struct
import sqlite3
import tempfile
from zipfile import ZipFile

import shapefile


EXTENSIONS = ('.shp', '.shx', '.dbf', '.prj', '.cpg')
COMPONENT_COPY_BYTES = 1024 * 1024
PHYSICAL_RECORD_BATCH = 16384


def validate_point_components(shp, shx, record_count):
    """Reconcile the physical POINT records and their index, not just DBF count.

    A 2D POINT has a 20-byte body and an 8-byte record header. Its SHX index
    entry is eight bytes. Checking these bytes prevents a correct-looking
    index from hiding additional SHP records that readers might ignore.
    """
    from .core import ArchiveError

    if isinstance(record_count, bool) or not isinstance(record_count, int) or record_count < 0:
        raise ArchiveError('Invalid shapefile physical record count')
    def stream(payload):
        return io.BytesIO(payload) if isinstance(payload, (bytes, bytearray, memoryview)) else payload
    shp, shx = stream(shp), stream(shx)
    for payload, size, extension in ((shp, 28, '.shp'), (shx, 8, '.shx')):
        payload.seek(0, 2)
        length = payload.tell()
        if length != 100 + size * record_count:
            raise ArchiveError('Shapefile physical component length/count mismatch: ' + extension)
        payload.seek(0)
        header = payload.read(100)
        if struct.unpack_from('>i', header, 24)[0] * 2 != length:
            raise ArchiveError('Shapefile declared component length mismatch: ' + extension)
        if (struct.unpack_from('>i', header, 0)[0] != 9994
                or struct.unpack_from('<ii', header, 28) != (1000, shapefile.POINT)):
            raise ArchiveError('Shapefile component header is not a standard POINT file: ' + extension)
    for first in range(0, record_count, PHYSICAL_RECORD_BATCH):
        count = min(PHYSICAL_RECORD_BATCH, record_count - first)
        shape_block, index_block = shp.read(count * 28), shx.read(count * 8)
        if len(shape_block) != count * 28 or len(index_block) != count * 8:
            raise ArchiveError('Truncated shapefile physical record batch')
        for offset in range(count):
            index = first + offset
            position = 100 + 28 * index
            if (struct.unpack_from('>ii', index_block, 8 * offset) != (position // 2, 10)
                    or struct.unpack_from('>ii', shape_block, 28 * offset) != (index + 1, 10)
                    or struct.unpack_from('<i', shape_block, 28 * offset + 8)[0] != shapefile.POINT):
                raise ArchiveError('Shapefile POINT record/index framing mismatch')
    shp.seek(0)
    shx.seek(0)


def validate_declarations(archive, stem):
    """Check exact small declarations without allocating an untrusted member."""
    from .core import ArchiveError, PRJ

    for extension, expected in (('.prj', PRJ.encode('utf-8')), ('.cpg', b'UTF-8')):
        name = stem + extension
        if archive.getinfo(name).file_size != len(expected):
            raise ArchiveError('Invalid shapefile CRS/encoding declaration')
        with archive.open(name) as stream:
            if stream.read(len(expected) + 1) != expected:
                raise ArchiveError('Invalid shapefile CRS/encoding declaration')


@contextmanager
def point_reader(archive, stem, record_count):
    """Yield a reader backed by seekable disk files and bounded ZIP copies.

    Seeking compressed ZIP streams for every DBF record can repeatedly inflate
    the member. Temporary files provide efficient random access without holding
    a whole annual SHP, SHX or DBF component in RAM. Every member is read to EOF,
    retaining ZIP CRC validation, and every POINT/index record is checked.
    """
    with ExitStack() as stack:
        components = {}
        for extension in ('.shp', '.shx', '.dbf'):
            target = stack.enter_context(tempfile.TemporaryFile(mode='w+b'))
            with archive.open(stem + extension) as source:
                while block := source.read(COMPONENT_COPY_BYTES):
                    target.write(block)
            target.seek(0)
            components[extension] = target
        validate_point_components(components['.shp'], components['.shx'], record_count)
        reader = shapefile.Reader(shp=components['.shp'], shx=components['.shx'],
                                  dbf=components['.dbf'], encoding='utf-8')
        try:
            yield reader
        finally:
            reader.close()


def validate_dbf_schema(reader, fields=None):
    """Require field names, types, byte widths and numeric precision."""
    from .core import ArchiveError, shape_fields

    fields = shape_fields() if fields is None else fields
    observed = [tuple(field) for field in reader.fields[1:]]
    expected = [(name, kind, width, decimals)
                for _, name, kind, width, decimals in fields]
    if observed != expected:
        raise ArchiveError('Shapefile DBF field names/types/widths/precision mismatch')


def _family(archive, expected_stem=None):
    """Check one flat shapefile family and any permitted metadata sidecars."""
    from .core import ArchiveError

    names = archive.namelist()
    if len(names) != len(set(names)) or len(names) != len({n.casefold() for n in names}):
        raise ArchiveError('Shapefile archive contains duplicate members')
    if any(Path(name).name != name or '\\' in name or ':' in name for name in names):
        raise ArchiveError('Shapefile archive contains unsafe member paths')
    shapes = [name for name in names if name.endswith('.shp')]
    if len(shapes) != 1:
        raise ArchiveError('Shapefile archive must contain one shapefile family')
    stem = shapes[0][:-4]
    family = {stem + ext for ext in EXTENSIONS}
    permitted = family if expected_stem is not None else family | {'fields.json', 'provenance.json'}
    if not family <= set(names) or not set(names) <= permitted:
        raise ArchiveError('Shapefile archive has missing or unexpected components')
    if expected_stem is not None and stem != expected_stem:
        raise ArchiveError('Shapefile archive basename does not match its source/year')
    return stem


def verify_export_payload(accepted_zip, readable_zip, source, year):
    """Check that renaming/packaging did not alter any accepted component."""
    from .core import ArchiveError, annual_stem

    with ZipFile(accepted_zip) as original, ZipFile(readable_zip) as exported:
        old_stem = _family(original)
        new_stem = _family(exported, annual_stem(source, year))
        for extension in EXTENSIONS:
            # Stream to bound memory even for large annual DBF components.
            hashes = []
            for archive, member in ((original, old_stem + extension),
                                    (exported, new_stem + extension)):
                digest = hashlib.sha256()
                with archive.open(member) as stream:
                    for block in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(block)
                hashes.append(digest.digest())
            if hashes[0] != hashes[1]:
                raise ArchiveError('Annual export component differs from accepted artifact: ' + extension)


def _projected_attribute(value, raw, kind, width, decimals, field_name):
    """Compare the actual DBF value to the writer's declared field projection."""
    from .core import ArchiveError

    if kind == 'C':
        expected = str(raw)
        if len(expected.encode('utf-8')) > width:
            raise ArchiveError('Canonical text exceeds DBF field width: ' + field_name)
        # DBF character padding does not preserve trailing spaces.
        if value != expected.rstrip(' \x00'):
            raise ArchiveError('Shapefile scientific attribute mismatch: ' + field_name)
        return
    if raw == '':
        if value is not None:
            raise ArchiveError('Shapefile missing numeric attribute mismatch: ' + field_name)
        return
    if value is None:
        raise ArchiveError('Shapefile numeric attribute is unexpectedly missing: ' + field_name)
    expected = float(raw)
    if not math.isfinite(expected) or not math.isfinite(float(value)):
        raise ArchiveError('Nonfinite shapefile numeric attribute: ' + field_name)
    # export_shape hands a float to pyshp, whose F writer formats that float to
    # the declared number of decimal places. Check this projection exactly;
    # a relative tolerance would incorrectly admit large-value discrepancies.
    rendered = f'{expected:.{decimals}f}'
    if len(rendered.encode('ascii')) > width:
        raise ArchiveError('Canonical numeric value exceeds DBF field width: ' + field_name)
    if float(value) != float(rendered):
        raise ArchiveError('Shapefile scientific attribute mismatch: ' + field_name)


@contextmanager
def canonical_index():
    """Keep a partition's identity/payload index on temporary disk, not in RAM."""
    with tempfile.TemporaryDirectory(prefix='firms-canonical-check-') as directory:
        connection = sqlite3.connect(str(Path(directory) / 'canonical.sqlite'))
        try:
            # This database is disposable verification scratch, never a source
            # or accepted output. Bound its page cache and avoid a RAM journal.
            connection.execute('PRAGMA cache_size=-2048')
            connection.execute('PRAGMA mmap_size=0')
            connection.execute('PRAGMA temp_store=FILE')
            connection.execute('PRAGMA journal_mode=OFF')
            connection.execute('PRAGMA synchronous=OFF')
            connection.execute('CREATE TABLE observations (id TEXT PRIMARY KEY, payload TEXT NOT NULL, matched INTEGER NOT NULL DEFAULT 0)')
            yield connection
        finally:
            connection.close()


def verify_partition(csvpath, zippath, record_count, source, year, geography=None,
                     *, coverage_start=None, coverage_end=None,
                     source_sha256=None, strict_family=True):
    """Verify every canonical record, all DBF values and actual point assignment.

    ``geography`` is an accepted-output Geography-compatible object with an
    ``assign`` method. It must be supplied by the archive verifier. It is
    optional only for isolated callers that explicitly need projection checks.
    Source data, observation IDs and original values are never changed.
    """
    from .core import ArchiveError, FIELDS, PRJ, SOURCES, annual_stem, number, observation_id, shape_fields
    from .scientific import validate_scientific_record

    csvpath, zippath = Path(csvpath), Path(zippath)
    if source not in SOURCES or isinstance(year, bool) or not isinstance(year, int):
        raise ArchiveError('Invalid canonical source/year partition')
    if isinstance(record_count, bool) or not isinstance(record_count, int) or record_count < 0:
        raise ArchiveError('Invalid canonical partition count')
    spec = SOURCES[source]
    start = coverage_start or f'{year}-01-01'
    end = coverage_end or f'{year}-12-31'
    date.fromisoformat(start)
    date.fromisoformat(end)
    if start > end or start[:4] != str(year) or end[:4] != str(year):
        raise ArchiveError('Invalid source coverage interval')
    canonical_count = 0
    batch = []

    def check_spatial():
        if not batch or geography is None:
            batch.clear()
            return
        # Keep only this bounded batch in memory. Copies preserve the saved
        # labels for independent comparison after assign fills its own labels.
        originals = {row['id']: row for row in batch}
        requested = [dict(row, latitude=float(row['latitude']), longitude=float(row['longitude']))
                     for row in batch]
        assigned, outside, unassigned = geography.assign(requested)
        if outside or unassigned or len(assigned) != len(batch):
            raise ArchiveError('Canonical point is outside accepted Ghana/district geography')
        for row in assigned:
            original = originals.get(row['id'])
            if original is None or (row['district_id'], row['zone_id']) != (original['district_id'], original['zone_id']):
                raise ArchiveError('Canonical point district/zone assignment mismatch')
        batch.clear()

    with canonical_index() as canonical:
        with csvpath.open(encoding='utf-8', newline='') as stream:
            rows = csv.DictReader(stream)
            if rows.fieldnames != FIELDS:
                raise ArchiveError('Canonical CSV field schema mismatch')
            for row in rows:
                if None in row or any(value is None for value in row.values()):
                    raise ArchiveError('Malformed canonical CSV row')
                if row['processing_status'] != 'SP' or row['source_product'] != source:
                    raise ArchiveError('Invalid prepared row identity/status')
                if row['source_version'] not in spec['versions'] or row['platform'] not in spec['platforms']:
                    raise ArchiveError('Invalid canonical source version/platform')
                day = row['acq_date']
                if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', day) or not start <= day <= end:
                    raise ArchiveError('Canonical date is outside source coverage')
                date.fromisoformat(day)
                if not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', row['time_utc']):
                    raise ArchiveError('Invalid canonical UTC time')
                lat, lon = number(row['latitude']), number(row['longitude'])
                if not -90 <= lat <= 90 or not -180 <= lon <= 180:
                    raise ArchiveError('Canonical coordinates outside WGS84 bounds')
                if not re.fullmatch(r'[0-9a-f]{64}', row['source_file_sha256']):
                    raise ArchiveError('Invalid canonical source-file hash')
                if source_sha256 is not None and row['source_file_sha256'] != source_sha256:
                    raise ArchiveError('Canonical source-file hash differs from partition provenance')
                try:
                    validate_scientific_record(row)
                except ValueError as exc:
                    raise ArchiveError(str(exc)) from None
                if row['id'] != observation_id(source, row['platform'], day, row['time_utc'], lat, lon, row):
                    raise ArchiveError('Invalid canonical observation identity')
                try:
                    canonical.execute('INSERT INTO observations(id,payload) VALUES (?,?)',
                        (row['id'], json.dumps(row, ensure_ascii=False, separators=(',', ':'))))
                except sqlite3.IntegrityError:
                    raise ArchiveError('Invalid prepared row identity/status') from None
                canonical_count += 1
                batch.append(row)
                if len(batch) >= 10000:
                    check_spatial()
            check_spatial()
        if canonical_count != record_count:
            raise ArchiveError('Canonical partition count mismatch')
        canonical.commit()

        with ZipFile(zippath) as archive:
            stem = _family(archive, annual_stem(source, year) if strict_family else None)
            validate_declarations(archive, stem)
            with point_reader(archive, stem, record_count) as reader:
                _verify_shape_records(reader, canonical, canonical_count, shape_fields())
    return {'records': canonical_count, 'attributes_checked': len(shape_fields()),
            'spatial_assignment_checked': geography is not None}


def _verify_shape_records(reader, canonical, record_count, fields):
    """Compare every geometry/value through the disk-backed identity index."""
    from .core import ArchiveError

    if (reader.shapeType != shapefile.POINT or len(reader) != record_count
            or reader.numShapes != record_count):
        raise ArchiveError('Shapefile/CSV point type or count mismatch')
    validate_dbf_schema(reader, fields)
    matched_count = 0
    for feature in reader.iterShapeRecords():
        identifier = feature.record['obs_id']
        if not isinstance(identifier, str):
            raise ArchiveError('Shapefile/CSV identity mismatch')
        stored = canonical.execute('SELECT payload,matched FROM observations WHERE id=?', (identifier,)).fetchone()
        if stored is None or stored[1]:
            raise ArchiveError('Shapefile/CSV identity mismatch')
        row = json.loads(stored[0])
        if feature.shape.shapeType != shapefile.POINT or len(feature.shape.points) != 1:
            raise ArchiveError('Shapefile contains a non-point observation')
        if tuple(feature.shape.points[0]) != (float(row['longitude']), float(row['latitude'])):
            raise ArchiveError('Shapefile/CSV point coordinate mismatch')
        for original_name, dbf_name, kind, width, decimals in fields:
            _projected_attribute(feature.record[dbf_name], row[original_name],
                                 kind, width, decimals, dbf_name)
        canonical.execute('UPDATE observations SET matched=1 WHERE id=?', (identifier,))
        matched_count += 1
    # Unique canonical IDs and a once-only match for every shape establish the
    # same complete identity-set equality without storing either annual set.
    if matched_count != record_count:
        raise ArchiveError('Shapefile/CSV identity mismatch')
