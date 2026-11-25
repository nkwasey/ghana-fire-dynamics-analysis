#!/usr/bin/env python3
"""Validate and publish immutable annual c3 extended CSV source bundles.

Validation-only uses the standard library and never creates output files.
Publication requires canonical geography and the actual merger's admission.
"""
from __future__ import annotations
import argparse
import csv
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import math
from pathlib import Path
import platform
import re
import shutil
import sys
import tempfile
from typing import Callable
from collections.abc import Mapping

_SRC = Path(__file__).resolve().parents[1] / 'rp1_analysis' / 'src'
_contract_import_path = sys.path[:]
try:
    if str(_SRC) not in sys.path:
        sys.path.insert(0, str(_SRC))
    from rp1_ba_contracts import c3
finally:
    sys.path[:] = _contract_import_path
from RP1_Project.rp1_local_io import preflight_directory_publication, publish_directory_no_replace

VERSION = '2.0.0'
CONTRACT = 'rp1-ba-c3-bundle-v1'
ZONES = c3.ZONES
BASE_COLUMNS = list(c3.FIELDS[:23])  # Projection only, never the input contract.
FIELDS = c3.FIELDS
NATIVE_TRANSFORM = list(c3.GRID)
AREA_TOL = FRACTION_TOL = Decimal('0.00000001')
ValidationError = c3.C3ValidationError
_AUXILIARY = re.compile(r'^rp1_ba_district_monthly_c3_(CZ|FZ|GS|SS|TZ)_BA(2001|2012)_([0-9]{4})-([0-9]{4})_qa_by_acz\.csv$')
IDENTITY_FIELDS = ('level', 'unit_id', 'unit_code', 'unit_name', 'parent_level', 'parent_id', 'parent_code', 'parent_name')
UNIT_COLUMNS = ('unit_type', *IDENTITY_FIELDS, 'area_sqkm')


@dataclass(frozen=True)
class ConsolidationOptions:
    input_dir: Path
    output_dir: Path
    families: tuple[int, ...] = (2001, 2012)
    zones: tuple[str, ...] = tuple(ZONES)
    start_year: int | None = None
    end_year: int = 2024
    boundary_label: str = 'unspecified'
    validate_only: bool = False
    levels: tuple[str, ...] = c3.LEVELS
    unit_universe: Path | None = None
    scope: str = 'auto'
    observation_windows: Mapping | None = None


def require(condition, message):
    if not condition:
        raise ValidationError(message)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def number(value, label, *, nullable=False):
    if value in ('', None) and nullable:
        return None
    try:
        result = Decimal(str(value))
    except InvalidOperation:
        raise ValidationError(f'{label}: invalid number {value!r}') from None
    require(result.is_finite(), f'{label}: nonfinite numeric value')
    return result


def integer(value, label):
    result = number(value, label)
    require(result == result.to_integral_value(), f'{label}: expected integer')
    return int(result)


def read_csv(path: Path, root: Path, inventory: list) -> tuple[list, list]:
    require(not path.is_symlink(), f'Symbolic link input is not accepted: {path}')
    raw = path.read_bytes()
    try:
        reader = csv.reader(io.StringIO(raw.decode('utf-8-sig'), newline=''), strict=True)
        header = next(reader)
        require(header and len(header) == len(set(header)), f'{path.name}: missing/duplicate header')
        rows = []
        for line, cells in enumerate(reader, 2):
            require(len(cells) == len(header), f'{path.name}:{line}: row/header length mismatch')
            require(not any('\x00' in value for value in cells), f'{path.name}:{line}: NUL character')
            rows.append(dict(zip(header, cells)))
        require(bool(rows), f'{path.name}: no data rows')
    except (UnicodeError, csv.Error, StopIteration) as exc:
        raise ValidationError(f'{path.name}: invalid CSV: {exc}') from exc
    inventory.append({'path': path.relative_to(root).as_posix(), 'filename': path.name,
                      'sha256': digest(raw), 'size_bytes': len(raw), 'rows': len(rows),
                      'columns': len(header), 'run_ids': sorted({r.get('run_id', '') for r in rows} - {''})})
    return header, rows


def parse_file(path: Path, family: int | None = None, *, observation_windows=None) -> dict:
    identity = c3.parse_filename(path.name, observation_windows=observation_windows)
    if family is not None:
        require(identity['domain'] == f'BA{family}', f'{path.name}: wrong domain')
    return identity


def selection(args: ConsolidationOptions) -> tuple[dict, list, list, str]:
    families = sorted(set(args.families))
    zones, levels = sorted(set(args.zones)), sorted(set(args.levels))
    require(families and set(families) <= {2001, 2012}, 'Select BA2001 and/or BA2012')
    require(zones and set(zones) <= set(ZONES), 'Select canonical c3 zones')
    require(levels and set(levels) <= set(c3.LEVELS), 'Select acz and/or district')
    windows = {f'BA{family}': [family if args.start_year is None else max(family, args.start_year), args.end_year] for family in families}
    c3.expected_identities(windows, zones, levels)
    declared = {name: list(bounds) for name, bounds in c3.declared_observation_windows(args.observation_windows).items()}
    require(set(windows) <= set(declared) and all(declared[name][0] <= bounds[0] <= bounds[1] <= declared[name][1] for name, bounds in windows.items()),
            'Selected export years lie outside declared observation coverage')
    full = windows == declared and set(declared) == set(c3.DOMAIN_WINDOWS) and zones == sorted(ZONES) and levels == sorted(c3.LEVELS)
    require(args.scope in ('auto', 'full', 'pilot'), 'scope must be auto, full or pilot')
    require(args.scope != 'full' or full, 'Full scope requires both domains, all five zones, both levels and every export year')
    scope = ('full' if full else 'pilot') if args.scope == 'auto' else args.scope
    return windows, zones, levels, scope


def discover(root: Path, windows: dict, zones: list, levels: list) -> tuple[dict, list, list, list]:
    expected = c3.expected_identities(windows, zones, levels)
    found, auxiliary, skipped, unconsumed = {}, [], [], []
    seen = set()
    def outside(path, identity=None):
        raw = path.read_bytes()
        unconsumed.append({'path': path.relative_to(root).as_posix(), 'filename': path.name,
            'sha256': digest(raw), 'size_bytes': len(raw),
            'classification': 'outside_declared_delivery', 'validation_status': 'NOT_CONSUMED',
            **(identity or {})})
    for path in sorted(root.rglob('*')):
        require(not path.is_symlink(), f'Symbolic links are not admitted: {path}')
        if not path.is_file():
            continue
        require(path.resolve().is_relative_to(root), f'Input escapes release root: {path}')
        if path.suffix.lower() != '.csv':
            skipped.append(path.relative_to(root).as_posix())
            continue
        if _AUXILIARY.fullmatch(path.name):
            _, family, start, end = _AUXILIARY.fullmatch(path.name).groups()
            bounds = windows.get('BA'+family)
            if bounds is None or not bounds[0] <= int(start) <= int(end) <= bounds[1]:
                outside(path)
            else:
                auxiliary.append(path)
            continue
        # Classify every recognised annual source; only the explicitly selected
        # calendar can enter the consumer bundle. Source years are not inferred.
        identity = parse_file(path, observation_windows={name: (bounds[0], 9999) for name, bounds in c3.DOMAIN_WINDOWS.items()})
        key = tuple(identity[f] for f in ('family', 'level', 'partition', 'year'))
        require(key not in seen, f'Duplicate annual source identity {key}: {path.name}')
        seen.add(key)
        if key not in expected:
            outside(path, identity)
            continue
        found[key] = path
    require(set(found) == expected, f'Missing annual c3 files: {sorted(expected-set(found))}')
    return found, auxiliary, skipped, unconsumed


def load_units(path: Path | None) -> dict:
    if path is None:
        return {}
    require(path.is_file() and not path.is_symlink(), f'Missing/symlinked unit universe: {path}')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames and len(reader.fieldnames) == len(set(reader.fieldnames)) and set(UNIT_COLUMNS) == set(reader.fieldnames), 'Unit universe must have the exact canonical header')
        rows = list(reader)
    result = {}
    for row in rows:
        require(None not in row and all(value is not None for value in row.values()), 'Malformed unit universe row')
        key = row['level'], row['unit_id']
        require(key[0] in c3.LEVELS and key[1] and key not in result, 'Invalid/duplicate unit universe identity')
        require(row['unit_name'].strip() and row['unit_type'] == ('zone' if key[0] == 'acz' else 'district') and number(row['area_sqkm'], 'unit area') > 0, 'Invalid canonical unit name/type/area')
        result[key] = row
    zones = {r['unit_code']: r for (level, _), r in result.items() if level == 'acz'}
    require(set(zones) == set(ZONES) and sum(level == 'acz' for level, _ in result) == 5, 'Unit universe must contain the five canonical zones exactly once')
    for code, row in zones.items():
        require(row['unit_id'] == ZONES[code] and not any(row[f] for f in IDENTITY_FIELDS[4:]), 'Invalid ACZ geography identity')
    districts = [r for (level, _), r in result.items() if level == 'district']
    require(bool(districts), 'Unit universe has no districts')
    for row in districts:
        require(row['parent_level'] == 'acz' and row['parent_code'] in zones, 'Invalid district parent')
        parent = zones[row['parent_code']]
        require(row['parent_id'] == parent['unit_id'] and row['parent_name'] == parent['unit_name'], 'District parent attributes differ from geography')
    return result


def _equal_constant(constants, key, value, label, *, numeric=False):
    if value == '':
        return
    if key in constants:
        previous = constants[key]
        same = math.isclose(float(previous), float(value), abs_tol=1e-8, rel_tol=1e-10) if numeric else previous == value
        require(same, f'{label}: fixed domain/source/geography drift')
    else:
        constants[key] = value


def process_level(identity: dict, path: Path, root: Path, inventory: list, units: dict, constants: dict, keys: set, *, observation_windows=None) -> dict:
    header, rows = read_csv(path, root, inventory)
    c3.validate_header(header)
    expected_units = {uid for (level, uid), row in units.items() if level == identity['level'] and row['unit_code' if level == 'acz' else 'parent_code'] == identity['partition']}
    actual, source_runs, status_counts, coverage_counts = set(), set(), {}, {}
    for line, row in enumerate(rows, 2):
        key = row['ba_domain'], row['level'], row['unit_id'], integer(row['yyyymm'], path.name)
        require(key not in keys, f'{path.name}:{line}: duplicate unit-month key {key}')
        keys.add(key)
        unit = units.get((row['level'], row['unit_id'])) if units else None
        require(not units or unit is not None, f'{path.name}:{line}: noncanonical unit')
        try:
            c3.validate_row(row, identity=identity, unit=unit, observation_windows=observation_windows)
        except ValueError as exc:
            raise ValidationError(f'{path.name}:{line}: {exc}') from exc
        actual.add((row['unit_id'], int(row['yyyymm'])))
        source_runs.add(row['run_id'])
        status_counts[row['ba_status']] = status_counts.get(row['ba_status'], 0) + 1
        coverage_counts[row['ba_coverage_status']] = coverage_counts.get(row['ba_coverage_status'], 0) + 1
        uid, domain = row['unit_id'], row['ba_domain']
        for field in IDENTITY_FIELDS:
            _equal_constant(constants, ('identity', row['level'], uid, field), row[field], path.name)
        for field in ('ba_product', 'ba_lc_product', 'ba_grid_crs', 'ba_grid_transform', 'ba_reducer', 'ba_ghana_asset'):
            _equal_constant(constants, ('method', field), row[field], path.name)
        _equal_constant(constants, ('boundary', row['level']), row['ba_boundary_asset'], path.name)
        _equal_constant(constants, ('lc', domain), row['ba_lc_source_indexes'], path.name)
        for reference_year, index in enumerate(row['ba_lc_source_indexes'].split('|'), c3.DOMAIN_WINDOWS[domain][0]):
            _equal_constant(constants, ('lc_year', reference_year), index, path.name)
        if row.get('ba_annual_lc_source_index'):
            _equal_constant(constants, ('lc_year', identity['year']), row['ba_annual_lc_source_index'], path.name)
        _equal_constant(constants, ('ba_source', row['yyyymm']), row['ba_source_index'], path.name)
        for field in ('ba_known_union_area_km2', 'ba_domain_unresolved_km2', 'ba_domain_excluded_km2',
                      'ba_any_lc_missing_year_km2', 'ba_any_lw_missing_year_km2',
                      'ba_any_lc_invalid_year_km2', 'ba_any_lw_invalid_year_km2', 'modis_aoi_area_land_km2'):
            _equal_constant(constants, ('fixed', domain, row['level'], uid, field), row[field], path.name, numeric=True)
        _equal_constant(constants, ('annual', domain, row['level'], uid, identity['year']), row['modis_burnable_km2_annual'], path.name, numeric=True)
        _equal_constant(constants, ('annual_unknown', domain, row['level'], uid, identity['year']), row['ba_annual_unknown_km2'], path.name, numeric=True)
    require(len(source_runs) == 1, f'{path.name}: expected one original task run_id')
    if not units:
        expected_units = {uid for uid, _ in actual}
    require(expected_units and (identity['level'] != 'acz' or len(expected_units) == 1), f'{path.name}: invalid selected unit set')
    expected = {(uid, identity['year'] * 100 + month) for uid in expected_units for month in range(1, 13)}
    require(actual == expected, f'{path.name}: incomplete unit/calendar coverage; missing={sorted(expected-actual)[:20]} extra={sorted(actual-expected)[:20]}')
    inventory[-1].update(identity)
    return {'family': identity['family'], 'level': identity['level'], 'partition': identity['partition'], 'year': identity['year'], 'rows': len(rows), 'units': len(expected_units), 'status_counts': status_counts, 'coverage_counts': coverage_counts}


def _validate_auxiliary(path, root, inventory, *, windows=None, units=None, constants=None):
    header, rows = read_csv(path, root, inventory)
    required = {'schema_version', 'domain', 'zone_id', 'zone_code', 'district_filter', 'selected_unit_count', 'raw_asset_zone_count', 'identity_preflight', 'geometry_preflight', 'source_preflight', 'start_year', 'end_year', 'boundary_asset', 'ghana_asset'}
    require(set(header) - set(c3.OPTIONAL_FIELDS) == required, f'{path.name}: unsupported auxiliary receipt schema')
    require(len(rows) == 1, f'{path.name}: expected one optional inventory receipt')
    zone, family, start, end = _AUXILIARY.fullmatch(path.name).groups()
    for row in rows:
        require(row['schema_version'] == 'c3_unit_inventory_v1' and row['domain'] in c3.DOMAIN_WINDOWS, f'{path.name}: unsupported auxiliary receipt')
        require(row['zone_code'] in ZONES and row['zone_id'] == ZONES[row['zone_code']], f'{path.name}: invalid receipt zone')
        require(row['domain'] == 'BA' + family and row['zone_code'] == zone and
                integer(row['start_year'], 'receipt start') == int(start) and
                integer(row['end_year'], 'receipt end') == int(end), f'{path.name}: receipt filename/content mismatch')
        require(not row['district_filter'] and integer(row['selected_unit_count'], 'selected units') > 0 and
                integer(row['raw_asset_zone_count'], 'raw units') >= integer(row['selected_unit_count'], 'selected units'),
                f'{path.name}: invalid/subset receipt population')
        require(row['identity_preflight'] == row['source_preflight'] == 'PASSED' and
                row['geometry_preflight'] == 'CLIPPED_NONZERO_AREA_ONLY' and row['boundary_asset'] and row['ghana_asset'],
                f'{path.name}: invalid receipt preflight')
        if windows is not None:
            bounds = windows.get(row['domain'])
            require(bounds is not None and bounds[0] <= int(start) <= int(end) <= bounds[1],
                    f'{path.name}: receipt is outside declared delivery')
        if units:
            expected = sum(level == 'district' and unit['parent_code'] == zone for (level, _), unit in units.items())
            require(integer(row['selected_unit_count'], 'selected units') == expected,
                    f'{path.name}: receipt population differs from canonical geography')
        if constants:
            require(row['boundary_asset'] == constants.get(('boundary', 'district')) and
                    row['ghana_asset'] == constants.get(('method', 'ba_ghana_asset')),
                    f'{path.name}: receipt assets differ from analytical sources')
    inventory[-1]['classification'] = 'optional_unit_inventory_receipt'


def consolidate(args: ConsolidationOptions, *, pre_publish: Callable | None = None) -> dict:
    raw_output, raw_root = Path(args.output_dir).expanduser(), Path(args.input_dir).expanduser()
    require(not raw_output.is_symlink() and not raw_root.is_symlink(), 'Symbolic link input/output root is not accepted')
    root, output = raw_root.resolve(), raw_output.resolve()
    require(root.is_dir(), f'Input directory does not exist: {root}')
    require(root != output and root not in output.parents and output not in root.parents, 'Input/output directories must be disjoint')
    if not args.validate_only:
        require(not output.exists(), f'Output already exists: {output}')
        require(args.unit_universe is not None or pre_publish is not None, 'Publication requires canonical geography and actual consumer admission')
    windows, zones, levels, scope = selection(args)
    groups, auxiliary, skipped, unconsumed = discover(root, windows, zones, levels)
    declared = {name: list(bounds) for name, bounds in c3.declared_observation_windows(args.observation_windows).items()}
    unit_path = Path(args.unit_universe).resolve() if args.unit_universe is not None else None
    units = load_units(unit_path)
    unit_hash = digest(unit_path.read_bytes()) if unit_path else None
    inventory, products, auxiliary_inventory, constants, keys = [], [], [], {}, set()
    for _, path in sorted(groups.items()):
        products.append(process_level(parse_file(path, observation_windows=windows), path, root, inventory, units, constants, keys,
                                      observation_windows=windows))
    for path in auxiliary:
        _validate_auxiliary(path, root, auxiliary_inventory, windows=windows, units=units, constants=constants)
    report = {'status': 'PASS', 'contract': CONTRACT, 'version': VERSION, 'scope': scope,
              'coverage': 'complete' if scope == 'full' else 'pilot', 'windows': windows,
              'declared_observation_windows': declared, 'unconsumed_sources': unconsumed,
              'domain_windows': {k: list(v) for k, v in c3.DOMAIN_WINDOWS.items()}, 'zones': zones, 'levels': levels,
              'source_schema': c3.SCHEMA, 'method_version': c3.METHOD, 'profile_contract': c3.PROFILE,
              'consumer_validation_status': 'NOT_RUN', 'geography_validation_status': 'PASS' if units else 'NOT_RUN',
              'unit_universe_sha256': unit_hash, 'input_files': len(inventory), 'products': products,
              'auxiliary_files': len(auxiliary_inventory), 'skipped_files': skipped, 'python': platform.python_version(),
              'script_sha256': digest(Path(__file__).read_bytes()), 'contract_sha256': digest(Path(c3.__file__).read_bytes()),
              'boundary_label_operator_declared': args.boundary_label, 'boundary_geometry_verified_by_this_script': False,
              'limits': ['CSV identity/internal arithmetic does not establish remote geometry identity or physical-fire accuracy.']}
    def verify_sources():
        for record in inventory + auxiliary_inventory + unconsumed:
            require(digest((root / record['path']).read_bytes()) == record['sha256'], f"Source changed during validation: {record['path']}")
        if unit_path:
            require(digest(unit_path.read_bytes()) == unit_hash, 'Unit universe changed during preparation')
    verify_sources()
    if args.validate_only:
        return report
    preflight_directory_publication(output)
    stage = Path(tempfile.mkdtemp(prefix=f'.{output.name}.staging-', dir=output.parent))
    try:
        outputs, auxiliary_outputs = [], []
        for records, subdir, destinations in ((inventory, 'sources', outputs), (auxiliary_inventory, 'auxiliary', auxiliary_outputs)):
            for record in records:
                relative = f"{subdir}/{record['filename']}"
                destination = stage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                require(not destination.exists(), f'Duplicate destination filename: {relative}')
                shutil.copyfile(root / record['path'], destination)
                require(digest(destination.read_bytes()) == record['sha256'], f'Staged source differs: {relative}')
                destinations.append(record | {'path': relative, 'origin_relative_path': record['path']})
        fields = ('contract', 'version', 'scope', 'coverage', 'windows', 'domain_windows', 'declared_observation_windows', 'unconsumed_sources', 'zones', 'levels', 'source_schema', 'method_version', 'profile_contract', 'script_sha256', 'contract_sha256', 'unit_universe_sha256', 'boundary_label_operator_declared')
        manifest = {key: report[key] for key in fields}
        manifest.update(inputs=inventory, outputs=outputs, auxiliary=auxiliary_outputs)
        for name, value in (('manifest.json', manifest), ('validation_report.json', report)):
            (stage / name).write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
        if pre_publish is not None:
            pre_publish(stage, report)
        else:
            from .handoff import admit_bundle
            admit_bundle(stage, report, unit_universe=unit_path)
        require((stage / 'handoff.json').is_file() and (stage / 'source_lock.json').is_file(), 'Consumer callback did not admit the bundle')
        from .handoff import verify_handoff
        verify_handoff(stage, unit_universe=unit_path)
        verify_sources()
        publish_directory_no_replace(stage, output)
        return report
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument('--input-dir', type=Path, required=True)
    result.add_argument('--output-dir', type=Path, required=True, help='Fresh destination; validate-only never writes it')
    result.add_argument('--unit-universe', type=Path, help='Canonical geography; required for writing/admission')
    result.add_argument('--families', nargs='+', type=int, choices=[2001, 2012], default=[2001, 2012])
    result.add_argument('--zones', nargs='+', choices=list(ZONES), default=list(ZONES))
    result.add_argument('--levels', nargs='+', choices=list(c3.LEVELS), default=list(c3.LEVELS))
    result.add_argument('--start-year', type=int)
    result.add_argument('--end-year', type=int, default=2024)
    result.add_argument('--observation-start-year', type=int, help='Explicit complete observation-period start; requires --observation-end-year')
    result.add_argument('--observation-end-year', type=int, help='Explicit complete observation-period end; does not change fixed union years')
    result.add_argument('--scope', choices=['auto', 'full', 'pilot'], default='auto')
    result.add_argument('--boundary-label', default='unspecified')
    result.add_argument('--validate-only', action='store_true')
    result.add_argument('--version', action='version', version=VERSION)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        options = vars(args).copy()
        start, end = options.pop('observation_start_year'), options.pop('observation_end_year')
        require((start is None) == (end is None), 'Declare both observation-period endpoints')
        if start is not None:
            options['observation_windows'] = c3.observation_windows(start, end)
        report = consolidate(ConsolidationOptions(**options))
    except (ValueError, OSError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2
    print(f"PASS: {report['input_files']} annual c3 sources; scope={report['scope']}; consumer={report['consumer_validation_status']}")
    if args.validate_only:
        print('Validation only: no files written.')
    return 0
