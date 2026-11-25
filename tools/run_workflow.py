#!/usr/bin/env python3
"""Run explicit local workflow steps from source inputs and verified handoffs."""
from __future__ import annotations
import argparse
from contextlib import contextmanager
import csv
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
FIRMS = ROOT / 'RP1_Project/rp1_mv_firms_panels'
ANALYSIS = ROOT / 'RP1_Project/rp1_analysis'
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tools'))
import stage_geo_handoff as geo_handoff
from study_settings import analysis_run_id, validate_study


@contextmanager
def checkout_source_scope():
    """Pin CLI execution to this checkout without mutating import-only callers."""
    original = sys.path[:]
    try:
        for component in ('geo_data_prep', 'RP1_Project/rp1_mv_firms_panels',
                          'RP1_Project/rp1_analysis', 'RP1_Project/rp1_firms_archive'):
            sys.path.insert(0, str(ROOT / component / 'src'))
        yield
    finally:
        sys.path[:] = original


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def inside(value: str) -> Path:
    p = (ROOT / value).resolve()
    if not p.is_relative_to(ROOT) or p == ROOT:
        raise ValueError('Workflow paths must be inside the project')
    return p


def run(command, cwd=ROOT):
    print('Executing:', ' '.join(map(str, command)), flush=True)
    env=os.environ.copy()
    sources=[str(ROOT/part/'src') for part in ('geo_data_prep','RP1_Project/rp1_mv_firms_panels',
             'RP1_Project/rp1_analysis','RP1_Project/rp1_firms_archive')]
    env['PYTHONPATH']=os.pathsep.join([str(ROOT),*sources]+([env['PYTHONPATH']] if env.get('PYTHONPATH') else []))
    subprocess.run(list(map(str, command)), cwd=cwd, check=True,env=env)


def dump(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n',encoding='utf-8')


def verified_geo(state):
    receipt = json.loads((state / 'geo.json').read_text())
    if sha(ROOT / 'RP1_Project/geo_handoff_manifest.json') != receipt['project_manifest_sha256']:
        raise ValueError('Geography handoff changed since this workflow run')
    manifest = json.loads((ROOT / 'RP1_Project/geo_handoff_manifest.json').read_text())
    for name, record in manifest['files'].items():
        p = inside(name)
        if not p.is_file() or sha(p) != record['sha256']:
            raise ValueError('Staged geography changed: ' + name)
    if receipt.get('reused_existing_handoff'):
        verify_reused_geo_sources(receipt)
    return receipt


def verify_reused_geo_sources(receipt):
    """Verify original generation evidence; never retag it as a new geo run."""
    import yaml
    config_path=inside(receipt['geo_config_path'])
    if sha(config_path)!=receipt['geo_config_sha256']:raise ValueError('Reused geography configuration changed')
    config=yaml.safe_load(config_path.read_text(encoding='utf-8'))
    project=(config_path.parent/config.get('project_root','..')).resolve()
    source=inside(receipt['source_run'])
    fingerprint=json.loads((source/'inputs_fingerprint.json').read_text(encoding='utf-8'))
    if fingerprint.get('config_sha256')!=receipt['geo_config_sha256']:
        raise ValueError('Selected geography configuration differs from original source run')
    original=json.loads((ROOT/'RP1_Project/geo_handoff_manifest.json').read_text(encoding='utf-8'))
    if (sha(source/'outputs_manifest.json')!=original['source_output_manifest_sha256']
            or sha(source/'contract/stage1_contract_manifest.json')!=original['source_contract_sha256']):
        raise ValueError('Reused geography generation authorities changed')
    outputs=json.loads((source/'outputs_manifest.json').read_text(encoding='utf-8'))
    authority=outputs.get('files',{}).get('inputs_fingerprint.json',{})
    if authority.get('sha256')!=sha(source/'inputs_fingerprint.json'):
        raise ValueError('Reused geography input fingerprint differs from original output manifest')
    for role in ('districts','zones','national'):
        base=(project/config['inputs'][role]['path']).parent
        parts=fingerprint.get(role,{}).get('parts',{})
        if not isinstance(parts,dict) or not parts:
            raise ValueError('Reused geography source fingerprint is incomplete: '+role)
        for name,expected in parts.items():
            path=(base/name).resolve()
            if not path.is_relative_to(ROOT) or not path.is_file() or sha(path)!=expected:
                raise ValueError('Reused geography source bytes changed: '+role)


def reuse_geo_handoff(state,cfg):
    """Explicit read-only adoption of the current, unchanged structural handoff."""
    if (state/'geo.json').exists():
        receipt=verified_geo(state)
        if not receipt.get('reused_existing_handoff'):raise ValueError('This run already owns another geography step')
        return receipt
    import yaml
    config_path=inside(cfg['geo_config'])
    config=yaml.safe_load(config_path.read_text(encoding='utf-8'))
    project=(config_path.parent/config.get('project_root','..')).resolve()
    original=json.loads((ROOT/'RP1_Project/geo_handoff_manifest.json').read_text(encoding='utf-8'))
    if original.get('schema')!='rp1-geo-handoff-v2':raise ValueError('No verified reusable geography handoff')
    origin=original['source_run']['run_id']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}',origin):raise ValueError('Invalid original geography run identity')
    out=Path(config['outputs']['root'])
    source=(out if out.is_absolute() else project/out)/origin
    receipt={'schema':'rp1-workflow-geography-reuse-v1','reused_existing_handoff':True,
             'source_run':source.resolve().relative_to(ROOT).as_posix(),
             'project_manifest_sha256':sha(ROOT/'RP1_Project/geo_handoff_manifest.json'),
             'geo_config_path':config_path.relative_to(ROOT).as_posix(),'geo_config_sha256':sha(config_path),
             'original_generation':original['source_run'],
             'note':'Existing structural geography verified unchanged; no geometry computation or new generation identity asserted.'}
    verify_reused_geo_sources(receipt)
    for name,item in original['files'].items():
        if sha(inside(name))!=item['sha256']:raise ValueError('Reused staged geography differs')
    dump(state/'geo.json',receipt)
    return verified_geo(state)


def gee_upload_bundle(source, state, config_path, run_id):
    import stage_gee_handoff as gee_handoff
    destination = state / 'gee_upload'
    result = gee_handoff.verify(destination) if destination.exists() else gee_handoff.build(source, destination, config_path)
    if result['run_id'] != run_id:
        raise ValueError('GEE upload bundle belongs to a different geography run')
    return destination, result


def verify_ba_handoff(state,profile,study):
    """Bind the c3 preparation receipt to this request and selected geography."""
    if profile!='c3': raise ValueError('Only c3 burned-area inputs are supported')
    from RP1_Project.rp1_ba_consolidator.handoff import verify_handoff
    receipt=json.loads((state/'ba_c3.json').read_text(encoding='utf-8'))
    request=state/'ba_c3_request.json'
    configured=json.loads(request.read_text(encoding='utf-8'))
    if (receipt.get('schema')!='rp1-workflow-ba-v2' or receipt.get('profile')!='c3'
        or configured.get('schema')!='rp1-ba-c3-preparation-request-v1'
        or receipt.get('request_sha256')!=sha(request)
        or receipt.get('geo_receipt_sha256')!=sha(state/'geo.json')
        or configured.get('output_dir')!=receipt.get('output_dir')):
        raise ValueError('c3 preparation request/geography/output binding differs')
    result=verify_handoff(Path(receipt['output_dir']),unit_universe=FIRMS/'data/metadata/unit_universe.csv',
        profile_id='c3',study=study,workflow_request_sha256=sha(request))
    for field in ('manifest_sha256','handoff_sha256'):
        if result[field]!=receipt.get(field):raise ValueError('c3 handoff identity changed: '+field)
    return result


def prepare_ba(state,cfg,args):
    """Prepare or verify an immutable c3 annual delivery for this workflow."""
    from rp1_ba_contracts import c3
    from RP1_Project.rp1_ba_consolidator.core import ConsolidationOptions,consolidate
    from RP1_Project.rp1_ba_consolidator.handoff import admit_bundle,verify_handoff
    if args.step!='consolidate-ba' or args.profile!='c3':
        raise ValueError('Use consolidate-ba --profile c3 for annual c3 exports')
    verified_geo(state)
    profiles=json.loads(inside(cfg['merge_config']).read_text(encoding='utf-8'))['profiles']
    if set(profiles)!={'c3'} or any(profiles['c3'].get(k)!=v for k,v in c3.PROFILE.items()):
        raise ValueError('The workflow requires the implemented c3 profile')
    preparation=cfg.get('ba_preparation',{})
    if not isinstance(preparation,dict) or set(preparation)-{'c3'} or 'ba_consolidation' in cfg:
        raise ValueError('Use one c3 ba_preparation block')
    settings=preparation.get('c3',{})
    if not isinstance(settings,dict) or set(settings)-{'input_dir','boundary_label','output_root','scope'}:
        raise ValueError('Unknown c3 preparation settings')
    source_value=args.ba_input_dir or settings.get('input_dir')
    label=args.boundary_label if args.boundary_label is not None else settings.get('boundary_label')
    if not isinstance(source_value,str) or not source_value.strip() or not isinstance(label,str) or not label.strip() or label=='unspecified':
        raise ValueError('Provide annual c3 --ba-input-dir and documented --boundary-label')
    source=Path(source_value).expanduser();source=(source if source.is_absolute() else ROOT/source).resolve()
    output=state/'ba'/'c3'
    root_value=args.ba_output_root or settings.get('output_root')
    if root_value:
        output_root=Path(root_value).expanduser()
        if args.ba_output_root and not output_root.is_absolute():raise ValueError('--ba-output-root must be absolute')
        output=(output_root if output_root.is_absolute() else ROOT/output_root).resolve()/args.run_id/'c3'
    if output.is_symlink():raise ValueError('Symbolic-link c3 destination is not accepted')
    scope=settings.get('scope','auto')
    request={'schema':'rp1-ba-c3-preparation-request-v1','input_dir':str(source),'output_dir':str(output.resolve()),
        'boundary_label':label,'profile':'c3','profile_contract':dict(c3.PROFILE),'study':cfg['study'],
        'scope':scope,'geo_receipt_sha256':sha(state/'geo.json')}
    request_path=state/'ba_c3_request.json';receipt_path=state/'ba_c3.json'
    if not request_path.exists() and (state/'merge_c3.json').exists():
        raise ValueError('Merge already started; use a new run-id for changed c3 inputs')
    if request_path.exists():
        previous=json.loads(request_path.read_text(encoding='utf-8'))
        if previous!=request:
            changed={k for k in set(previous)|set(request) if previous.get(k)!=request.get(k)}
            old=Path(previous['output_dir'])
            if changed=={'output_dir'} and args.ba_output_root and not receipt_path.exists() and not old.exists() and not old.is_symlink() and not output.exists():
                dump(request_path,request)
            else:raise ValueError('c3 preparation request changed; use a fresh run-id')
    else:
        if output.exists() or output.is_symlink():raise ValueError('c3 output already exists without its workflow request')
        if not source.is_dir():raise ValueError('c3 download directory does not exist: '+str(source))
        dump(request_path,request)
    if receipt_path.exists():
        verify_ba_handoff(state,'c3',cfg['study'])
        print('Workflow step already completed and verified: consolidate-ba');return
    unit_csv=FIRMS/'data/metadata/unit_universe.csv'
    if not output.exists():
        def admit(staged,report):
            verified_geo(state)
            admit_bundle(staged,report,unit_universe=unit_csv,profile_id='c3',study=cfg['study'],workflow_request_sha256=sha(request_path))
        consolidate(ConsolidationOptions(input_dir=source,output_dir=output,boundary_label=label,
            unit_universe=unit_csv,start_year=cfg['study']['start_yyyymm']//100,end_year=cfg['study']['end_yyyymm']//100,
            observation_windows=c3.observation_windows(
                cfg['study']['start_yyyymm']//100, cfg['study']['end_yyyymm']//100),
            scope=scope),pre_publish=admit)
    result=verify_handoff(output,unit_universe=unit_csv,profile_id='c3',study=cfg['study'],workflow_request_sha256=sha(request_path))
    verified_geo(state)
    dump(receipt_path,{'schema':'rp1-workflow-ba-v2','profile':'c3','output_dir':str(output.resolve()),
        'request_sha256':sha(request_path),'geo_receipt_sha256':sha(state/'geo.json'),
        'manifest_sha256':result['manifest_sha256'],'handoff_sha256':result['handoff_sha256']})
    print('Admitted c3 annual bundle:',output)


def verify_interrupted_handoff(merged, raw):
    """Verify an untouched staged handoff against the selected merger output."""
    original = (merged / 'fire_panel_manifest.json').read_bytes()
    if (raw / 'original_merger_manifest.json').read_bytes() != original:
        raise ValueError('Cannot resume: staged original merger manifest differs from selected output')
    manifest = json.loads(original)
    expected = json.loads(original)
    for name, record in expected['outputs'].items():
        filename = Path(str(record['staged_path']).replace('\\', '/')).name
        if not filename or filename in ('.', '..'):
            raise ValueError('Cannot resume: invalid merger output filename')
        if name != 'manifest':
            expected_hash = record.get('sha256')
            if not expected_hash or sha(raw / filename) != expected_hash or sha(merged / filename) != expected_hash:
                raise ValueError('Cannot resume: merger or staged output hash differs: ' + name)
        record['staged_path'] = 'RP1_Project/rp1_analysis/data/raw/' + filename
    expected['analysis_handoff'] = {
        'original_manifest_file': 'original_merger_manifest.json',
        'original_manifest_sha256': hashlib.sha256(original).hexdigest(),
        'note': 'Output paths describe the Stage 5 analysis input location; source provenance and output hashes are unchanged.',
    }
    actual = json.loads((raw / 'fire_panel_manifest.json').read_text(encoding='utf-8'))
    if actual != expected:
        # A previous attempt may have normalized the manifest before a later step
        # failed. Accept only the exact deterministic normalization of our bundle.
        spec = importlib.util.spec_from_file_location('rp1_resume_provenance', ANALYSIS / 'scripts/regenerate_data_provenance.py')
        try:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            normalized = module.normalise_panel_manifest(expected, repo_root=ROOT)
        except (OSError, ValueError, KeyError, ImportError):
            normalized = None
        if actual != normalized:
            raise ValueError('Cannot resume: staged handoff manifest differs from the original staged bundle')


def configured_analysis_inputs():
    from rp1_analysis_v1.config import load_configuration_bundle
    schema = load_configuration_bundle(ANALYSIS / 'config').data_schema
    required = {str(panel.path) for panel in schema.panels.values()}
    required.update(str(item['path']) for item in schema.auxiliary_inputs.values())
    for geometry in schema.geometries.values():
        required.update(geometry.required_members)
    return required


def verify_completed_handoff(state, merged, profile):
    receipt = json.loads((state / 'analysis_inputs.json').read_text())
    inventory_path = ANALYSIS / 'data/input_sha256.json'
    if (receipt.get('profile') != profile
            or receipt.get('merger_manifest_sha256') != sha(merged / 'fire_panel_manifest.json')
            or receipt.get('input_inventory_sha256') != sha(inventory_path)):
        raise ValueError('Completed analysis handoff identity differs; investigate the existing receipt and inputs')
    contract_hash = receipt.get('input_contract_sha256')
    if contract_hash is not None and contract_hash != sha(ANALYSIS / 'config/data_schema_contract.yml'):
        raise ValueError('Completed analysis input contract changed; investigate before reusing the handoff')
    verify_interrupted_handoff(merged, ANALYSIS / 'data/raw')
    records = json.loads(inventory_path.read_text())['files']
    members = [record['staged_path'] for record in records]
    if len(members) != len(set(members)) or set(members) != configured_analysis_inputs():
        raise ValueError('Completed handoff inventory differs from the configured input contract')
    for record in records:
        relative = Path(record['staged_path'])
        target = (ANALYSIS / relative).resolve()
        if (relative.is_absolute() or '..' in relative.parts
                or not target.is_relative_to(ANALYSIS.resolve())
                or target.stat().st_size != record['size_bytes']
                or sha(target) != record['sha256']):
            raise ValueError('Completed analysis handoff input changed: ' + str(relative))


def main():
    with checkout_source_scope():
        return _main()


def _main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', default='configs/workflow.json')
    p.add_argument('--run-id', required=True)
    p.add_argument('step', choices=['geo','geo-reuse','gee-inputs','archive-plan','archive','archive-admit','consolidate-ba','firms','merge','analysis-inputs'])
    p.add_argument('--archive-manifest',help='For archive stages only: explicitly reuse an accepted producer manifest; never replaces shared raw data')
    p.add_argument('--profile', default='c3', choices=['c3'], help='The sole operational burned-area source profile')
    p.add_argument('--retry-merge', action='store_true', help='Retry a failed merge using an unchanged runtime configuration and an absent output directory')
    p.add_argument('--resume-analysis-inputs', action='store_true', help='Resume an interrupted analysis handoff after verifying its staged bundle')
    p.add_argument('--merge-output-root', help='Absolute directory for merge outputs; run ID and profile are appended. The location is recorded for later workflow steps.')
    p.add_argument('--ba-input-dir', help='Downloaded annual c3 extended CSV directory, absolute or relative to the repository root')
    p.add_argument('--boundary-label', help='Documented boundary/export release label for BA preparation')
    p.add_argument('--ba-output-root', help='Absolute BA preparation output root; run ID and profile are appended')
    p.add_argument('--geo-backup', help='For geo only: explicitly replace existing geography handoff files after preserving them in this fresh absolute backup directory')
    a = p.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', a.run_id):
        p.error('run-id must be portable letters, digits, underscore and hyphen')
    if a.retry_merge and a.step != 'merge':
        p.error('--retry-merge is only valid for merge')
    if a.resume_analysis_inputs and a.step != 'analysis-inputs':
        p.error('--resume-analysis-inputs is only valid for analysis-inputs')
    if a.merge_output_root and a.step != 'merge':
        p.error('--merge-output-root is only valid for merge')
    if a.geo_backup and (a.step != 'geo' or not Path(a.geo_backup).is_absolute()):
        p.error('--geo-backup requires the geo step and a fresh absolute backup directory')
    if a.archive_manifest and a.step not in ('archive-plan','archive','archive-admit'):
        p.error('--archive-manifest applies only to Archive stages')
    if any(value is not None for value in (a.ba_input_dir, a.boundary_label, a.ba_output_root)) and a.step not in ('consolidate-ba',):
        p.error('Burned-area preparation flags are only valid for consolidate-ba')
    cfg_path = inside(a.config)
    cfg = json.loads(cfg_path.read_text())
    if cfg.get('schema') != 'rp1-local-workflow-v1':
        p.error('Unknown workflow schema')
    study = validate_study(cfg['study'])
    cfg['study'] = study
    state = inside(cfg['output_root']) / a.run_id
    state.mkdir(parents=True, exist_ok=True)
    snapshot = state / 'workflow.json'
    if snapshot.exists() and json.loads(snapshot.read_text()) != cfg:
        raise ValueError('This run-id is bound to a different workflow configuration')
    if not snapshot.exists(): dump(snapshot, cfg)
    if a.step in ('consolidate-ba','merge','analysis-inputs') and not a.profile:
        p.error('--profile is required for this step')
    if a.profile and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', a.profile):
        p.error('Invalid profile')
    if a.step == 'geo-reuse':
        reuse_geo_handoff(state,cfg)
    elif a.step in ('archive-plan','archive','archive-admit'):
        import firms_archive_workflow as archive_workflow
        if a.step=='archive-admit':
            verified_geo(state)
            result=archive_workflow.admit_archive_step(ROOT,state,cfg,a.run_id,sha(state/'geo.json'),a.archive_manifest)
            verified_geo(state)
        else:
            result=archive_workflow.prepare_archive_step(ROOT,state,cfg,a.run_id,a.archive_manifest,preview=a.step=='archive-plan')
        print(json.dumps(result,indent=2))
    elif a.step == 'geo':
        if (state / 'geo.json').exists():
            raise ValueError('Geography step already completed; use a fresh run-id')
        run([sys.executable, '-c', 'import sys; from geo_data_prep.cli import main; sys.exit(main())', 'run', '--config', inside(cfg['geo_config']), '--run-id', a.run_id])
        import yaml
        gcfg = yaml.safe_load(inside(cfg['geo_config']).read_text())
        # Configuration project_root is relative to the configuration directory.
        groot = (inside(cfg['geo_config']).parent / gcfg.get('project_root', '..')).resolve()
        goutput = Path(gcfg['outputs']['root'])
        source = (goutput if goutput.is_absolute() else groot / goutput) / a.run_id
        bundle = state / 'geo_handoff'
        geo_handoff.build(source, bundle)
        gee_destination, _ = gee_upload_bundle(source, state, inside(cfg['geo_config']), a.run_id)
        if a.geo_backup:
            application = geo_handoff.apply(bundle, ROOT, replace=True, backup_arg=a.geo_backup)
        else:
            application = geo_handoff.apply(bundle, ROOT)
        geo_receipt = {'source_run': source.relative_to(ROOT).as_posix(), 'project_manifest_sha256': sha(ROOT / 'RP1_Project/geo_handoff_manifest.json'), 'gee_upload': gee_destination.relative_to(ROOT).as_posix()}
        if a.geo_backup:
            saved = Path(application['backup']).resolve()
            geo_receipt['previous_handoff_backup'] = {'path': str(saved), 'manifest_sha256': sha(saved / 'backup_manifest.json')}
        dump(state / 'geo.json', geo_receipt)
    elif a.step == 'gee-inputs':
        receipt = verified_geo(state)
        if receipt.get('reused_existing_handoff'):
            raise ValueError('Reused geography retains its original approved asset/generation identity; create a fresh geo run to package new GEE uploads')
        destination, _ = gee_upload_bundle(inside(receipt['source_run']), state, inside(cfg['geo_config']), a.run_id)
        print('GEE upload bundle:', destination)
    elif a.step in ('consolidate-ba',):
        prepare_ba(state, cfg, a)
    elif a.step == 'firms':
        geography = verified_geo(state)
        if (state / 'firms.json').exists(): raise ValueError('FIRMS step already completed')
        import yaml
        fc = yaml.safe_load(inside(cfg['firms_config']).read_text())
        archive_admission=None
        if 'firms_archive' in cfg:
            import firms_archive_workflow as archive_workflow
            options=archive_workflow.resolved_settings(ROOT,state,cfg)
            if options['mode']=='bundled':
                archive_admission=archive_workflow.admit_archive_step(ROOT,state,cfg,a.run_id,sha(state/'geo.json'))
            elif not (state/'archive_admission.json').is_file():
                raise ValueError('Complete verified archive and archive-admit before firms')
            else:
                archive_admission=archive_workflow.verify_admission(ROOT,state,cfg,a.run_id,sha(state/'geo.json'))
            archive_workflow.configure_firms_inputs(fc,ROOT,archive_admission)
        if geography.get('gee_upload'):
            import stage_gee_handoff as gee_handoff
            gee_destination = inside(geography['gee_upload'])
            upload = gee_handoff.verify(gee_destination)
            if upload['run_id'] != a.run_id:
                raise ValueError('Projected national AOI belongs to a different geography run')
            geo_config_path = inside(cfg['geo_config'])
            geo_config = yaml.safe_load(geo_config_path.read_text())
            geo_root = (geo_config_path.parent / geo_config.get('project_root', '..')).resolve()
            national_source = (geo_root / geo_config['inputs']['national']['path']).resolve()
            if inside(cfg['land_mask']) != national_source:
                raise ValueError('Configured FIRMS land mask differs from the national AOI packaged for this geography run')
            fc['io']['inputs']['land_mask'] = str(gee_destination / upload['national_relative_path'])
        else:
            fc['io']['inputs']['land_mask'] = str(inside(cfg['land_mask']))
        fc['processing']['time_range'].update(start_yyyymm=study['start_yyyymm'], end_yyyymm=study['end_yyyymm'])
        fc['study'] = {key: study[key] for key in ('start_yyyymm', 'end_yyyymm', 'viirs_support_start_yyyymm')}
        for sensor, start in [('modis', study['start_yyyymm']), ('viirs', max(study['start_yyyymm'],study['viirs_support_start_yyyymm']))]:
            fc['processing']['sensor_time_ranges'][sensor].update(start_yyyymm=start, end_yyyymm=study['end_yyyymm'])
            fc['processing']['sensor_coverage'][sensor].update(start_yyyymm=start, end_yyyymm=study['end_yyyymm'])
            fc['outputs']['rp1_exports']['sensors'][sensor]['window'].update(start_yyyymm=start, end_yyyymm=study['end_yyyymm'])
        generated = FIRMS / 'configs/generated' / (a.run_id + '.yaml')
        if generated.exists(): raise ValueError('Generated FIRMS config already exists')
        generated.parent.mkdir(parents=True, exist_ok=True)
        generated.write_text(yaml.safe_dump(fc, sort_keys=False))
        run([sys.executable, '-m', 'mv_firms_panels.cli.main', '--config', generated, '--repo-root', FIRMS, '--run-id', a.run_id, 'pipeline', '--years-modis', str(study['start_yyyymm']//100)+'-'+str(study['end_yyyymm']//100), '--years-viirs', str(max(study['start_yyyymm'],study['viirs_support_start_yyyymm'])//100)+'-'+str(study['end_yyyymm']//100)], cwd=FIRMS)
        out = FIRMS / fc['outputs']['base_dir'] / a.run_id
        firms_receipt={'af_root': (out / 'rp1_af_exports').relative_to(ROOT).as_posix(), 'config_path': generated.relative_to(ROOT).as_posix(), 'config_sha256': sha(generated), 'geo_receipt_sha256': sha(state / 'geo.json')}
        if archive_admission:firms_receipt['archive_admission_sha256']=sha(state/'archive_admission.json')
        dump(state/'firms.json',firms_receipt)
    elif a.step == 'merge':
        verified_geo(state)
        af = json.loads((state / 'firms.json').read_text())
        if af['geo_receipt_sha256'] != sha(state / 'geo.json'): raise ValueError('FIRMS geography binding differs')
        if sha(inside(af['config_path'])) != af['config_sha256']: raise ValueError('FIRMS configuration changed after execution')
        if 'firms_archive' in cfg:
            import firms_archive_workflow as archive_workflow
            archive_workflow.verify_admission(ROOT,state,cfg,a.run_id,sha(state/'geo.json'))
            if af.get('archive_admission_sha256')!=sha(state/'archive_admission.json'):
                raise ValueError('FIRMS Archive admission changed before merge')
        mcfg = json.loads(inside(cfg['merge_config']).read_text())
        if a.profile not in mcfg['profiles']: raise ValueError('Unknown merge profile')
        if not (state/'ba_c3.json').is_file():
            raise ValueError('Complete verified c3 consolidate-ba before merge')
        burned_area=verify_ba_handoff(state,'c3',study)
        if any(mcfg['profiles']['c3'].get(k)!=v for k,v in burned_area['profile_contract'].items()):
            raise ValueError('Configured c3 profile differs from admission')
        mcfg['profiles']['c3'].update({key:burned_area[key] for key in
            ('ba2001_root','ba2012_root','source_lock','bundle_manifest','bundle_handoff')})
        unit_csv = FIRMS / 'data/metadata/unit_universe.csv'
        with unit_csv.open(newline='') as f: units = list(csv.DictReader(f))
        counts = {lev: sum(r['level'] == lev for r in units) for lev in ('acz', 'district')}
        mcfg['study'] = {**study, 'expected_units': counts}
        runtime_config = state / ('merge_' + a.profile + '.json')
        location_file = state / ('merge_' + a.profile + '_location.json')
        default_output = state / 'merge' / a.profile
        recorded_output = Path(json.loads(location_file.read_text())['output_dir']) if location_file.exists() else None
        if a.merge_output_root:
            external_root = Path(a.merge_output_root).expanduser()
            if not external_root.is_absolute():
                raise ValueError('--merge-output-root must be an absolute path')
            merge_output = external_root.resolve() / a.run_id / a.profile
            if recorded_output is not None and merge_output != recorded_output:
                if not a.retry_merge:
                    raise ValueError('Merge output location is already bound to a different directory')
                if recorded_output.exists() or recorded_output.is_symlink():
                    raise ValueError('Cannot relocate retry: recorded merge output directory already exists')
            if recorded_output is None and default_output != merge_output and (default_output.exists() or default_output.is_symlink()):
                raise ValueError('Merge output directory already exists at the default location')
        else:
            merge_output = recorded_output or default_output
        if a.retry_merge:
            if not runtime_config.is_file(): raise ValueError('Retry requires an existing merge runtime configuration')
            if json.loads(runtime_config.read_text()) != mcfg: raise ValueError('Retry rejected: merge runtime configuration differs from current inputs or configuration')
            if merge_output.exists() or merge_output.is_symlink(): raise ValueError('Retry rejected: merge output directory already exists')
        else:
            if runtime_config.exists(): raise ValueError('Merge step already started for this profile; use --retry-merge only after reviewing failure')
            if merge_output.exists() or merge_output.is_symlink(): raise ValueError('Merge output directory already exists')
            dump(runtime_config, mcfg)
        if recorded_output != merge_output:
            dump(location_file, {'output_dir': str(merge_output)})
        run([sys.executable, ROOT / 'RP1_Project/merge_af_ba_panels.py', '--repo-root', ROOT, '--config', runtime_config, '--profile', a.profile, '--run-id', analysis_run_id(a.run_id, a.profile), '--unit-universe', unit_csv, '--af-root', inside(af['af_root']), '--output-dir', merge_output])
    else:
        verified_geo(state)
        location_file = state / ('merge_' + a.profile + '_location.json')
        merged = Path(json.loads(location_file.read_text())['output_dir']) if location_file.exists() else state / 'merge' / a.profile
        manifest = json.loads((merged / 'fire_panel_manifest.json').read_text())
        if manifest.get('merge_run_id') != analysis_run_id(a.run_id, a.profile) or manifest.get('profile_id') != a.profile: raise ValueError('Merger run or profile identity differs')
        if manifest.get('profile_id')!='c3' or manifest.get('ba_bundle',{}).get('scope')!='full':
            raise ValueError('Full c3 admission is required; pilot inputs cannot rewrite scientific configuration')
        raw = ANALYSIS / 'data/raw'
        if (state / 'analysis_inputs.json').exists():
            verify_completed_handoff(state, merged, a.profile)
            print('Workflow step already completed and verified: analysis-inputs')
            return
        if a.resume_analysis_inputs:
            verify_interrupted_handoff(merged, raw)
        else:
            if raw.exists() and any(raw.iterdir()): raise ValueError('Analysis raw input directory is occupied; use a separate clean checkout or --resume-analysis-inputs for a verified interrupted handoff')
            if raw.exists(): raw.rmdir()
            run([sys.executable, ANALYSIS / 'scripts/prepare_profile_handoff.py', merged, raw])
        run([sys.executable, ANALYSIS / 'scripts/configure_generated_inputs.py', '--subproject-root', ANALYSIS])
        run([sys.executable, ANALYSIS / 'scripts/render_data_schema_contract.py'])
        run([sys.executable, ANALYSIS / 'scripts/regenerate_data_provenance.py', '--subproject-root', ANALYSIS])
        dump(state / 'analysis_inputs.json', {'profile': a.profile, 'merger_manifest_sha256': sha(merged / 'fire_panel_manifest.json'), 'input_inventory_sha256': sha(ANALYSIS / 'data/input_sha256.json'), 'input_contract_sha256': sha(ANALYSIS / 'config/data_schema_contract.yml')})
    print('Workflow step completed:', a.step)

if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as e:
        raise SystemExit('Workflow failed: ' + str(e))
