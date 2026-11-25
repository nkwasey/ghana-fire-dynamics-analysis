"""Pure c3 source contract, derived from the pinned c3 v2 CSV checker.

No analysis, pandas or geospatial imports. Validation never rewrites records.
The row arithmetic/status checks preserve the upstream checker semantics.
"""
from __future__ import annotations

import math
import re
from collections.abc import Mapping

REQUIRED = ('run_id', 'schema_version', 'level', 'unit_id', 'unit_code', 'unit_name', 'parent_level', 'parent_id', 'parent_code', 'parent_name', 'yyyymm', 'year', 'month', 'modis_ba_km2', 'modis_burned_pixel_count', 'modis_ba_any', 'modis_burnable_km2_union', 'modis_burnable_km2_annual', 'modis_burned_frac_union', 'modis_burned_frac_annual', 'modis_aoi_area_land_km2', 'modis_zero_union_den_flag', 'modis_zero_annual_den_flag', 'ba_domain', 'ba_domain_start_year', 'ba_domain_end_year', 'ba_status', 'ba_coverage_status', 'ba_source_status', 'ba_source_count', 'ba_source_index', 'ba_lc_source_indexes', 'ba_product', 'ba_lc_product', 'ba_boundary_asset', 'ba_ghana_asset', 'ba_grid_crs', 'ba_grid_transform', 'ba_reducer', 'ba_sampled_pixel_count', 'ba_known_union_area_km2', 'ba_known_union_burned_km2', 'ba_domain_unresolved_km2', 'ba_domain_excluded_km2', 'ba_any_lc_missing_year_km2', 'ba_any_lw_missing_year_km2', 'ba_any_lc_invalid_year_km2', 'ba_any_lw_invalid_year_km2', 'ba_annual_unknown_km2', 'ba_state_qa_missing_km2', 'ba_state_burndate_masked_km2', 'ba_state_unsupported_km2', 'ba_state_explicit_zero_km2', 'ba_state_accepted_km2', 'ba_reason_qa_missing_km2', 'ba_reason_burndate_masked_km2', 'ba_reason_qa_nonland_km2', 'ba_reason_qa_invalid_km2', 'ba_reason_shortened_km2', 'ba_reason_special_km2', 'ba_reason_positive_special_km2', 'ba_reason_unexpected_burndate_km2', 'ba_anomaly_area_km2', 'ba_anomaly_pixel_count', 'ba_shortened_km2', 'ba_full_period_only_km2', 'ba_supported_area_km2', 'ba_supported_fraction', 'ba_state_closure_km2')
KEYS=('ba_domain','level','unit_id','yyyymm')
TEXT=('run_id','schema_version','level','unit_id','unit_code','unit_name','parent_level','parent_id','parent_code','parent_name',
      'ba_domain','ba_status','ba_coverage_status','ba_source_status','ba_source_index','ba_lc_source_indexes',
      'ba_product','ba_lc_product','ba_boundary_asset','ba_ghana_asset','ba_grid_crs','ba_grid_transform','ba_reducer')
STATES=('ba_state_qa_missing_km2','ba_state_burndate_masked_km2','ba_state_unsupported_km2',
        'ba_state_explicit_zero_km2','ba_state_accepted_km2')
REASONS=tuple(x for x in REQUIRED if x.startswith('ba_reason_'))
AREA_FIELDS=tuple(x for x in REQUIRED if x.endswith('_km2') and x!='ba_state_closure_km2')
RASTER_FIELDS=tuple(x for x in REQUIRED if x.startswith('modis_') and x!='modis_aoi_area_land_km2')+(
 'ba_known_union_area_km2','ba_known_union_burned_km2','ba_domain_unresolved_km2','ba_domain_excluded_km2',
 'ba_any_lc_missing_year_km2','ba_any_lw_missing_year_km2','ba_any_lc_invalid_year_km2','ba_any_lw_invalid_year_km2',
 'ba_annual_unknown_km2','ba_shortened_km2','ba_full_period_only_km2','ba_supported_area_km2',
 'ba_supported_fraction','ba_state_closure_km2','ba_anomaly_area_km2','ba_anomaly_pixel_count')+STATES+REASONS
C3_STATUS={'ADMITTED','SOURCE_PIXEL_ANOMALY','DOMAIN_UNRESOLVED','ZERO_UNION_DENOMINATOR','NO_PIXEL_CENTRES','REDUCTION_INCOMPLETE','ACCOUNTING_INCONSISTENCY','EMPTY_REDUCTION_UNRESOLVED'}
COVERAGE={'EMPTY_REDUCTION_UNRESOLVED','ACCOUNTING_INCONSISTENCY','REDUCTION_INCOMPLETE','NO_PIXEL_CENTRES','NO_KNOWN_UNION_PIXELS','NO_SUPPORTED_EVIDENCE',
          'PARTIAL_EVIDENCE','FULL_EVIDENCE_WITH_SHORTENING','FULL_EVIDENCE_NO_SHORTENING'}
DOMAINS={'BA2001':(2001,2024),'BA2012':(2012,2024)}
GRID=(463.3127165279165,0,-20015109.354,0,-463.3127165279167,7783653.6376640005)

def number(row,key):
    s=row.get(key,'')
    if s is None or isinstance(s,list): raise ValueError(f'{key}: malformed or short row')
    s=s.strip()
    if not s: return None
    try: v=float(s)
    except ValueError: raise ValueError(f'{key}: invalid number {s!r}')
    if not math.isfinite(v): raise ValueError(f'{key}: non-finite number {s!r}')
    return v

def integer(row,key):
    v=number(row,key)
    if v is None or not v.is_integer(): raise ValueError(f'{key}: expected integer, got {v}')
    return int(v)

def close(a,b,atol,rtol): return math.isclose(a,b,abs_tol=atol,rel_tol=rtol)

def _validate_rows(rows,atol,rtol,allow_technical=False,observation_windows=None):
    observation = declared_observation_windows(observation_windows)
    errors=[]
    for key,row in rows.items():
        def err(msg): errors.append(f'{key}: {msg}')
        try:
            missing=set(REQUIRED)-set(row)
            if missing: err(f'missing fields {sorted(missing)}');continue
            if None in row or any(v is None or isinstance(v,list) for v in row.values()):err('malformed row width');continue
            N=lambda k:number(row,k)
            def eq(a,b,msg):
                if a is None or b is None or not close(a,b,atol,rtol):err(f'{msg}: {a} versus {b}')
            # Validate every required non-text value even when it is a null.
            for field in REQUIRED:
                if field not in TEXT:N(field)
            for field in AREA_FIELDS:
                v=N(field)
                if v is not None and v < -atol:err(f'{field}: negative area {v}')
            for field in ('run_id','schema_version','level','unit_id','unit_name','ba_domain','ba_status',
                          'ba_coverage_status','ba_source_status','ba_source_index','ba_lc_source_indexes',
                          'ba_product','ba_lc_product','ba_boundary_asset','ba_ghana_asset','ba_grid_crs',
                          'ba_grid_transform','ba_reducer'):
                if not row[field].strip():err(f'{field}: required text is blank')
            if row['schema_version']!='rp1_ba_c3_extended_v2':err('unsupported schema_version')
            domain_name=row['ba_domain'];level=row['level'];status=row['ba_status'];cov=row['ba_coverage_status']
            if domain_name not in DOMAINS:err('invalid domain')
            if level not in ('acz','district'):err('invalid level')
            if status not in C3_STATUS:err('invalid ba_status')
            if cov not in COVERAGE:err('invalid ba_coverage_status')
            year,month,ym=integer(row,'year'),integer(row,'month'),integer(row,'yyyymm')
            if month<1 or month>12 or ym!=year*100+month:err('inconsistent year/month/yyyymm')
            if domain_name in DOMAINS:
                start,end=DOMAINS[domain_name]
                bounds = observation.get(domain_name)
                if bounds is None or not bounds[0]<=year<=bounds[1] or integer(row,'ba_domain_start_year')!=start or integer(row,'ba_domain_end_year')!=end:
                    err('year/domain bounds mismatch')
                indexes=row['ba_lc_source_indexes'].split('|')
                if len(indexes)!=end-start+1 or any(not v.strip() for v in indexes) or len(set(indexes))!=len(indexes):
                    err('incorrect, blank or duplicate LC source indexes')
                annual_index = row.get('ba_annual_lc_source_index', '').strip()
                if annual_index and re.fullmatch(r'[A-Za-z0-9_-]+', annual_index) is None:
                    err('invalid annual LC source index')
                if not start<=year<=end and not annual_index:
                    err('annual LC source index required outside fixed union period')
                if not start<=year<=end and annual_index and annual_index != f'{year:04d}_01_01':
                    err('annual LC source index does not match observation year')
                if start<=year<=end and annual_index and len(indexes)==end-start+1 and annual_index != indexes[year-start]:
                    err('annual LC source index differs from fixed-union source')
            if level=='district' and (row['parent_level']!='acz' or not row['parent_id'].strip()):err('district parent identity missing')
            if level=='acz' and row['parent_level'].strip():err('unexpected ACZ parent level')
            if row['ba_source_status']!='ADMITTED' or integer(row,'ba_source_count')!=1:err('unexpected source admission')
            if row['ba_product']!='MODIS/061/MCD64A1' or row['ba_lc_product']!='MODIS/061/MCD12Q1':err('unexpected MODIS product ID')
            if row['ba_grid_crs']!='SR-ORG:6974' or row['ba_reducer']!='sum_unweighted_centroid':err('unexpected grid or reducer')
            try:
                transform=[float(x) for x in row['ba_grid_transform'].split(',')]
                if len(transform)!=6 or any(not math.isfinite(v) or abs(v-ref)>1e-6 for v,ref in zip(transform,GRID)):
                    err('unexpected affine transform')
            except ValueError:err('invalid affine transform')
            for f in ('modis_burned_frac_union','ba_supported_fraction'):
                v=N(f)
                if v is not None and (v < -atol or v > 1+atol):err(f'{f}: outside [0,1]')
            if N('modis_burned_frac_annual') is not None and N('modis_burned_frac_annual') < -atol:err('negative annual ratio')
            if status in ('REDUCTION_INCOMPLETE','ACCOUNTING_INCONSISTENCY','EMPTY_REDUCTION_UNRESOLVED'):
                if cov!=status:err('failure coverage status mismatch')
                for f in RASTER_FIELDS:
                    if N(f) is not None:err(f'{f} must be null on {status}')
                if N('ba_sampled_pixel_count') is not None:
                    err(f'sample count must be null on {status}')
                if not allow_technical and status=='REDUCTION_INCOMPLETE':err('incomplete Earth Engine reduction; investigate withheld fields')
                if not allow_technical and status=='ACCOUNTING_INCONSISTENCY':err('Earth Engine accounting inconsistency; investigate withheld fields and diagnostic output')
                if not allow_technical and status=='EMPTY_REDUCTION_UNRESOLVED':err('independent reference reduction missing or null; investigate withheld fields')
                continue
            count=N('ba_sampled_pixel_count'); domain=N('ba_known_union_area_km2'); ba=N('ba_known_union_burned_km2')
            unresolved=N('ba_domain_unresolved_km2'); annual_unknown=N('ba_annual_unknown_km2')
            if count is None or count<0 or not count.is_integer(): err('invalid sample count');continue
            if count==0:
                if status!='NO_PIXEL_CENTRES' or cov!='NO_PIXEL_CENTRES':err('zero centres have wrong status')
                for f in RASTER_FIELDS:
                    if N(f) is not None:err(f'zero-centre {f} must be null')
                continue
            for f in ('ba_known_union_area_km2','ba_known_union_burned_km2','ba_domain_unresolved_km2',
                      'ba_annual_unknown_km2','ba_domain_excluded_km2','ba_any_lc_missing_year_km2',
                      'ba_any_lw_missing_year_km2','ba_any_lc_invalid_year_km2','ba_any_lw_invalid_year_km2')+STATES+REASONS:
                if N(f) is None:err(f'{f}: null with sampled centres')
            if any(x is None for x in (domain,ba,unresolved,annual_unknown)):continue
            anomaly_area=N('ba_anomaly_area_km2'); anomaly_count=N('ba_anomaly_pixel_count')
            if anomaly_area is None or anomaly_count is None:err('anomaly diagnostics missing');continue
            if anomaly_count<0 or not anomaly_count.is_integer() or anomaly_count>count:err('invalid anomaly pixel count')
            if (anomaly_count>0)!=(anomaly_area>0):err('anomaly count/area inconsistent')
            excluded=N('ba_domain_excluded_km2')
            # For non-withheld rows the three domain areas partition the
            # sampled grid; this approximates the core's independent grid-area
            # scale. The independent area itself is not exported.
            grid_proxy=domain+unresolved+(excluded if excluded is not None else 0)
            area_tol=max(atol,rtol*abs(grid_proxy))
            if N('ba_state_unsupported_km2') is not None and anomaly_area>N('ba_state_unsupported_km2')+area_tol:
                err('anomaly area exceeds unsupported state')
            def area_eq(a,b,msg):
                if a is None or b is None or abs(a-b)>area_tol:err(f'{msg}: {a} versus {b}')
            if ba>domain+area_tol:err('known-domain BA exceeds its domain')
            state=[N(k) for k in STATES]
            if None not in state:
                area_eq(sum(state),domain,'state partition closure')
                area_eq(state[-1],ba,'accepted state versus known-domain BA')
                area_eq(N('ba_state_closure_km2'),sum(state)-domain,'closure diagnostic')
                area_eq(N('ba_reason_qa_missing_km2'),state[0],'QA missing reason versus state')
            for f in REASONS:
                v=N(f)
                if v is not None and v>domain+area_tol:err(f'{f}: reason area exceeds known union')
            shortened=N('ba_shortened_km2');full=N('ba_full_period_only_km2')
            if shortened is None or full is None:err('missing BA sensitivity areas')
            else:
                area_eq(shortened+full,ba,'shortened/full BA decomposition')
                reason_short=N('ba_reason_shortened_km2')
                if reason_short is not None and shortened>reason_short+area_tol:err('shortened BA exceeds shortened reason area')
            supported=N('ba_supported_area_km2')
            if supported is None:err('missing support area')
            else:
                if None not in state:area_eq(supported,state[-1]+state[-2],'support area')
                if supported>0:eq(N('ba_supported_fraction'),ba/supported,'supported fraction')
                elif N('ba_supported_fraction') is not None:err('zero support fraction must be null')
                if domain==0:expected_cov='NO_KNOWN_UNION_PIXELS'
                elif supported==0:expected_cov='NO_SUPPORTED_EVIDENCE'
                elif None not in state and sum(state[:3])>0:expected_cov='PARTIAL_EVIDENCE'
                elif N('ba_reason_shortened_km2') and N('ba_reason_shortened_km2')>0:expected_cov='FULL_EVIDENCE_WITH_SHORTENING'
                else:expected_cov='FULL_EVIDENCE_NO_SHORTENING'
                if cov!=expected_cov:err(f'coverage status inconsistent: {cov} versus {expected_cov}')
            if unresolved>0:
                if status!='DOMAIN_UNRESOLVED':err('unresolved membership not reported')
                for f in ('modis_ba_km2','modis_burned_pixel_count','modis_ba_any','modis_burnable_km2_union',
                          'modis_burned_frac_union','modis_zero_union_den_flag'):
                    if N(f) is not None:err(f'{f} must be null when union unresolved')
            elif anomaly_count>0:
                if status!='SOURCE_PIXEL_ANOMALY':err('source anomaly not reported')
                for f in ('modis_ba_km2','modis_burned_pixel_count','modis_ba_any','modis_burnable_km2_union',
                          'modis_burned_frac_union','modis_burned_frac_annual'):
                    if N(f) is not None:err(f'{f} must be null for anomaly')
                if N('modis_zero_union_den_flag')!=int(domain==0):err('incorrect zero-union flag')
            else:
                area_eq(N('modis_ba_km2'),ba,'primary BA')
                area_eq(N('modis_burnable_km2_union'),domain,'primary union')
                pixels=N('modis_burned_pixel_count');any_ba=N('modis_ba_any');zero=N('modis_zero_union_den_flag')
                if pixels is None or not pixels.is_integer() or pixels<0 or pixels>count:err('invalid burned pixel count')
                elif (pixels>0)!=(ba>0):err('burned pixel count and burned area disagree on whether burning is positive')
                if any_ba!=int(ba>0):err('incorrect BA-any flag')
                if zero!=int(domain==0):err('incorrect zero-union flag')
                if domain>0:
                    if status!='ADMITTED':err('positive resolved union status mismatch')
                    eq(N('modis_burned_frac_union'),ba/domain,'union fraction')
                else:
                    if status!='ZERO_UNION_DENOMINATOR':err('zero union status mismatch')
                    if N('modis_burned_frac_union') is not None:err('zero union fraction must be null')
            annual=N('modis_burnable_km2_annual');annual_frac=N('modis_burned_frac_annual');annual_flag=N('modis_zero_annual_den_flag')
            # Annual eligibility is a subset of the fixed union only for years
            # used to construct that union. Later observations retain the same
            # fixed support but require their own admitted annual LC source.
            if annual is not None and domain_name in DOMAINS and start<=year<=end and annual>domain+area_tol:
                err('annual eligible area exceeds the known fixed-union area')
            if annual is not None and annual+annual_unknown>grid_proxy+area_tol:
                err('annual eligibility exceeds the sampled grid area')
            if annual_unknown>0:
                if annual is not None or annual_frac is not None or annual_flag is not None:err('unknown annual eligibility must withhold annual fields')
            else:
                if annual is None:err('annual area missing despite resolved eligibility')
                elif annual_flag!=int(annual==0):err('incorrect zero-annual flag')
            if annual_unknown==0 and unresolved==0 and anomaly_count==0 and annual is not None and annual>0:eq(annual_frac,ba/annual,'union-over-annual ratio')
            if (annual is None or annual==0 or unresolved>0 or anomaly_count>0) and annual_frac is not None:err('annual ratio should be null')
        except (ValueError,TypeError,ZeroDivisionError,AttributeError) as e:err(str(e))
    return errors


# Public source authority. Proposed local bundle/policy IDs are deliberately
# separate from the upstream exported schema and method identity.
FIELDS = C3_FIELDS = REQUIRED
OPTIONAL_FIELDS = ('system:index', '.geo', 'ba_annual_lc_source_index')
SCHEMA = 'rp1_ba_c3_extended_v2'
METHOD = 'c3_methods_v1_schema_v2'
POLICY = 'c3_preserve_admission_v1'
DOMAIN_WINDOWS = DOMAINS
ZONES = {'CZ': 'coastal_zone', 'FZ': 'forest_zone', 'GS': 'guinea_savannah',
         'SS': 'sudan_savannah', 'TZ': 'transition_zone'}
LEVELS = ('acz', 'district')
SOURCE_META_FIELDS = ('family', 'source_path', 'source_sha256', 'source_row')
TECHNICAL_STATUSES = frozenset({'REDUCTION_INCOMPLETE', 'ACCOUNTING_INCONSISTENCY',
                              'EMPTY_REDUCTION_UNRESOLVED'})
PROFILE = {'source_label': 'c3', 'source_schema_version': SCHEMA,
           'quality_policy': POLICY, 'method_version': METHOD}
FILENAME = re.compile(r'^rp1_ba_(acz|district)_monthly_c3_(CZ|FZ|GS|SS|TZ)_(BA2001|BA2012)_([0-9]{4})_ext\.csv$')


class C3ValidationError(ValueError):
    """A c3 source/header/row does not satisfy the pinned input contract."""


def declared_observation_windows(windows: Mapping | None = None) -> dict:
    """Validate an explicit observation calendar independently of fixed masks."""
    selected = DOMAIN_WINDOWS if windows is None else windows
    if not isinstance(selected, Mapping) or not selected:
        raise C3ValidationError('Declare nonempty c3 observation windows')
    result = {}
    for domain, bounds in selected.items():
        if domain not in DOMAIN_WINDOWS or not isinstance(bounds, (tuple, list)) or len(bounds) != 2:
            raise C3ValidationError('Unknown c3 domain/window')
        lo, hi = bounds
        if type(lo) is not int or type(hi) is not int or not DOMAIN_WINDOWS[domain][0] <= lo <= hi <= 9999:
            raise C3ValidationError(f'Invalid export years for {domain}')
        result[domain] = (lo, hi)
    return result


def observation_windows(start_year: int, end_year: int) -> dict:
    """Build declared observation windows without changing fixed union years."""
    if type(start_year) is not int or type(end_year) is not int or not 2001 <= start_year <= end_year <= 9999:
        raise C3ValidationError('Invalid complete observation period')
    return declared_observation_windows({
        domain: (max(start_year, fixed[0]), end_year)
        for domain, fixed in DOMAIN_WINDOWS.items()
    })


def parse_filename(name: str, *, observation_windows: Mapping | None = None) -> dict:
    match = FILENAME.fullmatch(name)
    if match is None:
        raise C3ValidationError(f'Unrecognized annual c3 analytical filename: {name}')
    level, partition, domain, year_text = match.groups()
    year = int(year_text)
    selected = declared_observation_windows(observation_windows)
    if domain not in selected:
        raise C3ValidationError(f'{name}: domain outside declared observation coverage')
    lo, hi = selected[domain]
    if not lo <= year <= hi:
        raise C3ValidationError(f'{name}: export year outside declared {domain} observation coverage')
    return {'family': domain.lower(), 'domain': domain, 'level': level,
            'partition': partition, 'year': year, 'role': 'extended'}


def validate_header(header) -> None:
    header = list(header)
    if not header or len(header) != len(set(header)):
        raise C3ValidationError('Missing or duplicate CSV header')
    missing = set(FIELDS) - set(header)
    extra = set(header) - set(FIELDS) - set(OPTIONAL_FIELDS)
    if missing or extra:
        raise C3ValidationError(f'c3 header missing fields={sorted(missing)}; unexpected fields={sorted(extra)}')
    if [name for name in header if name in FIELDS] != list(FIELDS):
        raise C3ValidationError('c3 required fields are not in the documented order')


def scalar_text(value) -> str:
    """Accept CSV values and ordinary Python scalars without a pandas import."""
    if value is None:
        return ''
    if isinstance(value, (list, tuple, dict, set)):
        raise C3ValidationError('Malformed c3 scalar value')
    return str(value)


def validate_row(row: Mapping, *, identity: Mapping | None = None,
                 unit: Mapping | None = None, allow_technical: bool = False,
                 atol: float = 1e-8, rtol: float = 1e-10,
                 observation_windows: Mapping | None = None) -> None:
    """Validate source values without mutating them or manufacturing zeroes.

    ``identity`` is parse_filename()'s result; ``unit`` is one selected canonical
    geography row. Technical result records can be inspected with
    allow_technical=True, but cannot satisfy production admission.
    """
    missing = set(FIELDS) - set(row)
    if missing:
        raise C3ValidationError(f'Missing c3 fields: {sorted(missing)}')
    if not math.isfinite(atol) or not math.isfinite(rtol) or atol < 0 or rtol < 0:
        raise C3ValidationError('Invalid comparison tolerances')
    normalized = {name: scalar_text(row[name]) for name in FIELDS}
    if 'ba_annual_lc_source_index' in row:
        normalized['ba_annual_lc_source_index'] = scalar_text(row['ba_annual_lc_source_index'])
    key = tuple(normalized[name] for name in KEYS)
    errors = _validate_rows({key: normalized}, atol, rtol, allow_technical, observation_windows)
    if re.fullmatch(r'[A-Za-z0-9_-]+', normalized['ba_source_index']) is None or any(
            re.fullmatch(r'[A-Za-z0-9_-]+', index) is None for index in normalized['ba_lc_source_indexes'].split('|')):
        errors.append('Source index violates the upstream c3SafeIndex contract')
    if normalized['level'] == 'acz' and any(normalized[f] for f in
            ('parent_level', 'parent_id', 'parent_code', 'parent_name')):
        errors.append('ACZ parent attributes must all be blank')
    if identity is not None:
        for field, expected in (('level', identity['level']), ('ba_domain', identity['domain'])):
            if normalized[field] != str(expected):
                errors.append(f'Filename/content mismatch in {field}')
        if integer(normalized, 'year') != identity['year']:
            errors.append('Filename/content mismatch in year')
        partition = identity['partition']
        code_field = 'unit_code' if identity['level'] == 'acz' else 'parent_code'
        if normalized[code_field] != partition:
            errors.append(f'Filename/content mismatch in {code_field}')
        zone_id_field = 'unit_id' if identity['level'] == 'acz' else 'parent_id'
        if normalized[zone_id_field] != ZONES[partition]:
            errors.append(f'Noncanonical zone identity in {zone_id_field}')
    if unit is not None:
        for name in ('level', 'unit_id', 'unit_code', 'unit_name', 'parent_level',
                     'parent_id', 'parent_code', 'parent_name'):
            if normalized[name] != scalar_text(unit.get(name)):
                errors.append(f'Canonical geography mismatch in {name}')
    if errors:
        raise C3ValidationError('; '.join(errors))


def expected_identities(windows: Mapping, zones=tuple(ZONES), levels=LEVELS) -> set[tuple]:
    """Return declared annual source identities, never infer them from files."""
    result = set()
    for domain, bounds in declared_observation_windows(windows).items():
        lo, hi = bounds
        for zone in zones:
            if zone not in ZONES:
                raise C3ValidationError(f'Unknown zone: {zone}')
            for level in levels:
                if level not in LEVELS:
                    raise C3ValidationError(f'Unknown level: {level}')
                result.update((domain.lower(), level, zone, year) for year in range(lo, hi + 1))
    return result


