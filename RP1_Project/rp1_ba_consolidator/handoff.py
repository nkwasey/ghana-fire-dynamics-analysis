"""Admit immutable c3 source bundles with the actual merger's BA loader."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
from . import core
from rp1_ba_contracts import c3

SCHEMA = 'rp1-ba-c3-handoff-v1'
PROFILE = dict(c3.PROFILE)
WINDOWS = {key: list(value) for key, value in c3.DOMAIN_WINDOWS.items()}
_METADATA = {'manifest.json', 'validation_report.json', 'source_lock.json', 'handoff.json'}


def _require(condition, message):
    if not condition:
        raise ValueError('c3 bundle admission: ' + message)


def _sha(path: Path) -> str:
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def _json(path):
    value = json.loads(path.read_text(encoding='utf-8'))
    _require(isinstance(value, dict), 'Expected JSON object: ' + str(path))
    return value


def _write_new(path, value):
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write('\n')


def _workflow_request_identity(value):
    _require(value is None or isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{64}', value), 'Invalid workflow request SHA-256')
    return value


def expected_product_paths(windows=None, zones=None, levels=None):
    windows = WINDOWS if windows is None else windows
    zones = sorted(c3.ZONES) if zones is None else zones
    levels = c3.LEVELS if levels is None else levels
    return {f'sources/rp1_ba_{level}_monthly_c3_{zone}_{family.upper()}_{year}_ext.csv'
            for family, level, zone, year in c3.expected_identities(windows, zones, levels)}


def _safe_member(bundle, relative):
    _require(isinstance(relative, str) and relative and '\\' not in relative and ':' not in relative, 'Invalid manifest path')
    relative_path = PurePosixPath(relative)
    _require(not relative_path.is_absolute() and '..' not in relative_path.parts and relative_path.as_posix() == relative, 'Unsafe manifest member: ' + relative)
    target = bundle.joinpath(*relative_path.parts)
    _require(target.resolve().is_relative_to(bundle.resolve()), 'Manifest member escapes bundle')
    _require(not any(part.is_symlink() for part in [target, *target.parents] if part != bundle.parent), 'Symbolic links are not admitted')
    return target


def _implementation_hashes():
    from RP1_Project import create_ba_source_lock
    authority = Path(__file__).resolve().parents[1] / 'rp1_gee_ba_scripts' / 'c3'
    return {'preparer_sha256': _sha(Path(core.__file__)), 'contract_sha256': _sha(Path(c3.__file__)),
            'merger_sha256': _sha(Path(__file__).resolve().parents[1] / 'merge_af_ba_panels.py'),
            'admission_sha256': _sha(Path(__file__)), 'source_lock_implementation_sha256': _sha(Path(create_ba_source_lock.__file__)),
            'upstream_identity_sha256': _sha(authority / 'UPSTREAM_IDENTITY.json'),
            'upstream_exporter_sha256': _sha(authority / 'scripts/02_monthly_csv_exporter_c3.js'),
            'upstream_scientific_core_sha256': _sha(authority / 'src/ee_core.js'),
            'upstream_scientific_logic_sha256': _sha(authority / 'src/scientific_logic.js')}


def _unit_counts(unit_universe):
    units = core.load_units(Path(unit_universe))
    return {level: sum(key[0] == level for key in units) for level in c3.LEVELS}


def _study(study, counts, manifest):
    windows = manifest['windows']
    _require(set(windows) == set(WINDOWS) and manifest['zones'] == sorted(c3.ZONES) and manifest['levels'] == sorted(c3.LEVELS), 'Actual merger admission requires both domains/levels and all five zones')
    start, end = windows['BA2001']
    ba_start, ba_end = windows['BA2012']
    _require(end == ba_end and ba_start == max(2012, start), 'Domain delivery windows cannot form one canonical study spine')
    default = {'start_yyyymm': start * 100 + 1, 'end_yyyymm': end * 100 + 12,
               'viirs_support_start_yyyymm': max(2012, start) * 100 + 1,
               'ba2012_support_start_yyyymm': ba_start * 100 + 1, 'expected_units': counts}
    supplied = study or {}
    _require(isinstance(supplied, dict) and not set(supplied) - (set(default) | {'analysis_overlap_start_yyyymm'}), 'Unknown study fields')
    result = default | supplied
    for key in ('start_yyyymm', 'end_yyyymm', 'viirs_support_start_yyyymm', 'ba2012_support_start_yyyymm'):
        value = result[key]
        _require(type(value) is int and 100001 <= value and 1 <= value % 100 <= 12,
                 'Invalid study YYYYMM: ' + key)
    # Source availability can precede a bounded pilot's selected calendar.
    # The source's fixed LC domain is recorded independently in domain_windows.
    result['ba2012_support_start_yyyymm'] = max(result['ba2012_support_start_yyyymm'], result['start_yyyymm'])
    for key in ('start_yyyymm', 'end_yyyymm', 'ba2012_support_start_yyyymm', 'expected_units'):
        _require(result[key] == default[key], 'Study/geography differs from admitted annual delivery: ' + key)
    viirs = result['viirs_support_start_yyyymm']
    _require(type(viirs) is int and 1 <= viirs % 100 <= 12 and 200101 <= viirs <= result['end_yyyymm'], 'Invalid VIIRS support start')
    result['viirs_support_start_yyyymm'] = max(viirs, result['start_yyyymm'])
    if 'analysis_overlap_start_yyyymm' in supplied:
        overlap = result['analysis_overlap_start_yyyymm']
        _require(type(overlap) is int and 100001 <= overlap and 1 <= overlap % 100 <= 12,
                 'Invalid study YYYYMM: analysis_overlap_start_yyyymm')
        # The configured date is an earliest analytical floor. A bounded study
        # can begin later; analysis derives its effective paired start from the
        # maximum of this floor, the selected calendar and source support.
        _require(overlap <= result['end_yyyymm'],
                 'Analysis overlap start exceeds the admitted observation period')
    return result


def _inspect_bundle(bundle, *, admitted):
    _require(bundle.is_dir() and not bundle.is_symlink(), 'Bundle directory missing or symbolic link')
    manifest = _json(_safe_member(bundle, 'manifest.json'))
    report = _json(_safe_member(bundle, 'validation_report.json'))
    required = {'contract', 'version', 'profile_contract', 'source_schema', 'method_version',
                'windows', 'zones', 'levels', 'scope', 'coverage', 'domain_windows',
                'script_sha256', 'contract_sha256', 'unit_universe_sha256',
                'boundary_label_operator_declared', 'inputs', 'outputs', 'auxiliary'}
    _require(required <= set(manifest), 'Bundle manifest is missing required fields')
    _require(manifest.get('contract') == report.get('contract') == core.CONTRACT and manifest.get('version') == report.get('version') == core.VERSION, 'Unsupported bundle contract/version')
    _require(manifest.get('profile_contract') == report.get('profile_contract') == PROFILE and manifest.get('source_schema') == c3.SCHEMA and manifest.get('method_version') == c3.METHOD, 'Bundle source/method/profile differs')
    _require(report.get('status') == 'PASS', 'Source validation did not pass')
    if admitted:
        _require(report.get('consumer_validation_status') == 'PASS', 'Actual consumer validation did not pass')
    for key in ('windows', 'zones', 'levels', 'scope', 'coverage', 'domain_windows', 'declared_observation_windows', 'unconsumed_sources', 'script_sha256', 'contract_sha256', 'unit_universe_sha256', 'boundary_label_operator_declared'):
        _require(manifest.get(key) == report.get(key), 'Manifest/report differ in ' + key)
    _require(manifest['domain_windows'] == WINDOWS, 'Fixed domain endpoints changed')
    declared = {name: list(bounds) for name, bounds in c3.declared_observation_windows(manifest.get('declared_observation_windows')).items()}
    selected = c3.declared_observation_windows(manifest['windows'])
    _require(set(selected) <= set(declared) and all(declared[name][0] <= bounds[0] <= bounds[1] <= declared[name][1] for name, bounds in selected.items()), 'Selected source years exceed declared observation coverage')
    expected = expected_product_paths(manifest['windows'], manifest['zones'], manifest['levels'])
    full_matrix = manifest['windows'] == declared and set(declared) == set(WINDOWS) and manifest['zones'] == sorted(c3.ZONES) and manifest['levels'] == sorted(c3.LEVELS)
    _require(manifest['scope'] in ('full', 'pilot') and (manifest['scope'] != 'full' or full_matrix), 'Invalid full/pilot classification')
    _require(manifest['coverage'] == ('complete' if manifest['scope'] == 'full' else 'pilot'), 'Coverage/scope classification differs')
    _require(manifest['script_sha256'] == _sha(Path(core.__file__)) and manifest['contract_sha256'] == _sha(Path(c3.__file__)), 'Preparation/contract implementation changed; readmit')
    records = manifest.get('outputs')
    _require(isinstance(records, list) and len(records) == len(expected) and all(isinstance(row, dict) for row in records), 'Invalid annual source inventory')
    names = [record.get('path') for record in records]
    for name in names:
        _safe_member(bundle, name)
    _require(len(names) == len(set(names)) and set(names) == expected, 'Annual source matrix differs from declared delivery')
    inputs = manifest.get('inputs')
    _require(isinstance(inputs, list) and len(inputs) == len(records) and all(isinstance(row, dict) for row in inputs), 'Original source inventory differs from staged inventory')
    source_fields = ('family', 'domain', 'level', 'partition', 'year', 'role', 'filename',
                     'sha256', 'size_bytes', 'rows', 'columns', 'run_ids')
    by_origin = {}
    for source in inputs:
        relative = source.get('path')
        _safe_member(bundle, relative)  # Validate provenance path syntax, not existence.
        _require(relative not in by_origin, 'Duplicate original source path')
        by_origin[relative] = source
    for staged in records:
        original = by_origin.get(staged.get('origin_relative_path'))
        _require(original is not None and all(original.get(key) == staged.get(key) for key in source_fields),
                 'Staged source identity differs from original inventory')
    auxiliaries = manifest.get('auxiliary', [])
    _require(isinstance(auxiliaries, list) and all(isinstance(row, dict) for row in auxiliaries), 'Invalid auxiliary inventory')
    all_records = records + auxiliaries
    for record in all_records:
        path = _safe_member(bundle, record.get('path'))
        _require(path.is_file() and type(record.get('size_bytes')) is int and path.stat().st_size == record['size_bytes'] and _sha(path) == record.get('sha256'), 'Source/auxiliary identity changed: ' + str(record.get('path')))
    actual = set()
    for path in bundle.rglob('*'):
        _require(not path.is_symlink(), 'Symbolic links are not admitted')
        if path.is_file():
            actual.add(path.relative_to(bundle).as_posix())
    declared = {record['path'] for record in all_records}
    _require(len(declared) == len(all_records), 'Duplicate output/auxiliary path')
    _require(actual == declared | (_METADATA if admitted else {'manifest.json', 'validation_report.json'}), 'Bundle has missing or unlisted members')
    return manifest, report


def _validate_consumer(bundle, unit_universe, profile_id, study):
    from RP1_Project import create_ba_source_lock
    from RP1_Project import merge_af_ba_panels as merger
    manifest = _json(bundle / 'manifest.json')
    # Recheck semantics/lineage independently of a caller-supplied PASS report.
    units, constants, keys, inventory = core.load_units(unit_universe), {}, set(), []
    for source in manifest['outputs']:
        path = _safe_member(bundle, source['path'])
        core.process_level(c3.parse_filename(path.name, observation_windows=manifest['windows']), path, bundle, inventory, units, constants, keys,
                           observation_windows=manifest['windows'])
        _require(all(inventory[-1].get(key) == source.get(key) for key in
                     ('filename', 'sha256', 'size_bytes', 'rows', 'columns', 'run_ids',
                      'family', 'domain', 'level', 'partition', 'year', 'role')),
                 'Recorded source inventory differs from original CSV contents')
    for source in manifest.get('auxiliary', []):
        core._validate_auxiliary(_safe_member(bundle, source['path']), bundle, [],
                                 windows=manifest['windows'], units=units, constants=constants)
    lock = create_ba_source_lock.build_lock(bundle=bundle, profile=profile_id)
    paths = merger.PathsConfig(repo_root=bundle, unit_universe_path=unit_universe,
        af_root=bundle / 'unused_af', ba2001_root=bundle / 'sources', ba2012_root=bundle / 'sources',
        output_dir=bundle / 'unused_merge', profile_id='c3', profile_contract=PROFILE,
        source_lock_entries=tuple(lock['files']), bundle_manifest_path=bundle / 'manifest.json',
        bundle_handoff_path=bundle / 'handoff.json')
    settings = ('START_YYYYMM', 'END_YYYYMM', 'VIIRS_SUPPORT_START_YYYYMM', 'BA2012_SUPPORT_START_YYYYMM', 'ANALYSIS_OVERLAP_START_YYYYMM', 'EXPECTED_UNITS')
    original = {key: getattr(merger, key) for key in settings}
    results = []
    try:
        merger.configure_study(study)
        unit_frame = merger.load_unit_universe(paths)
        partitions = merger.canonical_partition_codes(unit_frame)
        spines = {level: merger.build_canonical_spine(unit_frame, level) for level in c3.LEVELS}
        for spec in merger.build_family_specs(paths):
            if spec.source_kind in ('ba2001', 'ba2012'):
                loaded = merger.load_family(spec, unit_frame, spines[spec.level], partitions, paths)
                results.append({'family': spec.source_kind, 'level': spec.level, 'rows': len(loaded.data), 'run_ids': loaded.run_ids})
    except merger.ValidationError as exc:
        raise ValueError('c3 source bundle is incompatible with actual merger: ' + str(exc)) from exc
    finally:
        for key, value in original.items():
            setattr(merger, key, value)
    return lock, results


def admit_bundle(stage, report, *, unit_universe, profile_id='c3', study=None, workflow_request_sha256=None):
    stage, unit_universe = Path(stage), Path(unit_universe).resolve()
    _require(profile_id == 'c3', 'Only c3 can be admitted')
    request = _workflow_request_identity(workflow_request_sha256)
    manifest, stored_report = _inspect_bundle(stage, admitted=False)
    _require(report == stored_report, 'In-memory report differs from stored report')
    selected_study = _study(study, _unit_counts(unit_universe), manifest)
    unit_hash = _sha(unit_universe)
    _require(manifest.get('unit_universe_sha256') in (None, unit_hash), 'Canonical geography differs from source validation')
    lock, families = _validate_consumer(stage, unit_universe, profile_id, selected_study)
    _inspect_bundle(stage, admitted=False)
    _require(_sha(unit_universe) == unit_hash, 'Canonical geography changed during admission')
    # Bind geography even when core was invoked with a callback supplying it.
    manifest['unit_universe_sha256'] = unit_hash
    report.update(consumer_validation_status='PASS', geography_validation_status='PASS', unit_universe_sha256=unit_hash)
    for name, value in (('manifest.json', manifest), ('validation_report.json', report)):
        (stage / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    _write_new(stage / 'source_lock.json', lock)
    receipt = {'schema': SCHEMA, 'status': 'PASS', 'merge_ready': True, 'scope': manifest['scope'],
               'profile_id': 'c3', 'profile_contract': PROFILE, 'study': selected_study,
               'unit_universe_sha256': unit_hash, 'unit_universe_path': str(unit_universe),
               'workflow_request_sha256': request, 'implementations': _implementation_hashes(),
               'boundary_label_operator_declared': manifest['boundary_label_operator_declared'],
               'boundary_geometry_verified_by_consolidator': False, 'consumer_validation': families,
               'metadata_sha256': {name: _sha(stage / name) for name in ('manifest.json', 'validation_report.json', 'source_lock.json')}}
    _write_new(stage / 'handoff.json', receipt)
    return receipt


def verify_handoff(bundle, *, unit_universe=None, profile_id='c3', study=None, workflow_request_sha256=None, require_full=False):
    bundle = Path(bundle)
    manifest, _ = _inspect_bundle(bundle, admitted=True)
    receipt = _json(bundle / 'handoff.json')
    unit_universe = Path(unit_universe or receipt.get('unit_universe_path', '')).resolve()
    _require(profile_id == 'c3' and receipt.get('schema') == SCHEMA and receipt.get('status') == 'PASS' and receipt.get('merge_ready') is True, 'No current c3 admission receipt')
    _require(receipt.get('profile_id') == 'c3' and receipt.get('profile_contract') == PROFILE and receipt.get('scope') == manifest['scope'], 'Profile/scope differs from admission')
    _require(not require_full or manifest['scope'] == 'full', 'Pilot bundle cannot satisfy full production admission')
    request = _workflow_request_identity(workflow_request_sha256)
    if request is not None:
        _require(receipt.get('workflow_request_sha256') == request, 'Workflow request differs from admission')
    selected_study = receipt.get('study') if study is None else study
    _require(receipt.get('study') == _study(selected_study, _unit_counts(unit_universe), manifest), 'Study differs from admitted annual coverage')
    _require(receipt.get('unit_universe_sha256') == manifest['unit_universe_sha256'] == _sha(unit_universe), 'Canonical geography changed')
    _require(receipt.get('implementations') == _implementation_hashes(), 'Consumer/preparation/contract implementation changed; readmit')
    _require(receipt.get('metadata_sha256') == {name: _sha(bundle / name) for name in ('manifest.json', 'validation_report.json', 'source_lock.json')}, 'Bundle metadata changed')
    from RP1_Project import create_ba_source_lock
    _require(_json(bundle / 'source_lock.json') == create_ba_source_lock.build_lock(bundle=bundle), 'Lock differs from source inventory')
    return {'ba2001_root': str((bundle / 'sources').resolve()), 'ba2012_root': str((bundle / 'sources').resolve()),
            'source_lock': str((bundle / 'source_lock.json').resolve()), 'bundle_manifest': str((bundle / 'manifest.json').resolve()),
            'bundle_handoff': str((bundle / 'handoff.json').resolve()), 'scope': manifest['scope'], 'study': receipt['study'],
            'manifest_sha256': _sha(bundle / 'manifest.json'), 'handoff_sha256': _sha(bundle / 'handoff.json'),
            'unit_universe_sha256': receipt['unit_universe_sha256'], 'profile_contract': dict(PROFILE),
            'boundary_label_operator_declared': receipt['boundary_label_operator_declared']}
