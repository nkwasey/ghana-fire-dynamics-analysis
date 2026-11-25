"""Large-component verification remains streaming and fully checks semantics."""
import io
from pathlib import Path
import struct
from zipfile import ZipExtFile, ZipFile

import pytest

from ghana_fire_archive import core, exports, semantic
from test_archive import row
from test_semantic_verification import _prepared, _check, _rewrite_shape


BINARY = ('.shp', '.shx', '.dbf')


def forbid_unbounded_zip_reads(monkeypatch):
    original_read, original_stream_read = ZipFile.read, ZipExtFile.read
    observed = []
    def read(archive, name, *args, **kwargs):
        member = name.filename if hasattr(name, 'filename') else str(name)
        assert not member.endswith(BINARY), 'A whole shapefile component was loaded into RAM'
        return original_read(archive, name, *args, **kwargs)
    def stream_read(stream, size=-1):
        if str(stream.name).endswith(BINARY):
            assert 0 <= size <= 1024 * 1024, 'Unbounded component decompression'
            observed.append((stream.name, size))
        return original_stream_read(stream, size)
    monkeypatch.setattr(ZipFile, 'read', read)
    monkeypatch.setattr(ZipExtFile, 'read', stream_read)
    return observed


def track_scratch(monkeypatch, root):
    directories, files = [], []
    original_directory = semantic.tempfile.TemporaryDirectory
    original_file = semantic.tempfile.TemporaryFile
    def directory(*args, **kwargs):
        kwargs.setdefault('dir', root)
        temporary = original_directory(*args, **kwargs)
        directories.append(Path(temporary.name))
        return temporary
    def file(*args, **kwargs):
        kwargs.setdefault('dir', root)
        temporary = original_file(*args, **kwargs)
        files.append(temporary)
        return temporary
    monkeypatch.setattr(semantic.tempfile, 'TemporaryDirectory', directory)
    monkeypatch.setattr(semantic.tempfile, 'TemporaryFile', file)
    return directories, files


def test_upload_semantics_and_normalisation_never_load_whole_components(tmp_path, monkeypatch):
    # The DBF exceeds one copy block. Distinct native values form distinct
    # observation identities; these are designed records, not research results.
    c, _, root, part = _prepared(tmp_path, [row(frp=str(index + 1)) for index in range(3200)])
    archive_path = root / part['shapefile_path']
    before = {path.name: core.sha(path) for path in (root / part['path'], archive_path)}
    with ZipFile(archive_path) as archive:
        assert archive.getinfo('Ghana_MODIS_SP_2024.dbf').file_size > 1024 * 1024
    observed = forbid_unbounded_zip_reads(monkeypatch)
    directories, files = track_scratch(monkeypatch, tmp_path)
    assert exports.validate_upload_zip(archive_path, part['source'], part['year'], part['record_count'])
    assert _check(c, root, part)['records'] == 3200
    normalised = tmp_path / 'normalised.zip'
    exports._normalise_zip(archive_path, normalised, part['source'], part['year'])
    with ZipFile(normalised) as archive:
        assert all(info.extract_version < 45 for info in archive.infolist()), 'Ordinary annual files unnecessarily use ZIP64'
    semantic.verify_export_payload(archive_path, normalised, part['source'], part['year'])
    assert exports.validate_upload_zip(normalised, part['source'], part['year'], part['record_count'])
    assert observed and {Path(name).suffix for name, _ in observed} == set(BINARY)
    assert {path.name: core.sha(path) for path in (root / part['path'], archive_path)} == before
    assert directories and all(not path.exists() for path in directories)
    assert files and all(stream.closed for stream in files)


@pytest.mark.parametrize('corruption,expected', [
    ('attribute', 'scientific attribute mismatch'),
    ('coordinate', 'point coordinate mismatch'),
    ('framing', 'framing mismatch'),
    ('duplicate_csv', 'identity/status'),
])
def test_bounded_verifier_still_detects_corruption_and_closes_scratch(tmp_path, monkeypatch, corruption, expected):
    c, _, root, part = _prepared(tmp_path, [row(), row(latitude='8.2')])
    archive_path = root / part['shapefile_path']
    if corruption == 'attribute':
        _rewrite_shape(archive_path, changes={'frp_mw': 999})
    elif corruption == 'coordinate':
        _rewrite_shape(archive_path, coordinate_change=(-1.1, 8.1))
    elif corruption == 'duplicate_csv':
        path = root / part['path']
        lines = path.read_text(encoding='utf-8').splitlines()
        path.write_text('\n'.join([*lines, lines[1]]) + '\n', encoding='utf-8')
    else:
        with ZipFile(archive_path) as archive:
            payload = {name: archive.read(name) for name in archive.namelist()}
        name = next(name for name in payload if name.endswith('.shx'))
        data = bytearray(payload[name])
        struct.pack_into('>i', data, 100, 51)
        payload[name] = bytes(data)
        core.zip_files(archive_path, payload)
    forbid_unbounded_zip_reads(monkeypatch)
    directories, files = track_scratch(monkeypatch, tmp_path)
    with pytest.raises(core.ArchiveError, match=expected):
        _check(c, root, part)
    assert directories and all(not path.exists() for path in directories)
    assert all(stream.closed for stream in files)


def point_components(records):
    shp, shx = bytearray(100 + records * 28), bytearray(100 + records * 8)
    for payload in (shp, shx):
        struct.pack_into('>i', payload, 0, 9994)
        struct.pack_into('>i', payload, 24, len(payload) // 2)
        struct.pack_into('<ii', payload, 28, 1000, 1)
    for index in range(records):
        position = 100 + 28 * index
        struct.pack_into('>ii', shp, position, index + 1, 10)
        struct.pack_into('<i', shp, position + 8, 1)
        struct.pack_into('>ii', shx, 100 + 8 * index, position // 2, 10)
    return shp, shx


def test_physical_framing_reads_bounded_batches_and_checks_last_record():
    records = semantic.PHYSICAL_RECORD_BATCH + 1
    shp, shx = point_components(records)
    class BoundedStream(io.BytesIO):
        def read(self, size=-1):
            assert 0 <= size <= semantic.PHYSICAL_RECORD_BATCH * 28
            return super().read(size)
    semantic.validate_point_components(BoundedStream(shp), BoundedStream(shx), records)
    # Corruption beyond the first batch must still be inspected.
    struct.pack_into('>i', shp, 100 + 28 * (records - 1), 0)
    with pytest.raises(core.ArchiveError, match='framing mismatch'):
        semantic.validate_point_components(BoundedStream(shp), BoundedStream(shx), records)
