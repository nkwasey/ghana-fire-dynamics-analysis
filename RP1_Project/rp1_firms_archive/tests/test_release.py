"""Source-release exclusion and installed/source CLI entry-point checks."""
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys
from zipfile import ZipFile
import importlib.util

import pytest
from ghana_fire_archive import __version__


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('source_packager', ROOT / 'tools/package_source.py')
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


def test_source_release_allowlist_and_reproducibility(tmp_path):
    source = tmp_path / 'source'
    for name in packager.SOURCE_FILES:
        dest = source / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, dest)
    # These files exist on a working research checkout but must never ship.
    for name in ('private/firms_map_key.txt', 'out/runs/study/annual/results.zip',
                 'out/runs/study/archive-manifest.json', 'data/raw/provider.csv',
                 'data/metadata/firms_map_key.txt', 'data/metadata/local-note.json',
                 'parallel/worker.log', '.venv/pyvenv.cfg',
                 'src/ghana_fire_archive/__pycache__/core.pyc', 'unreviewed.txt'):
        dest = source / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('release exclusion sentinel', encoding='utf-8')
    (source / 'data/reference/geography/ghana.geojson').write_text('local input', encoding='utf-8')
    output = tmp_path / 'release.zip'
    result = packager.package(output, source)
    with ZipFile(output) as archive:
        expected = {'Ghana_Fire_Archive/' + name for name in packager.SOURCE_FILES}
        expected.add('Ghana_Fire_Archive/' + packager.MANIFEST)
        assert set(archive.namelist()) == expected
        manifest = archive.read('Ghana_Fire_Archive/' + packager.MANIFEST).decode()
        for line in manifest.splitlines():
            digest, name = line.split('  ', 1)
            assert hashlib.sha256(archive.read('Ghana_Fire_Archive/' + name)).hexdigest() == digest
        assert not result['generated_outputs_included']
    second = packager.package(tmp_path / 'second.zip', source)
    assert second['sha256'] == result['sha256']
    (source / 'data/reference/geography/geography-manifest.json').write_text('tampered', encoding='utf-8')
    with pytest.raises(ValueError, match='checksum'):
        packager.package(tmp_path / 'bad.zip', source)


def test_source_cli_from_another_working_directory(tmp_path):
    version = subprocess.run([sys.executable, str(ROOT / 'archive.py'), '--version'],
                             cwd=tmp_path, capture_output=True, text=True)
    assert version.returncode == 0 and __version__ in version.stdout
    result = subprocess.run([sys.executable, str(ROOT / 'archive.py'), 'build',
                             '--year', '2024', '--start-year', '2020', '--end-year', '2024'],
                            cwd=tmp_path, capture_output=True, text=True)
    assert result.returncode == 2 and 'Choose --year' in result.stderr
