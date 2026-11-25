"""Run-local Archive acquisition, validation and immutable FIRMS admission.

The producer owns scientific preparation. This module owns RP1 selection and
receipts; it never activates or replaces the shared raw input directories.
"""
from __future__ import annotations

from contextlib import contextmanager
import csv
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
import tomllib
from zipfile import ZipFile

ARCHIVE = Path('RP1_Project/rp1_firms_archive')
FIRMS = Path('RP1_Project/rp1_mv_firms_panels')
AUTHORITY = Path('data/raw/source_provenance/archive_sp_intake.json')
PROFILE = 'ghana_firms_archive_sp_v1'
ACCEPTANCE = 'rp1_archive_sp_validation_acceptance_v1'
SOURCES = {'modis':'MODIS_SP','viirs':'VIIRS_SNPP_SP'}
PREFIXES = {'modis':'Ghana_MODIS_SP_','viirs':'Ghana_VIIRS_SNPP_SP_'}
POLICY = 'pinned_archive_population_rp1_rejoin_v1'


def sha(path):
    value=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1048576),b''):value.update(block)
    return value.hexdigest()


def read(path):return json.loads(Path(path).read_text(encoding='utf-8'))


def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8',newline='\n') as stream:
        json.dump(value,stream,indent=2,sort_keys=True,allow_nan=False);stream.write('\n')


def relative_child(root,value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value:
        raise ValueError('Archive authority path must be safe and relative')
    rel=PurePosixPath(value)
    path=(Path(root)/value).resolve()
    if rel.is_absolute() or '..' in rel.parts or rel.as_posix()!=value or not path.is_relative_to(Path(root).resolve()):
        raise ValueError('Archive authority path escapes its root')
    cursor=Path(root)
    for part in rel.parts:
        cursor=cursor/part
        if cursor.is_symlink():raise ValueError('Linked Archive authorities are not accepted')
    return path


def identity(path,relative):
    path=Path(path)
    if path.is_symlink() or not path.is_file():raise ValueError('Missing or linked Archive authority')
    return {'path':relative,'sha256':sha(path),'size_bytes':path.stat().st_size}


@contextmanager
def stage_lock(state):
    path=Path(state)/'.archive_workflow.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    try:handle=path.open('x',encoding='ascii')
    except FileExistsError:raise ValueError('Another Archive workflow stage holds this run lock') from None
    try:
        with handle:handle.write(str(os.getpid()))
        yield
    finally:path.unlink(missing_ok=True)


def settings(root,cfg,override_manifest=None):
    value=cfg.get('firms_archive',{'mode':'bundled'})
    allowed={'mode','manifest','producer_config','geography_policy'}
    if not isinstance(value,dict) or set(value)-allowed:raise ValueError('Unknown firms_archive settings')
    value=dict(value)
    mode=value.get('mode','bundled')
    if mode not in ('bundled','existing','build'):raise ValueError('Archive mode must be bundled, existing or build')
    if override_manifest:
        if mode=='build':raise ValueError('--archive-manifest cannot override build mode')
        mode='existing';value['manifest']=override_manifest
    policy=value.get('geography_policy',POLICY)
    if policy!=POLICY:raise ValueError('Unknown Archive geography policy; use a separately qualified source profile')
    result={'mode':mode,'geography_policy':policy}
    if mode=='existing':
        name=value.get('manifest')
        if not isinstance(name,str) or not name.strip():raise ValueError('Existing Archive mode requires a manifest path')
        path=Path(name).expanduser()
        path=path if path.is_absolute() else Path(root)/path
        if path.suffix.lower()!='.json' or path.is_symlink() or not path.is_file():raise ValueError('Archive manifest does not exist or is linked')
        path=path.resolve()
        result['manifest']=str(path)
    elif mode=='build':
        path=relative_child(root,value.get('producer_config',(ARCHIVE/'configs/rp1.yaml').as_posix()))
        if not path.is_file():raise ValueError('Archive producer configuration is missing')
        result.update(producer_config=path.relative_to(root).as_posix(),producer_config_sha256=sha(path))
    return result


def resolved_settings(root,state,cfg,override_manifest=None):
    """A declared CLI producer override remains bound for later stages."""
    path=Path(state)/'archive_request.json'
    if path.is_file():
        previous=read(path)
        if previous.get('configuration_settings')!=cfg.get('firms_archive',{'mode':'bundled'}):
            raise ValueError('Archive configuration changed; use a fresh run-id')
        if previous.get('manifest_override') and not override_manifest:
            return settings(root,{'firms_archive':previous['settings']})
    return settings(root,cfg,override_manifest)


def intake_module(root):
    path=Path(root)/'tools/import_firms_archive_sp.py'
    spec=importlib.util.spec_from_file_location('_rp1_workflow_archive_intake',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def archive_api(root):
    source=(Path(root)/ARCHIVE/'src').resolve()
    sys.path.insert(0,str(source))
    try:
        module=importlib.import_module('ghana_fire_archive.api')
    except ModuleNotFoundError as exc:
        raise ValueError('Install the rp1_firms_archive dependencies and editable package in the active RP1 environment') from exc
    if not Path(module.__file__).resolve().is_relative_to(source):
        raise ValueError('Archive import belongs to a different checkout')
    return module


def producer_identity(root):
    project=Path(root)/ARCHIVE
    metadata=tomllib.loads((project/'pyproject.toml').read_text(encoding='utf-8'))
    return {'version':metadata['project']['version'],
            'source_sha256':{p.relative_to(project).as_posix():sha(p) for p in sorted((project/'src').rglob('*.py'))}}


def bind_request(root,state,cfg,run_id,opts):
    previous=read(Path(state)/'archive_request.json') if (Path(state)/'archive_request.json').is_file() else {}
    configured=cfg.get('firms_archive',{'mode':'bundled'})
    original=configured.get('manifest') if isinstance(configured,dict) else None
    original_path=Path(original).expanduser() if isinstance(original,str) and original else None
    if original_path is not None:original_path=(original_path if original_path.is_absolute() else Path(root)/original_path).resolve()
    manifest_override=(opts['mode']=='existing' and
                       (configured.get('mode','bundled')!='existing' or str(original_path)!=opts['manifest']))
    if previous.get('manifest_override') and previous.get('settings')==opts:manifest_override=True
    tracked=('tools/run_workflow.py','tools/firms_archive_workflow.py','tools/import_firms_archive_sp.py',
             'RP1_Project/rp1_mv_firms_panels/src/mv_firms_panels/core/archive_authority.py',
             'RP1_Project/rp1_mv_firms_panels/src/mv_firms_panels/core/input_profiles.py')
    workflow_code={name:sha(Path(root)/name) for name in tracked if (Path(root)/name).is_file()}
    value={'schema':'rp1-workflow-archive-request-v1','run_id':run_id,'study':cfg['study'],
           'settings':opts,'sources':SOURCES,'validator_identity':producer_identity(root),
           'configuration_settings':configured,'manifest_override':manifest_override,
           'workflow_code_sha256':workflow_code}
    path=Path(state)/'archive_request.json'
    if path.exists():
        if read(path)!=value:raise ValueError('Archive request changed; use a fresh workflow run-id')
    else:write_new(path,value)
    return path,value


def source_inventory(manifest):
    """Exact producer inputs required to replay the accepted validation receipt."""
    manifest=Path(manifest);root=manifest.parent;m=read(manifest)
    paths={manifest,root/'annual/annual-export.json',root/'annual-current.csv',root/'qa/qa-manifest.json'}
    for part in m['partitions']:
        paths.update((relative_child(root,part['path']),relative_child(root,part['shapefile_path'])))
    for item in m['geography'].values():paths.add(relative_child(root,item['path']))
    export=read(root/'annual/annual-export.json')
    for part in export['partitions']:
        paths.add(relative_child(root/'annual',part['annual_shapefile_zip']))
        sensor={'MODIS_SP':'MODIS','VIIRS_SNPP_SP':'VIIRS','VIIRS_NOAA20_SP':'NOAA20','VIIRS_NOAA21_SP':'NOAA21'}[part['source']]
        stem=Path(part['annual_shapefile_zip']).stem
        paths.update((root/'annual/metadata'/sensor/(stem+'_provenance.json'),root/'annual/metadata'/sensor/(stem+'_fields.json')))
    qa=read(root/'qa/qa-manifest.json')
    for part in qa['partitions']:paths.add(relative_child(root/'qa',part['qa_path']))
    result=[]
    for path in sorted(paths):
        item=identity(path,path.relative_to(root).as_posix())
        result.append(item)
    return result


def check_source_inventory(manifest,records):
    root=Path(manifest).parent
    if source_inventory(manifest)!=records:raise ValueError('Accepted Archive source inventory changed')
    for record in records:
        path=relative_child(root,record['path'])
        if identity(path,record['path'])!=record:raise ValueError('Accepted Archive source bytes changed')


def copy_evidence(source,destination,role,relative,entries):
    destination=Path(destination);target=destination/relative
    record=identity(source,relative)
    target.parent.mkdir(parents=True,exist_ok=True)
    shutil.copyfile(source,target)
    if identity(target,relative)!=record:raise ValueError('Archive validation evidence changed while copying')
    entries.append({'role':role,**record})
    return record


def acceptance_receipt(root,destination,manifest,study,validation):
    """Copy metadata authorities only; scientific data stays producer-owned."""
    if not isinstance(validation,dict) or validation.get('passed') is not True:
        raise ValueError('A passing Archive scientific validation report is required')
    manifest=Path(manifest);base=manifest.parent;m=read(manifest)
    annual=base/'annual';export=read(annual/'annual-export.json');qa=read(base/'qa/qa-manifest.json')
    intake=intake_module(root)
    required=intake._authority.required_intervals(study)
    index=lambda rows:{(p['source'],p['year']):p for p in rows}
    cov=index(m['source_coverage']);parts=index(m['partitions']);rows=index(export['partitions']);quality=index(qa['partitions'])
    if not set(required)<=set(cov):raise ValueError('Archive does not declare all required source/year coverage')
    destination=Path(destination)
    destination.mkdir()
    entries=[]
    research=copy_evidence(manifest,destination,'research_manifest','evidence/archive-manifest.json',entries)
    exported=copy_evidence(annual/'annual-export.json',destination,'annual_export','evidence/annual-export.json',entries)
    quality_manifest=copy_evidence(base/'qa/qa-manifest.json',destination,'qa_manifest','evidence/qa/qa-manifest.json',entries)
    annual_validation=validation.get('annual_exports',{})
    quality_validation=validation.get('quality_assurance',{})
    if (validation.get('manifest_sha256')!=research['sha256']
            or annual_validation.get('annual_manifest_sha256')!=exported['sha256']
            or quality_validation.get('qa_manifest_sha256')!=quality_manifest['sha256']
            or annual_validation.get('passed') is not True
            or quality_validation.get('passed') is not True
            or quality_validation.get('semantics_recomputed') is not True):
        raise ValueError('Archive validation identities or complete annual/QA checks differ')
    selected_artifacts=[]
    for key in required:
        if key not in rows or key not in parts or key not in quality:raise ValueError('Required Archive partition, export or QA is missing')
        row=rows[key];item=quality[key]
        path=relative_child(annual,row['annual_shapefile_zip'])
        if sha(path)!=row['sha256']:raise ValueError('Accepted annual ZIP changed')
        members={}
        with ZipFile(path) as z:
            if z.testzip():raise ValueError('Corrupt accepted annual ZIP')
            names=z.namelist()
            stem=Path(row['annual_shapefile_zip']).stem
            expected={stem+ext for ext in ('.shp','.shx','.dbf','.prj','.cpg')}
            if len(names)!=5 or set(names)!=expected:raise ValueError('Unexpected accepted annual ZIP members')
            for name in names:
                digest=hashlib.sha256();size=0
                with z.open(name) as stream:
                    for block in iter(lambda:stream.read(1048576),b''):digest.update(block);size+=len(block)
                members[name]={'sha256':digest.hexdigest(),'size_bytes':size}
        selected_artifacts.append({'source':key[0],'year':key[1],'zip_sha256':row['sha256'],'members':members})
        copy_evidence(relative_child(base/'qa',item['qa_path']),destination,'qa_sidecar','evidence/qa/'+Path(item['qa_path']).name,entries)
    for name,item in m['geography'].items():
        copy_evidence(relative_child(base,item['path']),destination,'producer_geography',
                      'evidence/geography/'+Path(item['path']).name,entries)
    ref=Path(root)/ARCHIVE/'data/reference/geography/geography-manifest.json'
    if ref.is_file():copy_evidence(ref,destination,'producer_geography_provenance','evidence/geography/geography-manifest.json',entries)
    result={'schema':ACCEPTANCE,'status':'PASS','study':study,'research_manifest':research,
            'annual_export':exported,'qa_manifest':quality_manifest,'source_evidence':entries,
            'selected_coverage':[cov[key] for key in required],'selected_artifacts':selected_artifacts,
            'validator_identity':producer_identity(root),
            'generation_code_identity':{'generated_utc':m.get('generated_utc'),
               'partition_identities':[{'source':p['source'],'year':p['year'],
                  'preparation_code_sha256':p.get('preparation_code_sha256')} for p in m['partitions']]},
            'validation':{'passed':True,'report':validation},
            'origin_archive_manifest':str(manifest.resolve()),'validated_utc':datetime.now(timezone.utc).isoformat()}
    intake._authority.validate_acceptance(destination,result,study=study)
    write_new(destination/'acceptance.json',result)
    return result


def verify_archive_step(root,state,cfg,run_id,override_manifest=None):
    opts=resolved_settings(root,state,cfg,override_manifest)
    request,_=bind_request(root,state,cfg,run_id,opts)
    receipt=read(Path(state)/'archive.json')
    if receipt.get('request_sha256')!=sha(request) or receipt.get('mode')!=opts['mode']:
        raise ValueError('Archive workflow receipt/request binding differs')
    intake=intake_module(root)
    if opts['mode']=='bundled':
        checked=verify_bundled_inputs(intake,Path(root)/FIRMS,cfg['study'])
        if checked['intake_sha256']!=receipt['intake_sha256']:raise ValueError('Bundled FIRMS input authority changed')
    else:
        source=Path(receipt['origin_archive_manifest'])
        expected=(Path(opts['manifest']) if opts['mode']=='existing' else
                  Path(root)/ARCHIVE/'out/runs'/run_id/'archive-manifest.json')
        if source.resolve()!=expected.resolve():
            raise ValueError('Archive source origin differs from the bound request')
        check_source_inventory(source,receipt['source_inventory'])
        accepted=relative_child(root,receipt['acceptance_path'])
        if sha(accepted)!=receipt['acceptance_sha256']:raise ValueError('Archive acceptance identity changed')
        intake._authority.validate_acceptance(accepted.parent,read(accepted),study=cfg['study'])
    return receipt


def verify_bundled_inputs(intake,bundle,study):
    """Validate a whole bound bundle or check whether it covers the declared study."""
    authority=read(Path(bundle)/AUTHORITY)
    if authority.get('schema')==intake.SCHEMA:
        return intake.verify_bundle(Path(bundle))
    return intake.verify_bundle(Path(bundle),study=study)


def prepare_archive_step(root,state,cfg,run_id,override_manifest=None,preview=False):
    root,state=Path(root).resolve(),Path(state).resolve()
    opts=resolved_settings(root,state,cfg,override_manifest)
    with stage_lock(state):
        request,_=bind_request(root,state,cfg,run_id,opts)
        if preview:
            result={'schema':'rp1-workflow-archive-plan-v1','settings':opts,'study':cfg['study'],
                    'request_sha256':sha(request),'network_performed':False,
                    'required_products':list(SOURCES.values()),'note':'Local preview; acquisition occurs only in explicit build mode archive stage.'}
            path=state/'archive_plan.json'
            if path.exists():
                if read(path)!=result:raise ValueError('Archive plan changed')
            else:write_new(path,result)
            return result
        if (state/'archive.json').exists():return verify_archive_step(root,state,cfg,run_id,override_manifest)
        intake=intake_module(root)
        if opts['mode']=='bundled':
            checked=verify_bundled_inputs(intake,root/FIRMS,cfg['study'])
            result={'schema':'rp1-workflow-archive-v1','mode':'bundled','request_sha256':sha(request),
                    'intake_sha256':checked['intake_sha256'],'result':checked,
                    'note':'Existing admitted inputs verified; no producer-generation identity is asserted.'}
        else:
            api=archive_api(root)
            if opts['mode']=='build':
                config=api.load_config(root/opts['producer_config'],
                    start=cfg['study']['start_yyyymm']//100, end=cfg['study']['end_yyyymm']//100)
                config['sources']=list(SOURCES.values())
                config['output']=str(root/ARCHIVE/'out/runs'/run_id)
                if Path(config['output']).exists() and not (state/'archive_build_request.json').is_file():
                    raise ValueError('Archive output exists without this build request')
                build_request={'config_path':opts['producer_config'],'config_sha256':opts['producer_config_sha256'],
                               'output':config['output'],'sources':config['sources'],'years':config['selected_years']}
                bp=state/'archive_build_request.json'
                if bp.exists() and read(bp)!=build_request:raise ValueError('Archive build request changed')
                if not bp.exists():write_new(bp,build_request)
                plan=api.download(config)
                api.prepare_and_export(config,plan)
                manifest=Path(config['output'])/'archive-manifest.json'
            else:manifest=Path(opts['manifest'])
            before=source_inventory(manifest)
            validation=api.validate_archive(manifest,verify_qa=True)
            check_source_inventory(manifest,before)
            destination=state/'archive_validation'
            if destination.exists():raise ValueError('Incomplete validation directory exists; preserve diagnostics and choose a fresh run-id')
            acceptance_receipt(root,destination,manifest,cfg['study'],validation)
            acceptance=destination/'acceptance.json'
            result={'schema':'rp1-workflow-archive-v1','mode':opts['mode'],'request_sha256':sha(request),
                    'origin_archive_manifest':str(manifest.resolve()),'source_inventory':before,
                    'acceptance_path':acceptance.relative_to(root).as_posix(),'acceptance_sha256':sha(acceptance)}
        write_new(state/'archive.json',result)
        return result


def geography_compatibility(root,cfg,acceptance):
    """Pin upstream population; RP1 still owns analytical spatial assignment."""
    root=Path(root);base=Path(acceptance).parent;receipt=read(acceptance)
    evidence=receipt['source_evidence']
    def document(name):
        matches=[r for r in evidence if Path(r['path']).name==name]
        if len(matches)!=1:raise ValueError('Required Archive geography evidence missing or ambiguous: '+name)
        return read(relative_child(base,matches[0]['path']))
    units=document('units.json');geo=document('geography-manifest.json');m=document('archive-manifest.json')
    hashes={Path(r['path']).name:r['sha256'] for r in m['geography'].values()}
    if any(geo.get('generated_files',{}).get(name)!=value for name,value in hashes.items()):
        raise ValueError('Archive geography does not match the pinned source-population profile')
    land=(root/cfg['land_mask']).resolve()
    members={r['path']:r['sha256'] for r in geo.get('source',{}).get('members',[])}
    for ext in ('.shp','.prj'):
        if sha(land.with_suffix(ext))!=members.get('data/raw/boundaries/gha_admin0'+ext):
            raise ValueError('Archive national source differs from RP1; qualify a new population before admission')
    with (root/FIRMS/'data/metadata/unit_universe.csv').open(encoding='utf-8-sig',newline='') as stream:
        rows=list(csv.DictReader(stream))
    current={r['unit_id']:r['parent_id'] for r in rows if r['level']=='district'}
    upstream={r['district_id']:r['zone_id'] for r in units['districts']}
    if not current or current!=upstream:raise ValueError('Archive and RP1 district IDs/parent-zone mapping differ')
    return {'policy':POLICY,'country_source_shp_and_prj_identical':True,'district_parent_mapping_equal':True,
            'districts':len(current),'producer_coordinate_precision':geo.get('coordinate_precision_decimal_places'),
            'reporting_geometries_claimed_identical':False,
            'assignment_authority':'RP1 current analytical polygons; upstream country filtering remains part of declared source population'}


def verify_admission(root,state,cfg,run_id,geo_receipt_sha256,override_manifest=None):
    root,state=Path(root),Path(state)
    upstream=verify_archive_step(root,state,cfg,run_id,override_manifest)
    receipt=read(state/'archive_admission.json')
    if (receipt.get('archive_receipt_sha256')!=sha(state/'archive.json')
            or receipt.get('geo_receipt_sha256')!=geo_receipt_sha256 or receipt.get('study')!=cfg['study']):
        raise ValueError('Archive admission workflow/geography/study binding differs')
    bundle=relative_child(root,receipt['bundle_root'])
    intake_tool=intake_module(root)
    checked=(verify_bundled_inputs(intake_tool,bundle,cfg['study']) if upstream['mode']=='bundled'
             else intake_tool.verify_bundle(bundle,study=cfg['study']))
    if checked['intake_sha256']!=receipt['intake_sha256']:raise ValueError('Admitted FIRMS input authority changed')
    if upstream['mode']!='bundled':
        expected=relative_child(root,upstream['acceptance_path'])
        intake=read(bundle/AUTHORITY)
        if intake['acceptance']['sha256']!=sha(expected):raise ValueError('Input bundle belongs to another accepted Archive')
        if geography_compatibility(root,cfg,expected)!=receipt['geography_compatibility']:
            raise ValueError('Archive/RP1 geography compatibility changed')
    return receipt


def admit_archive_step(root,state,cfg,run_id,geo_receipt_sha256,override_manifest=None):
    root,state=Path(root).resolve(),Path(state).resolve()
    opts=resolved_settings(root,state,cfg,override_manifest)
    if not (state/'archive.json').exists():
        if opts['mode']!='bundled':raise ValueError('Complete archive stage before archive-admit')
        prepare_archive_step(root,state,cfg,run_id,override_manifest)
    with stage_lock(state):
        upstream=verify_archive_step(root,state,cfg,run_id,override_manifest)
        if (state/'archive_admission.json').exists():return verify_admission(root,state,cfg,run_id,geo_receipt_sha256,override_manifest)
        intake=intake_module(root)
        if opts['mode']=='bundled':
            bundle=root/FIRMS
            checked=verify_bundled_inputs(intake,bundle,cfg['study']);compatibility=None
        else:
            acceptance=relative_child(root,upstream['acceptance_path'])
            compatibility=geography_compatibility(root,cfg,acceptance)
            bundle=root/FIRMS/'out/runs'/run_id/'source_inputs'
            if bundle.exists():checked=intake.verify_bundle(bundle,study=cfg['study'])
            else:checked=intake.stage_archive(Path(upstream['origin_archive_manifest']).parent/'annual',bundle,cfg['study'],acceptance)
            manifest=read(bundle/AUTHORITY)
            if manifest['acceptance']['sha256']!=sha(acceptance):raise ValueError('Existing run input bundle belongs to another acceptance')
        result={'schema':'rp1-workflow-archive-admission-v1','mode':opts['mode'],'study':cfg['study'],
                'archive_receipt_sha256':sha(state/'archive.json'),'geo_receipt_sha256':geo_receipt_sha256,
                'bundle_root':bundle.relative_to(root).as_posix(),
                'intake_sha256':checked['intake_sha256'],'result':checked,'geography_compatibility':compatibility}
        write_new(state/'archive_admission.json',result)
        return result


def configure_firms_inputs(config,root,admission):
    bundle=relative_child(root,admission['bundle_root'])
    firms=(Path(root)/FIRMS).resolve()
    if not bundle.is_relative_to(firms):raise ValueError('Admitted input bundle must be inside the FIRMS project')
    prefix=bundle.relative_to(firms).as_posix()
    for sensor in SOURCES:
        point=config['io']['inputs']['firms_points'][sensor]
        point['input_profile']=PROFILE
        point['admission_manifest']=AUTHORITY.as_posix()
        point['admission_bundle_root']=None if prefix=='.' else prefix
        point['file_glob']=('/'.join([prefix,'data/raw',sensor,PREFIXES[sensor]+'*.shp']) if prefix!='.'
                            else f'data/raw/{sensor}/{PREFIXES[sensor]}*.shp')
    return config
