#!/usr/bin/env python3
"""Build and safely apply a complete geographic handoff from one geo-prep run.

The bundle does not replace existing project files, change the land mask or
rewrite analysis input manifests. It provides structural validation, not proof
that any pre-existing satellite/active-fire panels used the same geometry.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import math
import os
import re
from pathlib import Path, PurePosixPath
import shutil
import tempfile

EXTENSIONS = ('.shp', '.shx', '.dbf', '.prj', '.cpg')
FIRMS = 'RP1_Project/rp1_mv_firms_panels'
ANALYSIS = 'RP1_Project/rp1_analysis'
# Source-to-destination names for supported handoff schemas. The resolver
# selects the projected boundary sources required by the active contract.
MAPPING = {'unit_universe.csv': f'{FIRMS}/data/metadata/unit_universe.csv',
           'crosswalks/district_to_acz_max_overlap.csv': f'{ANALYSIS}/data/reference/district_to_acz_max_overlap.csv',
           'crosswalks/district_to_acz_max_overlap.provenance.json': f'{ANALYSIS}/data/reference/district_to_acz_max_overlap.provenance.json'}
for _base in ('acz', 'districts_within_acz'):
    for _ext in EXTENSIONS:
        MAPPING[f'boundaries/{_base}{_ext}'] = f'{FIRMS}/data/raw/boundaries/{_base}{_ext}'
        MAPPING[f'analysis_boundaries/{_base}{_ext}'] = f'{ANALYSIS}/data/geo/{_base}{_ext}'
BUNDLE_MANIFEST = 'handoff_manifest.json'
PROJECT_MANIFEST = 'RP1_Project/geo_handoff_manifest.json'
CURRENT_SCHEMA = 'rp1-geo-handoff-v2'
BOUNDARY_CRS = 'EPSG:32630'


def handoff_sources(schema):
    """Resolve source files for destinations under an explicit handoff schema."""
    require(schema in ('rp1-geo-handoff-v1', CURRENT_SCHEMA), 'Unexpected handoff schema')
    sources = {target: source for source, target in MAPPING.items()}
    if schema == CURRENT_SCHEMA:
        for base in ('acz', 'districts_within_acz'):
            for ext in EXTENSIONS:
                sources[f'{FIRMS}/data/raw/boundaries/{base}{ext}'] = f'analysis_boundaries/{base}{ext}'
    return sources

class HandoffError(ValueError):
    pass

def require(condition, message):
    if not condition:
        raise HandoffError(message)

def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()

def safe_relative(value):
    require(isinstance(value, str) and value and '\\' not in value and ':' not in value, f'Invalid relative path: {value!r}')
    relative = PurePosixPath(value)
    require(not relative.is_absolute() and '..' not in relative.parts and '.' not in relative.parts, f'Invalid relative path: {value!r}')
    return Path(*relative.parts)

def guarded_file(root, relative):
    candidate = root / safe_relative(relative)
    require(candidate.is_file() and not candidate.is_symlink(), f'Missing or symlinked file: {candidate}')
    require(candidate.resolve().is_relative_to(root.resolve()), f'Path outside root: {candidate}')
    return candidate

def read_json(path):
    with path.open(encoding='utf-8') as stream:
        data = json.load(stream)
    require(isinstance(data, dict), f'Expected JSON object: {path}')
    return data

def verify_record(path, record):
    require(isinstance(record, dict) and record.get('bytes') == path.stat().st_size and record.get('sha256') == sha256(path), f'Hash or size mismatch: {path}')

def read_csv(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames is not None and len(set(reader.fieldnames)) == len(reader.fieldnames), f'Missing or duplicate CSV headers: {path}')
        return list(reader)


def verify_projected_bundle(bundle, manifest):
    """Confirm that v2 consumers receive the same projected boundary bytes."""
    from pyproj import CRS
    import geopandas as gpd
    require(manifest.get('boundary_crs') == BOUNDARY_CRS, 'Unexpected handoff boundary CRS')
    for base in ('acz', 'districts_within_acz'):
        for ext in EXTENSIONS:
            firms = f'{FIRMS}/data/raw/boundaries/{base}{ext}'
            analysis = f'{ANALYSIS}/data/geo/{base}{ext}'
            require(manifest['files'][firms]['sha256'] == manifest['files'][analysis]['sha256'],
                    f'Consumer boundary bytes differ: {base}{ext}')
        for target in (f'{FIRMS}/data/raw/boundaries/{base}.shp', f'{ANALYSIS}/data/geo/{base}.shp'):
            layer = gpd.read_file(guarded_file(bundle, target))
            require(layer.crs is not None and CRS(layer.crs) == CRS(BOUNDARY_CRS),
                    f'Consumer boundary CRS differs: {target}')

def check_identities(run):
    """Verify keys and parents with no site-specific district or zone count."""
    from pyproj import CRS
    import geopandas as gpd
    from geo_data_prep.pipeline import positive_overlaps
    units = read_csv(guarded_file(run, 'unit_universe.csv'))
    walk = read_csv(guarded_file(run, 'crosswalks/district_to_acz_max_overlap.csv'))
    by_key = {}
    for row in units:
        level, uid = row.get('level', ''), row.get('unit_id', '')
        require(level in ('district', 'acz') and uid and (level, uid) not in by_key, f'Invalid or duplicate unit: {(level, uid)}')
        by_key[level, uid] = row
    districts = {uid: row for (level, uid), row in by_key.items() if level == 'district'}
    zones = {uid: row for (level, uid), row in by_key.items() if level == 'acz'}
    require(districts and zones, 'Empty unit hierarchy')
    for uid, row in districts.items():
        require(row.get('parent_level') == 'acz' and row.get('parent_id') in zones, f'Invalid parent for district {uid}')
    pairs = {}
    required_crosswalk = {'district_id', 'zone_id', 'zone_code', 'zone_name', 'original_district_area_sq_km', 'dominant_overlap_area_sq_km', 'dominant_overlap_share', 'assignment_method', 'working_crs'}
    require(walk and required_crosswalk.issubset(walk[0]), 'Crosswalk lacks required consumer fields')
    for row in walk:
        uid, zone = row.get('district_id', ''), row.get('zone_id', '')
        require(uid and uid not in pairs, f'Duplicate or missing crosswalk district: {uid}')
        require(zone in zones and row['zone_code'] == zones[zone]['unit_code'] and row['zone_name'] == zones[zone]['unit_name'], f'Crosswalk zone attributes differ: {uid}')
        share = float(row['dominant_overlap_share']); whole = float(row['original_district_area_sq_km']); overlap = float(row['dominant_overlap_area_sq_km'])
        require(math.isfinite(share) and 0 <= share <= 1 and math.isfinite(whole) and whole > 0 and math.isfinite(overlap) and overlap > 0, f'Invalid overlap metrics: {uid}')
        require(bool(row['assignment_method']) and bool(row['working_crs']), f'Missing assignment provenance: {uid}')
        pairs[uid] = zone
    require(set(pairs) == set(districts), 'Crosswalk and universe district IDs differ')
    require(all(pairs[uid] == row['parent_id'] for uid, row in districts.items()), 'Crosswalk and universe parent identities differ')
    provenance = read_json(guarded_file(run, 'crosswalks/district_to_acz_max_overlap.provenance.json'))
    require(provenance.get('crosswalk', {}).get('sha256') == sha256(run / 'crosswalks/district_to_acz_max_overlap.csv'), 'Crosswalk provenance hash mismatch')
    require(provenance.get('schema') == 'district-to-zone-crosswalk-provenance-v1' and provenance.get('crosswalk', {}).get('rows') == len(walk), 'Crosswalk provenance schema or row count mismatch')
    fingerprint = read_json(guarded_file(run, 'inputs_fingerprint.json'))
    for role, input_role in [('source_district_geometry', 'districts'), ('source_acz_geometry', 'zones')]:
        digest = provenance.get(role, {}).get('bundle_sha256', '')
        require(bool(re.fullmatch(r'[0-9a-f]{64}', digest)) and digest == fingerprint.get(input_role, {}).get('bundle_sha256'), f'Crosswalk input fingerprint mismatch: {role}')
    require(bool(provenance.get('implementation_identity')) and bool(provenance.get('analysis_crs')), 'Crosswalk processing provenance is incomplete')
    contract = read_json(guarded_file(run, 'contract/stage1_contract_manifest.json'))
    qa = read_json(guarded_file(run, 'qa/qa_summary.json'))
    qa_checks = qa.get('checks', {})
    require(contract.get('handoff_eligible') is True and qa_checks.get('handoff_eligible') is True, 'Stage 1 did not record a structurally eligible handoff')
    require(qa.get('status') in ('PASS', 'WARN'), 'Unexpected or failed QA status')
    area_tolerance = qa_checks.get('area_tolerance_m2')
    require(isinstance(area_tolerance, (int, float)) and not isinstance(area_tolerance, bool)
            and math.isfinite(area_tolerance) and area_tolerance >= 0,
            'Invalid or missing geography QA area tolerance')
    derivative = contract.get('analysis_handoff')
    require(isinstance(derivative, dict) and derivative.get('exact_parent_district_union') is True, 'No validated projected analysis handoff')
    analysis_crs = CRS.from_user_input(derivative.get('crs'))
    require(analysis_crs.is_projected and all(abs(axis.unit_conversion_factor - 1) < 1e-12
                                             for axis in analysis_crs.axis_info[:2]),
            'Analysis handoff requires a projected CRS with metre axes')
    require(derivative.get('districts_relative_path') == 'analysis_boundaries/districts_within_acz.shp' and derivative.get('zones_relative_path') == 'analysis_boundaries/acz.shp', 'Unexpected analysis paths')
    actual = {}
    layers = {}
    for group, crs in [('boundaries', CRS.from_user_input(contract['geometry_crs'])), ('analysis_boundaries', analysis_crs)]:
        D = gpd.read_file(guarded_file(run, f'{group}/districts_within_acz.shp'))
        Z = gpd.read_file(guarded_file(run, f'{group}/acz.shp'))
        require(D.crs and Z.crs and CRS(D.crs) == crs and CRS(Z.crs) == crs, f'{group}: CRS mismatch')
        require({'dist_id', 'dist_name', 'zone_id', 'zone_name', 'zone_code', 'ovl_share'}.issubset(D.columns), f'{group}: missing district fields')
        require({'zone_id', 'zone_name', 'zone_code'}.issubset(Z.columns), f'{group}: missing zone fields')
        require(D.dist_id.is_unique and Z.zone_id.is_unique, f'{group}: duplicate spatial IDs')
        require(set(D.dist_id.astype(str)) == set(districts) and set(Z.zone_id.astype(str)) == set(zones), f'{group}: spatial and universe IDs differ')
        require(all(pairs[str(r.dist_id)] == str(r.zone_id) for r in D.itertuples()), f'{group}: spatial parents differ')
        for r in D.itertuples():
            u = districts[str(r.dist_id)]
            require(str(r.dist_name) == str(u['unit_name']) and str(r.zone_name) == str(u['parent_name']) and str(r.zone_code) == str(u['parent_code']), f'{group}: district identity fields differ: {r.dist_id}')
        for r in Z.itertuples():
            u = zones[str(r.zone_id)]
            require(str(r.zone_name) == str(u['unit_name']) and str(r.zone_code) == str(u['unit_code']), f'{group}: zone identity fields differ: {r.zone_id}')
        require(D.geometry.notna().all() and Z.geometry.notna().all() and D.is_valid.all() and Z.is_valid.all() and not D.is_empty.any() and not Z.is_empty.any(), f'{group}: invalid geometry')
        for z in Z.itertuples():
            members = D[D.zone_id == z.zone_id]
            require(not members.empty and z.geometry.equals(members.geometry.union_all()), f'{group}: zone does not equal its district union: {z.zone_id}')
        actual[group] = {'districts': len(D), 'zones': len(Z), 'crs': crs.to_string()}
        layers[group] = D
    # Coordinate tolerance is numerical only, not a statement of input accuracy.
    native = layers['boundaries'].set_index('dist_id').sort_index().to_crs(analysis_crs)
    projected = layers['analysis_boundaries'].set_index('dist_id').sort_index()
    overlaps = positive_overlaps(projected, area_tolerance)
    require(not overlaps, f'Analysis district overlaps above numerical tolerance: {overlaps[:3]}')
    for uid in native.index:
        left = native.geometry.loc[uid].normalize()
        right = projected.geometry.loc[uid].normalize()
        require(left.equals_exact(right, 0.0001), f'Projected district does not match source coordinates: {uid}')
    return {'qa_status': qa['status'], 'warning_count': len(qa.get('warnings', [])), 'layers': actual,
            'districts': len(districts), 'zones': len(zones), 'run_id': contract['run_id']}

def build(run_arg, bundle_arg):
    run = Path(run_arg).resolve(strict=True)
    bundle = Path(bundle_arg).absolute()
    require(run.is_dir() and not bundle.exists(), 'Run must exist and output bundle must not exist')
    require(not bundle.resolve().is_relative_to(run), 'Bundle cannot be created inside the source run')
    manifest = read_json(guarded_file(run, 'outputs_manifest.json'))
    require(manifest.get('schema') == 'geo-data-output-manifest-v1' and isinstance(manifest.get('files'), dict), 'Unexpected geo-prep output manifest')
    for relative, record in manifest['files'].items():
        verify_record(guarded_file(run, relative), record)
    for relative in (*MAPPING, 'contract/stage1_contract_manifest.json', 'qa/qa_summary.json', 'inputs_fingerprint.json'):
        require(relative in manifest['files'], f'Required file not listed in output manifest: {relative}')
    evidence = check_identities(run)
    require(manifest.get('run_id') == evidence['run_id'], 'Run IDs differ between contract and manifest')
    require(evidence['layers']['analysis_boundaries']['crs'] == BOUNDARY_CRS,
            f'Common downstream boundary handoff requires {BOUNDARY_CRS}')
    bundle.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.geo-handoff-', dir=bundle.parent))
    try:
        files = {}
        for target, relative in handoff_sources(CURRENT_SCHEMA).items():
            source = guarded_file(run, relative)
            target_path = stage / safe_relative(target)
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target_path)
            verify_record(target_path, manifest['files'][relative])
            files[target] = {'bytes': target_path.stat().st_size, 'sha256': sha256(target_path), 'source_relative_path': relative}
        result = {'schema': CURRENT_SCHEMA, 'boundary_crs': BOUNDARY_CRS, 'source_output_manifest_sha256': sha256(run / 'outputs_manifest.json'),
                  'source_contract_sha256': sha256(run / 'contract/stage1_contract_manifest.json'),
                  'source_run': evidence, 'files': files,
                  'scope': 'Structural geography handoff only; satellite/AF provenance and scientific suitability require separate validation.',
                  'excluded': ['FIRMS land mask', 'analysis input hash inventory', 'fire panels', 'model outputs']}
        (stage / BUNDLE_MANIFEST).write_text(json.dumps(result, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        require(not bundle.exists(), f'Output bundle appeared during processing: {bundle}')
        os.rename(stage, bundle)
        return result
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise

def apply(bundle_arg, project_arg, *, replace=False, backup_arg=None):
    """Preflight all targets and preserve existing files when replacement is requested.

    Default application refuses every pre-existing target. Replacement is opt-in
    and first publishes a verified backup in a fresh directory. Ordinary errors
    trigger rollback; forced termination cannot guarantee cross-directory atomicity.
    Do not run simultaneous writers against these paths.
    """
    bundle = Path(bundle_arg).resolve(strict=True)
    project = Path(project_arg).resolve(strict=True)
    require((project / 'RP1_Project').is_dir(), 'Project root must contain RP1_Project')
    require(replace == (backup_arg is not None), 'Replacement requires --replace and a fresh --backup directory together')
    manifest_path = guarded_file(bundle, BUNDLE_MANIFEST)
    manifest = read_json(manifest_path)
    schema = manifest.get('schema')
    sources = handoff_sources(schema)
    require(set(manifest.get('files', {})) == set(sources), 'Unexpected or incomplete handoff bundle')
    records = []
    for relative, record in manifest['files'].items():
        require(record.get('source_relative_path') == sources[relative], f'Unexpected handoff source: {relative}')
        source = guarded_file(bundle, relative)
        verify_record(source, record)
        records.append((source, project / safe_relative(relative), record))
    if schema == CURRENT_SCHEMA:
        verify_projected_bundle(bundle, manifest)
    records.append((manifest_path, project / safe_relative(PROJECT_MANIFEST), {'sha256': sha256(manifest_path), 'bytes': manifest_path.stat().st_size}))
    require(not project.is_relative_to(bundle), 'Project root cannot be inside the handoff bundle')
    before = {}
    for source, dest, _ in records:
        require(source.resolve() != dest.resolve(), f'Source and destination overlap: {dest}')
        require(dest.resolve().is_relative_to(project) and not dest.is_symlink(), f'Unsafe destination: {dest}')
        ancestor = dest.parent
        while ancestor != project:
            require(not ancestor.is_symlink(), f'Symlinked destination directory: {ancestor}')
            ancestor = ancestor.parent
        if dest.exists():
            require(dest.is_file(), f'Destination is not a regular file: {dest}')
            require(replace, f'Destination already exists: {dest}')
            before[dest] = {'sha256': sha256(dest), 'bytes': dest.stat().st_size}
        else:
            before[dest] = None
    if not replace:
        created = []
        try:
            for source, dest, record in records:
                dest.parent.mkdir(parents=True, exist_ok=True)
                with source.open('rb') as inp, dest.open('xb') as out:
                    created.append(dest)
                    shutil.copyfileobj(inp, out)
                verify_record(dest, record)
        except BaseException:
            for dest in reversed(created):
                dest.unlink(missing_ok=True)
            raise
        return {'created_files': len(created), 'project_manifest': str(project / PROJECT_MANIFEST), 'run_id': manifest['source_run']['run_id']}

    backup = Path(backup_arg).absolute()
    require(not backup.exists() and not backup.is_symlink(), f'Backup directory already exists: {backup}')
    backup_resolved = backup.resolve()
    require(not project.is_relative_to(backup_resolved) and not bundle.is_relative_to(backup_resolved) and not backup_resolved.is_relative_to(bundle), 'Backup cannot contain the project root or overlap the handoff bundle')
    require(all(not dest.resolve().is_relative_to(backup_resolved) and dest.resolve() != backup_resolved for _, dest, _ in records), 'Backup overlaps a handoff destination')
    backup.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.geo-handoff-backup-', dir=backup.parent))
    try:
        for _, dest, _ in records:
            record = before[dest]
            if record is not None:
                copy = stage / dest.relative_to(project)
                copy.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(dest, copy)
                verify_record(copy, record)
                verify_record(dest, record)
        old = {dest.relative_to(project).as_posix(): record for dest, record in before.items() if record is not None}
        absent = [dest.relative_to(project).as_posix() for dest, record in before.items() if record is None]
        (stage / 'backup_manifest.json').write_text(json.dumps({'schema': 'rp1-geo-handoff-backup-v1', 'original_files': old, 'originally_absent': absent, 'source_bundle_manifest_sha256': sha256(manifest_path)}, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        require(not backup.exists(), f'Backup directory appeared during preparation: {backup}')
        os.rename(stage, backup)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise

    # Stage all new bytes on the same filesystem before changing any target.
    new_stage = Path(tempfile.mkdtemp(prefix='.geo-handoff-new-', dir=project))
    changed = []
    try:
        for index, (source, _, record) in enumerate(records):
            staged = new_stage / str(index)
            shutil.copyfile(source, staged)
            verify_record(staged, record)
        for _, dest, _ in records:
            original = before[dest]
            if original is None:
                require(not dest.exists() and not dest.is_symlink(), f'Destination changed during backup: {dest}')
            else:
                require(dest.is_file() and not dest.is_symlink(), f'Destination changed during backup: {dest}')
                verify_record(dest, original)
        for index, (_, dest, record) in enumerate(records):
            dest.parent.mkdir(parents=True, exist_ok=True)
            os.replace(new_stage / str(index), dest)
            changed.append(dest)
            verify_record(dest, record)
    except BaseException as error:
        restore_failures = []
        for dest in reversed(changed):
            try:
                original = before[dest]
                if original is None:
                    dest.unlink(missing_ok=True)
                else:
                    restored = new_stage / ('restore-' + str(len(restore_failures)) + '-' + str(len(changed)))
                    shutil.copyfile(backup / dest.relative_to(project), restored)
                    verify_record(restored, original)
                    os.replace(restored, dest)
                    verify_record(dest, original)
            except BaseException as restore_error:
                restore_failures.append(f'{dest}: {restore_error}')
        if restore_failures:
            raise HandoffError(f'Application failed and rollback was incomplete; backup retained at {backup}: {restore_failures}') from error
        raise
    finally:
        shutil.rmtree(new_stage, ignore_errors=True)
    return {'created_or_replaced_files': len(changed), 'previously_existing_files': sum(v is not None for v in before.values()),
            'backup': str(backup), 'project_manifest': str(project / PROJECT_MANIFEST), 'run_id': manifest['source_run']['run_id']}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    b = sub.add_parser('build', help='Validate a completed Stage 1 run and create an isolated handoff bundle')
    b.add_argument('--run', required=True); b.add_argument('--bundle', required=True)
    a = sub.add_parser('apply', help='Apply a verified bundle without overwriting, or explicitly replace with a verified backup')
    a.add_argument('--bundle', required=True); a.add_argument('--project-root', required=True)
    a.add_argument('--replace', action='store_true', help='Replace only after creating a verified backup')
    a.add_argument('--backup', help='Fresh backup directory required with --replace')
    args = parser.parse_args()
    try:
        result = build(args.run, args.bundle) if args.command == 'build' else apply(args.bundle, args.project_root, replace=args.replace, backup_arg=args.backup)
        print(json.dumps(result, indent=2, sort_keys=True))
    except (HandoffError, OSError, ValueError, KeyError) as exc:
        parser.exit(2, f'Geography handoff failed: {exc}\n')

if __name__ == '__main__':
    main()
