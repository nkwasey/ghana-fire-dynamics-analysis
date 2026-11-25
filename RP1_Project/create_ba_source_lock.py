#!/usr/bin/env python3
"""Lock original annual c3 CSV identities from an explicit bundle manifest.

Byte identity does not establish scientific validity or remote asset geometry.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import sys

_SRC = Path(__file__).resolve().parent / 'rp1_analysis' / 'src'
_contract_import_path = sys.path[:]
try:
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    from rp1_ba_contracts import c3
finally:
    sys.path[:] = _contract_import_path

SCHEMA = 'rp1-ba-source-lock-v2'
ENTRY_FIELDS = ('family', 'domain', 'level', 'partition', 'year', 'role', 'path', 'filename', 'sha256', 'size_bytes')


def build_lock(*, bundle: Path | None = None, manifest_path: Path | None = None,
               profile: str = 'c3', source_label: str = 'c3',
               source_schema_version: str = c3.SCHEMA, quality_policy: str = c3.POLICY,
               method_version: str = c3.METHOD) -> dict:
    if profile != 'c3' or {'source_label': source_label, 'source_schema_version': source_schema_version,
                          'quality_policy': quality_policy, 'method_version': method_version} != c3.PROFILE:
        raise ValueError('Only the pinned c3 profile can create current source locks')
    manifest_path = Path(manifest_path) if manifest_path is not None else Path(bundle) / 'manifest.json'
    root = manifest_path.parent.resolve()
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    if manifest.get('contract') != 'rp1-ba-c3-bundle-v1' or manifest.get('profile_contract') != c3.PROFILE:
        raise ValueError('Source lock requires the c3 bundle manifest')
    expected = c3.expected_identities(manifest['windows'], manifest['zones'], manifest['levels'])
    entries, seen = [], set()
    for source in manifest['outputs']:
        relative = source['path']
        posix = PurePosixPath(relative)
        if not relative or '\\' in relative or ':' in relative or posix.is_absolute() or '..' in posix.parts or posix.as_posix() != relative:
            raise ValueError('Unsafe source manifest path')
        path = root.joinpath(*posix.parts)
        if not path.is_file() or not path.resolve().is_relative_to(root) or any(p.is_symlink() for p in [path, *path.parents] if p != root.parent):
            raise ValueError('Missing, escaped or symlinked source member')
        identity = c3.parse_filename(path.name, observation_windows=manifest['windows'])
        key = tuple(identity[f] for f in ('family', 'level', 'partition', 'year'))
        if key not in expected or key in seen or any(source.get(f) != value for f, value in identity.items()):
            raise ValueError('Duplicate or incompatible annual source identity')
        seen.add(key)
        raw = path.read_bytes()
        if source.get('filename') != path.name or source.get('size_bytes') != len(raw) or source.get('sha256') != hashlib.sha256(raw).hexdigest():
            raise ValueError('Source manifest byte identity differs')
        entries.append({field: source[field] for field in ENTRY_FIELDS})
    if seen != expected:
        raise ValueError('Source lock does not exactly cover declared annual matrix')
    return {'schema_version': SCHEMA, 'profile_id': 'c3', **c3.PROFILE,
            'scope': manifest['scope'], 'windows': manifest['windows'],
            'zones': manifest['zones'], 'levels': manifest['levels'],
            'files': sorted(entries, key=lambda row: (row['family'], row['level'], row['partition'], row['year']))}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--profile', choices=['c3'], default='c3')
    parser.add_argument('--output', type=Path, required=True, help='New path, never overwritten')
    args = parser.parse_args(argv)
    try:
        lock = build_lock(bundle=args.bundle, profile=args.profile)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(lock, stream, indent=2, sort_keys=True)
            stream.write('\n')
    except (OSError, ValueError, KeyError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 1
    print(f'Created {args.output}; {len(lock["files"])} annual c3 byte identities.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
