"""Publish readable annual Earth Engine upload ZIPs from an accepted archive."""
from __future__ import annotations

import csv
import io
import json
import os
from pathlib import Path
import shutil
import tempfile
import uuid
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED, ZIP_STORED

import shapefile

from .core import (ArchiveError, PRJ, SENSOR_FOLDERS, annual_stem, sha,
                   shape_fields, verify, write_json, zip_files)
from .semantic import validate_dbf_schema, validate_declarations, point_reader, verify_export_payload

EXTENSIONS = ('.shp', '.shx', '.dbf', '.prj', '.cpg')
INDEX_FIELDS = ['source', 'year', 'records', 'checked_start', 'checked_end',
                'annual_shapefile_zip', 'sha256', 'gee_upload_ready']


def checked_path(root, relative):
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ArchiveError('Accepted archive contains an unsafe or missing artifact path')
    return path


def validate_upload_zip(path, source, year, records):
    """Check the local Earth Engine upload format; no asset is uploaded here."""
    stem = annual_stem(source, year)
    with ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != 5 or set(names) != {stem + ext for ext in EXTENSIONS} or archive.testzip():
            raise ArchiveError('Upload ZIP must contain exactly one flat, matching shapefile family')
        validate_declarations(archive, stem)
        with point_reader(archive, stem, records) as reader:
            if (reader.shapeType != shapefile.POINT or len(reader) != records
                    or reader.numShapes != records or records > 100_000_000):
                raise ArchiveError('Upload ZIP has an invalid geometry type or feature count')
            validate_dbf_schema(reader)
    return records > 0


def _normalise_zip(source_path, target, source, year):
    """Copy one shapefile family, renaming all members without altering observations."""
    stem = annual_stem(source, year)
    with ZipFile(source_path) as archive:
        names = archive.namelist()
        shapes = [n for n in names if n.endswith('.shp')]
        if len(names) != len(set(names)) or len(shapes) != 1 or archive.testzip():
            raise ArchiveError('Accepted annual ZIP is corrupt or has multiple shapefiles')
        old_stem = shapes[0][:-4]
        family = {old_stem + ext for ext in EXTENSIONS}
        if not family <= set(names) or set(names) - family - {'fields.json', 'provenance.json'}:
            raise ArchiveError('Accepted annual ZIP contains unexpected members')
        if any(Path(n).name != n or '\\' in n for n in names):
            raise ArchiveError('Accepted annual ZIP contains unsafe paths')
        # Stream each renamed component. The accepted payload is preserved;
        # no annual DBF or SHP needs to be materialised as a bytes object.
        with ZipFile(target, 'w', compression=ZIP_DEFLATED, compresslevel=6, allowZip64=True) as exported:
            for extension in sorted(EXTENSIONS):
                old_name, new_name = old_stem + extension, stem + extension
                entry = ZipInfo(new_name, (1980, 1, 1, 0, 0, 0))
                entry.compress_type = ZIP_DEFLATED
                entry.external_attr = 0o644 << 16
                entry.file_size = archive.getinfo(old_name).file_size
                with archive.open(old_name) as incoming, exported.open(entry, 'w') as outgoing:
                    shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)


def _index_bytes(rows, prefix=''):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=INDEX_FIELDS, lineterminator='\n')
    writer.writeheader()
    for row in rows:
        writer.writerow({**row, 'annual_shapefile_zip': prefix + row['annual_shapefile_zip']})
    return stream.getvalue().encode('utf-8')


def _stage_view(manifest_path, manifest, stage):
    root = manifest_path.parent
    rows = []
    seen = set()
    for part in manifest['partitions']:
        source, year = part['source'], part['year']
        stem = annual_stem(source, year)
        if (source, year) in seen or source not in manifest['requested_sources']:
            raise ArchiveError('Repeated or unknown annual partition')
        seen.add((source, year))
        original = checked_path(root, part['shapefile_path'])
        if sha(original) != part['shapefile_sha256']:
            raise ArchiveError('Accepted annual source checksum mismatch')
        relative = SENSOR_FOLDERS[source] + '/' + stem + '.zip'
        target = stage / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        _normalise_zip(original, target, source, year)
        ready = validate_upload_zip(target, source, year, part['record_count'])
        verify_export_payload(original, target, source, year)
        row = dict(source=source, year=year, records=part['record_count'],
                   checked_start=part['coverage_start'], checked_end=part['coverage_end'],
                   annual_shapefile_zip=relative, sha256=sha(target), gee_upload_ready=ready)
        rows.append(row)
        metadata = stage / 'metadata' / SENSOR_FOLDERS[source]
        write_json(metadata / (stem + '_fields.json'), {f[1]: f[0] for f in shape_fields()})
        write_json(metadata / (stem + '_provenance.json'), {
            'contract': 'ghana-firms-gee-annual-v1', 'accepted_partition': part,
            'research_manifest_sha256': sha(manifest_path), 'export': row,
            'upload_status': 'ready' if ready else 'empty_no_features',
            'coordinate_system': 'EPSG:4326', 'encoding': 'UTF-8'})
    if sum(row['records'] for row in rows) != manifest['total_records']:
        raise ArchiveError('Annual export total does not match the accepted manifest')
    rows.sort(key=lambda row: (list(SENSOR_FOLDERS).index(row['source']), row['year']))
    (stage / 'annual-index.csv').write_bytes(_index_bytes(rows))
    write_json(stage / 'annual-export.json', {'contract': 'ghana-firms-gee-annual-export-v1',
        'research_manifest_sha256': sha(manifest_path), 'total_records': manifest['total_records'],
        'complete_available_sp_scope': manifest['complete_available_sp_scope'],
        'complete_requested_scope': manifest['complete_requested_scope'],
        'source_coverage': manifest['source_coverage'], 'partitions': rows})
    (stage / 'README.txt').write_text(
        'Annual Ghana FIRMS SP point shapefiles. Each sensor folder contains individual annual ZIPs.\n'
        'Upload one annual ZIP at a time in Earth Engine Assets > NEW > Table upload > Shape files.\n'
        'The collection ZIP itself is not a single table upload: extract the collection first.\n'
        'ZIPs contain only SHP/SHX/DBF/PRJ/CPG. Fields and provenance are in metadata/.\n'
        'Check annual-index.csv and annual-export.json for coverage and empty periods.\n'
        'Empty annual files have gee_upload_ready=False; do not submit them as assets.\n'
        'Detections are satellite observations, not unique incidents or burned area.\n', encoding='utf-8')
    return rows


def export_annual(manifest_path, output, verify_source=True):
    """Atomically refresh the readable annual view; accepted input files stay untouched."""
    manifest_path = Path(manifest_path).resolve()
    output = Path(output).resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('contract') != 'ghana-firms-research-archive-v1':
        raise ArchiveError('Unsupported research manifest')
    target = output / 'annual'
    if target.is_symlink() or target.resolve() != target or (target.exists() and not target.is_dir()):
        raise ArchiveError('Annual export destination must not be a symlink')
    if manifest_path.is_relative_to(target):
        raise ArchiveError('Export destination overlaps its accepted manifest')
    for part in manifest['partitions']:
        for field in ('path', 'shapefile_path'):
            if checked_path(manifest_path.parent, part[field]).is_relative_to(target):
                raise ArchiveError('Export destination overlaps accepted inputs; choose a separate output directory')
    output.mkdir(parents=True, exist_ok=True)
    lock = output / '.annual-export.lock'
    try:
        handle = lock.open('x', encoding='utf-8')
    except FileExistsError:
        raise ArchiveError('Another annual export holds the lock; do not run exports concurrently') from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        if verify_source:
            verify(manifest_path, write_report=False)
        with tempfile.TemporaryDirectory(prefix='.annual-stage-', dir=output) as folder:
            stage = Path(folder) / 'annual'
            stage.mkdir()
            rows = _stage_view(manifest_path, manifest, stage)
            index = output / 'annual-current.csv'
            previous_index = index.read_bytes() if index.exists() else None
            index_tmp = Path(folder) / 'annual-current.csv'
            index_tmp.write_bytes(_index_bytes(rows, 'annual/'))
            backup = output / ('.annual-backup-' + uuid.uuid4().hex)
            moved = False
            published = False
            try:
                if target.exists():
                    target.rename(backup)
                    moved = True
                stage.rename(target)
                published = True
                os.replace(index_tmp, index)
            except BaseException:
                if published:
                    shutil.rmtree(target)
                if moved:
                    backup.rename(target)
                if previous_index is None:
                    index.unlink(missing_ok=True)
                else:
                    index.write_bytes(previous_index)
                raise
            retained_backup = None
            if moved:
                try:
                    shutil.rmtree(backup)
                except OSError:
                    retained_backup = str(backup)
    finally:
        lock.unlink(missing_ok=True)
    return {'passed': True, 'path': str(target), 'annual_partitions': len(rows),
            'records': manifest['total_records'], 'gee_upload_ready': sum(r['gee_upload_ready'] for r in rows),
            'empty_partitions': sum(not r['gee_upload_ready'] for r in rows),
            'retained_backup': retained_backup}


def verify_annual(output, manifest_path):
    root = Path(output).resolve() / 'annual'
    manifest_path = Path(manifest_path).resolve()
    research = json.loads(manifest_path.read_text(encoding='utf-8'))
    export = json.loads((root / 'annual-export.json').read_text(encoding='utf-8'))
    if (export.get('contract') != 'ghana-firms-gee-annual-export-v1'
            or export.get('research_manifest_sha256') != sha(manifest_path)):
        raise ArchiveError('Annual export does not match the accepted archive; run export again')
    rows = export['partitions']
    expected = {(p['source'], p['year']): p for p in research['partitions']}
    if len(rows) != len(expected) or {(r['source'], r['year']) for r in rows} != set(expected):
        raise ArchiveError('Annual export source/year coverage mismatch')
    expected_files = {'annual-export.json', 'annual-index.csv', 'README.txt'}
    for row in rows:
        source, year = row['source'], row['year']
        part = expected[(source, year)]
        relative = SENSOR_FOLDERS[source] + '/' + annual_stem(source, year) + '.zip'
        if (row['annual_shapefile_zip'] != relative or row['records'] != part['record_count']
                or row['checked_start'] != part['coverage_start'] or row['checked_end'] != part['coverage_end']):
            raise ArchiveError('Annual export index does not match its accepted partition')
        path = checked_path(root, relative)
        if sha(path) != row['sha256']:
            raise ArchiveError('Annual export checksum mismatch')
        if validate_upload_zip(path, source, year, row['records']) != row['gee_upload_ready']:
            raise ArchiveError('Annual export upload readiness mismatch')
        original = checked_path(manifest_path.parent, part['shapefile_path'])
        if sha(original) != part['shapefile_sha256']:
            raise ArchiveError('Accepted annual source checksum mismatch')
        verify_export_payload(original, path, source, year)
        meta = root / 'metadata' / SENSOR_FOLDERS[source]
        fields = json.loads((meta / (annual_stem(source, year) + '_fields.json')).read_text())
        provenance = json.loads((meta / (annual_stem(source, year) + '_provenance.json')).read_text())
        if fields != {f[1]: f[0] for f in shape_fields()} or provenance.get('accepted_partition') != part or provenance.get('export') != row:
            raise ArchiveError('Annual export provenance/field dictionary mismatch')
        expected_files.update((relative,
            'metadata/' + SENSOR_FOLDERS[source] + '/' + annual_stem(source, year) + '_fields.json',
            'metadata/' + SENSOR_FOLDERS[source] + '/' + annual_stem(source, year) + '_provenance.json'))
    actual_files = set()
    for path in root.rglob('*'):
        if path.is_symlink():
            raise ArchiveError('Annual export contains an unexpected symbolic link')
        if path.is_file():
            actual_files.add(path.relative_to(root).as_posix())
    if actual_files != expected_files:
        raise ArchiveError('Annual export contains missing or undeclared files')
    if ((root / 'annual-index.csv').read_bytes() != _index_bytes(rows)
            or (root.parent / 'annual-current.csv').read_bytes() != _index_bytes(rows, 'annual/')):
        raise ArchiveError('Annual export CSV index mismatch')
    if sum(r['records'] for r in rows) != research['total_records'] or export['total_records'] != research['total_records']:
        raise ArchiveError('Annual export record total mismatch')
    return {'passed': True, 'annual_partitions': len(rows), 'records': research['total_records']}


def package_collection(manifest_path, output):
    """Bundle the sensor folders; each enclosed annual ZIP is an individual GEE upload."""
    manifest_path, output = Path(manifest_path).resolve(), Path(output).resolve()
    if output.suffix.lower() != '.zip':
        raise ArchiveError('The annual collection output must be a ZIP file')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for part in manifest['partitions']:
        if output in {checked_path(manifest_path.parent, part[k]) for k in ('path', 'shapefile_path')}:
            raise ArchiveError('Collection output would replace an accepted artifact')
    if not manifest['partitions']:
        raise ArchiveError('No accepted annual partitions to package')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.annual-collection-', dir=output.parent) as folder:
        view = Path(folder) / 'view'
        result = export_annual(manifest_path, view)
        temporary = Path(folder) / 'collection.zip'
        with ZipFile(temporary, 'w', compression=ZIP_DEFLATED, allowZip64=True) as archive:
            for path in sorted((view / 'annual').rglob('*')):
                if not path.is_file():
                    continue
                entry = ZipInfo(path.relative_to(view / 'annual').as_posix(), (1980, 1, 1, 0, 0, 0))
                entry.compress_type = ZIP_STORED if path.suffix == '.zip' else ZIP_DEFLATED
                with path.open('rb') as src, archive.open(entry, 'w', force_zip64=True) as dst:
                    shutil.copyfileobj(src, dst)
        with ZipFile(temporary) as archive:
            if archive.testzip():
                raise ArchiveError('Annual collection integrity failed')
        os.replace(temporary, output)
    digest = sha(output)
    output.with_suffix(output.suffix + '.sha256').write_text(digest + '  ' + output.name + '\n', encoding='ascii')
    return {**result, 'path': str(output), 'bytes': output.stat().st_size, 'sha256': digest}
