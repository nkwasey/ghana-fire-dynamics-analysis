"""Package the Archive source with an explicit file list."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import tempfile
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = (
    '.gitignore', '.gitattributes', 'README.md', 'GEE_UPLOAD.md', 'environment.yml', 'pyproject.toml', 'requirements.txt',
    'requirements-dev.txt', 'archive.py', 'Build Archive.cmd',
    'Verify Archive.cmd', 'Package Annual Shapefiles.cmd',
    'configs/archive.yaml', 'configs/single-year.example.yaml', 'configs/rp1.yaml',
    'data/metadata/README.md', 'data/raw/README.md',
    'data/reference/geography/checksums.sha256', 'data/reference/geography/geography-manifest.json',
    'src/ghana_fire_archive/__init__.py',
    'src/ghana_fire_archive/__main__.py', 'src/ghana_fire_archive/api.py',
    'src/ghana_fire_archive/cli.py', 'src/ghana_fire_archive/core.py',
    'src/ghana_fire_archive/exports.py',
    'src/ghana_fire_archive/acquisition.py',
    'src/ghana_fire_archive/configuration.py',
    'src/ghana_fire_archive/scientific.py',
    'src/ghana_fire_archive/semantic.py',
    'tests/test_archive.py', 'tests/test_release.py', 'tests/test_exports.py',
    'tests/test_acquisition_contract.py', 'tests/test_configuration_contract.py',
    'tests/test_scientific_contract.py', 'tests/test_semantic_verification.py',
    'tests/test_integrated_contract.py', 'tests/test_api.py',
    'tests/test_bounded_validation.py',
    'tools/package_annual.py', 'tools/package_source.py',
)
MANIFEST = 'SOURCE_MANIFEST.sha256'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def package(output, root=ROOT):
    root = Path(root).resolve()
    output = Path(output).resolve()
    if output.suffix.lower() != '.zip':
        raise ValueError('The source package must be a ZIP file')
    metadata = tomllib.loads((root / 'pyproject.toml').read_text(encoding='utf-8'))
    version = metadata['project']['version']
    module = ast.parse((root / 'src/ghana_fire_archive/__init__.py').read_text(encoding='utf-8'))
    module_version = next(ast.literal_eval(node.value) for node in module.body
                          if isinstance(node, ast.Assign)
                          and any(isinstance(t, ast.Name) and t.id == '__version__' for t in node.targets))
    if module_version != version:
        raise ValueError('Project and CLI versions disagree')

    files = {}
    for name in sorted(SOURCE_FILES):
        path = root / name
        if path.is_symlink() or not path.resolve().is_relative_to(root) or not path.is_file():
            raise ValueError(f'Missing or unsafe required source file: {name}')
        files[name] = path.read_bytes()
    # The reference geometry is provisioned separately. Check the included manifest.
    prefix = 'data/reference/geography/'
    checksums = dict((name.lstrip('*'), digest) for digest, name in (
        line.split(maxsplit=1) for line in files[prefix + 'checksums.sha256'].decode('utf-8').splitlines()
        if line.strip()
    ))
    if sha(files[prefix + 'geography-manifest.json']) != checksums.get('geography-manifest.json'):
        raise ValueError('Reference geography manifest checksum mismatch')

    inventory = {name: sha(data) for name, data in files.items()}
    files[MANIFEST] = ''.join(f'{value}  {name}\n' for name, value in inventory.items()).encode('utf-8')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=output.stem + '-', suffix='.partial',
                                     dir=output.parent, delete=False) as handle:
        temporary = Path(handle.name)
    prefix = 'Ghana_Fire_Archive/'
    try:
        with ZipFile(temporary, 'w', compression=ZIP_DEFLATED, compresslevel=9) as archive:
            for name, data in sorted(files.items()):
                entry = ZipInfo(prefix + name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = ZIP_DEFLATED
                entry.create_system = 3
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data)
        with ZipFile(temporary) as archive:
            if archive.testzip() is not None or len(archive.namelist()) != len(files):
                raise ValueError('Source ZIP integrity failed')
            if set(archive.namelist()) != {prefix + name for name in files}:
                raise ValueError('Unexpected source ZIP contents')
            for name, data in files.items():
                if archive.read(prefix + name) != data:
                    raise ValueError('ZIP member differs from source: ' + name)
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return {'passed': True, 'version': version, 'path': str(output),
            'files': len(files), 'bytes': output.stat().st_size,
            'sha256': sha(output.read_bytes()), 'generated_outputs_included': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, help='destination source ZIP, outside generated dataset folders')
    args = parser.parse_args()
    print(json.dumps(package(args.output), indent=2))


if __name__ == '__main__':
    main()
