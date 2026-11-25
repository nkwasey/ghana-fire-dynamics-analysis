#!/usr/bin/env python3
"""Align input contracts to a selected, hashed merger handoff and geography.

Only input locations, observed spatial universe and structural support windows
are updated. Analytical eligible/model counts remain run-derived. Scientific
methods, exclusions, confidence policy and estimator settings are preserved.
"""
import argparse
import json
from pathlib import Path
import pandas as pd
import geopandas as gpd
import yaml
from rp1_analysis_v1.ba_support import (
    load_observation_support, profile_output_filenames, validate_c3_manifest,
    validate_observation_support, validate_profile_output_hashes,
)


def month(value):
    value = int(value)
    result = f"{value // 100:04d}-{value % 100:02d}"
    pd.Period(result, freq="M")
    return result


def declared_calendar(manifest, analysis):
    """Resolve expected dates from an explicit declaration, never observed extrema."""
    declared = manifest.get('study')
    if declared is None:
        return dict(analysis['study']['temporal_windows']['long_run']), None
    if not isinstance(declared, dict) or not {'start_yyyymm', 'end_yyyymm'} <= set(declared):
        raise ValueError('Merger study declaration is incomplete')
    for key in ('start_yyyymm', 'end_yyyymm', 'viirs_support_start_yyyymm',
                'ba2012_support_start_yyyymm', 'analysis_overlap_start_yyyymm'):
        if key in declared and type(declared[key]) is not int:
            raise ValueError('Declared study dates must be integer YYYYMM values: ' + key)
    start, end = month(declared['start_yyyymm']), month(declared['end_yyyymm'])
    if start > end or start[5:] != '01' or end[5:] != '12':
        raise ValueError('Declared scientific study requires complete calendar years')
    overlap = month(declared.get('analysis_overlap_start_yyyymm', 201202))
    return {'start': start, 'end': end}, overlap


def validate_declared_source_coverage(manifest, supports, research_window):
    """Require every source to cover its declared study obligation in full."""
    declared = manifest.get('study')
    if declared is None:
        return
    first, last = research_window['start'], research_window['end']
    required = {
        'modis_af': first,
        'ba2001': first,
        'viirs_af': max(first, '2012-01', month(declared.get('viirs_support_start_yyyymm', 201201))),
        'ba2012': max(first, '2012-01', month(declared.get('ba2012_support_start_yyyymm', 201201))),
    }
    missing = sorted(set(required) - set(supports))
    if missing:
        raise ValueError('Declared study is missing required source families: ' + ', '.join(missing))
    for source, required_start in required.items():
        if required_start > last:
            raise ValueError(source + ' support begins after the declared study end')
        actual_start, actual_end = supports[source]
        if actual_start > required_start or actual_end < last:
            raise ValueError(
                f'{source} support does not cover its declared study interval '
                f'{required_start}..{last}: {actual_start}..{actual_end}'
            )


def complete_paired_years(start, end):
    """Exclude partial endpoint years and reject an empty annual intersection."""
    first = int(start[:4]) + (start[5:] != '01')
    last = int(end[:4]) - (end[5:] != '12')
    if first > last:
        raise ValueError('Paired support contains no complete calendar year')
    return {'start': first, 'end': last}


def configure(root):
    root = Path(root).resolve()
    manifest = json.loads((root / 'data/raw/fire_panel_manifest.json').read_text())
    validate_c3_manifest(manifest)
    if manifest.get('ba_bundle', {}).get('scope') != 'full':
        raise ValueError('Pilot c3 bundles cannot configure full research inputs; use isolated pilot validation')
    validate_profile_output_hashes(root, manifest)
    files = profile_output_filenames(manifest)
    schema_path, analysis_path = root/'config/data_schema_contract.yml', root/'config/analysis_contract.yml'
    schema, analysis = yaml.safe_load(schema_path.read_text()), yaml.safe_load(analysis_path.read_text())
    research_window, declared_overlap = declared_calendar(manifest, analysis)
    panels = {}
    for role, panel_id in [('fire_panel_acz','acz_monthly'),('fire_panel_district','district_monthly')]:
        p = root / 'data/raw' / files[role]
        data = pd.read_csv(p)
        if data.empty or data[['unit_id','yyyymm']].isna().any().any() or data.duplicated(['unit_id','yyyymm']).any():
            raise ValueError('Generated panel has empty or duplicate keys')
        panels[panel_id] = data
        start, end = month(data.yyyymm.min()), month(data.yyyymm.max())
        if (start, end) != (str(research_window['start']), str(research_window['end'])):
            raise ValueError('Generated c3 panels do not cover the declared full research window')
        n_months = len(pd.period_range(start,end,freq='M'))
        units = int(data.unit_id.nunique())
        if len(data) != units * n_months:
            raise ValueError('Generated panel is not balanced')
        schema['panels'][panel_id].update(path='data/raw/'+files[role], expected_rows=len(data), expected_units=units, start=start,end=end)
        analysis['study']['populations'][panel_id].update(units=units,rows=len(data),start=start,end=end)
    if schema['panels']['acz_monthly']['start'] != schema['panels']['district_monthly']['start'] or schema['panels']['acz_monthly']['end'] != schema['panels']['district_monthly']['end']:
        raise ValueError('Generated panels have inconsistent study windows')
    start, end = schema['panels']['acz_monthly']['start'], schema['panels']['acz_monthly']['end']
    schema['categorical_domains']['year'] = list(range(int(start[:4]), int(end[:4]) + 1))
    for field in schema['fields']:
        if field['name'] == 'yyyymm':
            field.update(minimum=int(start.replace('-', '')), maximum=int(end.replace('-', '')))
        elif field['name'] == 'year':
            field.update(minimum=int(start[:4]), maximum=int(end[:4]))
    supports = {}
    for family in manifest.get('families', []):
        key = family['source_kind']; window = (month(family['support_start_yyyymm']),month(family['support_end_yyyymm']))
        if key in supports and supports[key] != window: raise ValueError('Source support windows disagree between levels')
        supports[key] = window
    validate_declared_source_coverage(manifest, supports, research_window)
    kinds = {'modis_af_full':'modis_af','viirs_active':'viirs_af','ba2001_full':'ba2001','ba2012_native':'ba2012'}
    for support_id, specification in schema['source_supports'].items():
        kind = specification.get('manifest_source_kind') or kinds.get(support_id)
        if kind in supports:
            specification.update(start=supports[kind][0],end=supports[kind][1])
        elif support_id == 'canonical_spine': specification.update(start=start,end=end)
    if 'viirs_af' not in supports or 'ba2012' not in supports: raise ValueError('Required paired support windows are absent')
    overlap_start=max(supports['viirs_af'][0],supports['ba2012'][0],start,
                      declared_overlap or analysis['study']['temporal_windows']['overlap_monthly']['start'])
    overlap_end=min(supports['viirs_af'][1],supports['ba2012'][1],end)
    if overlap_start > overlap_end: raise ValueError('Empty paired support intersection')
    schema['source_supports']['full_overlap_native'].update(start=max(supports['viirs_af'][0],supports['ba2012'][0]), end=min(supports['viirs_af'][1],supports['ba2012'][1]))
    if start[5:] != '01' or end[5:] != '12': raise ValueError('Annual analysis requires complete study years')
    if declared_overlap is None and (overlap_start, overlap_end) != tuple(str(analysis['study']['temporal_windows']['overlap_monthly'][key]) for key in ('start','end')):
        raise ValueError('Generated c3/AF support does not cover the declared paired research window')
    analysis['study']['temporal_windows']['long_run'] = {'start': start, 'end': end}
    analysis['study']['temporal_windows']['overlap_monthly'] = {'start': overlap_start, 'end': overlap_end}
    analysis['study']['temporal_windows']['overlap_complete_years'] = complete_paired_years(overlap_start, overlap_end)
    for name in ['long_run_district','paired_overlap','rq3_model']:
        analysis['study']['populations'][name].update(units=None,rows=None,start=start if name=='long_run_district' else overlap_start,end=end if name=='long_run_district' else overlap_end)
    for identity,spec in schema['geometries'].items():
        geom=gpd.read_file(root/spec['path']); epsg=geom.crs.to_epsg() if geom.crs else None
        if epsg is None: raise ValueError('Generated analysis geography needs a declared EPSG CRS')
        spec.update(expected_features=len(geom),crs_epsg=int(epsg))
    acz=panels['acz_monthly'][['unit_id','unit_code','unit_name']].drop_duplicates()
    schema['categorical_domains']['acz_code']=sorted(acz.unit_code.astype(str).unique().tolist())
    schema['categorical_domains']['acz_unit_id']=sorted(acz.unit_id.astype(str).unique().tolist())
    schema['categorical_domains']['acz_name']=sorted(acz.unit_name.astype(str).unique().tolist())
    schema['geometries']['acz']['unit_identities']= {str(r.unit_id):{'unit_code':str(r.unit_code),'unit_name':str(r.unit_name)} for r in acz.itertuples(index=False)}
    rq2=analysis['research_questions']['rq2']
    rq2['expected_series_count'] = len(acz)
    rq2['expected_n_per_series'] = int(end[:4])-int(start[:4])+1
    schema['auxiliary_inputs']['ba_observation_support'] = {'path':'data/raw/ba_observation_support.csv','format':'csv'}
    validate_observation_support(load_observation_support(root, manifest), manifest, panels['acz_monthly'], panels['district_monthly'])
    schema_path.write_text(yaml.safe_dump(schema,sort_keys=False));analysis_path.write_text(yaml.safe_dump(analysis,sort_keys=False))
    return {'structural_start':start,'structural_end':end,'paired_start':overlap_start,'paired_end':overlap_end,'analytical_counts':'run-derived'}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--subproject-root',required=True,type=Path);args=p.parse_args()
    print(json.dumps(configure(args.subproject_root),indent=2))
