"""Bounded workflow identity and CLI contract tests."""
from pathlib import Path
import importlib.util
import json
import sys
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('workflow', ROOT / 'tools/run_workflow.py')
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


@pytest.mark.parametrize('native_supports', [False, True])
def test_all_stages_receive_the_same_resolved_calendar_snapshot(tmp_path, monkeypatch, native_supports):
    declared = {'start_yyyymm': 200101, 'end_yyyymm': 202412}
    if native_supports:
        declared.update(viirs_support_start_yyyymm=201201, ba2012_support_start_yyyymm=201201)
    config = {'schema':'rp1-local-workflow-v1', 'study':declared, 'output_root':'out/workflows'}
    (tmp_path/'config.json').write_text(json.dumps(config), encoding='utf-8')
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    calls = []
    monkeypatch.setattr(workflow, 'reuse_geo_handoff', lambda state, resolved: calls.append(resolved['study'].copy()))
    monkeypatch.setattr(sys, 'argv', ['workflow', '--config', 'config.json', '--run-id', 'calendar', 'geo-reuse'])
    for _ in range(2):
        workflow.main()
    expected = workflow.validate_study(declared)
    saved = json.loads((tmp_path/'out/workflows/calendar/workflow.json').read_text())
    assert calls == [expected, expected]
    assert saved['study'] == expected
    assert json.loads((tmp_path/'config.json').read_text()) == config


@pytest.mark.parametrize('fail', [False, True])
def test_main_pins_checkout_sources_only_during_execution(tmp_path, monkeypatch, fail):
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    before = sys.path[:]
    required = {str(tmp_path / part / 'src') for part in (
        'geo_data_prep', 'RP1_Project/rp1_mv_firms_panels',
        'RP1_Project/rp1_analysis', 'RP1_Project/rp1_firms_archive')}
    def operation():
        assert required <= set(sys.path)
        if fail:
            raise ValueError('simulated stage rejection')
        return 'completed'
    monkeypatch.setattr(workflow, '_main', operation)
    if fail:
        with pytest.raises(ValueError, match='simulated stage rejection'):
            workflow.main()
    else:
        assert workflow.main() == 'completed'
    assert sys.path == before


def test_release_default_requires_upstream_archive_and_explicit_bundled_opt_in():
    import yaml
    config = json.loads((ROOT / 'configs/workflow.json').read_text(encoding='utf-8'))
    options = config['firms_archive']
    assert options['mode'] == 'build'
    producer = ROOT / options['producer_config']
    settings = yaml.safe_load(producer.read_text(encoding='utf-8'))
    assert set(settings['sources']) == {'MODIS_SP', 'VIIRS_SNPP_SP'}
    assert settings['years']['start'] <= config['study']['start_yyyymm'] // 100
    assert settings['years']['end'] >= config['study']['end_yyyymm'] // 100
    assert not settings.get('key_file')
    assert not settings.get('map_key')
    bundled = json.loads((ROOT / 'configs/workflow_bundled.example.json').read_text(encoding='utf-8'))
    assert bundled['firms_archive']['mode'] == 'bundled'
    assert config['geo_config'] == bundled['geo_config']
    assert config['study'] == bundled['study']


def test_workflow_rejects_paths_outside_checkout(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    with pytest.raises(ValueError, match='inside the project'):
        workflow.inside('../foreign')


def test_geo_binding_detects_changed_generated_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    path = tmp_path / 'RP1_Project/data/acz.shp'
    path.parent.mkdir(parents=True); path.write_bytes(b'geometry')
    manifest = tmp_path / 'RP1_Project/geo_handoff_manifest.json'
    manifest.write_text(json.dumps({'files': {'RP1_Project/data/acz.shp': {'sha256': workflow.sha(path)}}}))
    state = tmp_path / 'state'; state.mkdir()
    (state/'geo.json').write_text(json.dumps({'project_manifest_sha256':workflow.sha(manifest)}))
    workflow.verified_geo(state)
    path.write_bytes(b'changed')
    with pytest.raises(ValueError, match='Staged geography changed'):
        workflow.verified_geo(state)


@pytest.mark.parametrize('projected_aoi', [False, True])
def test_generated_firms_command_uses_selected_window_and_explicit_root(tmp_path, monkeypatch, projected_aoi):
    import yaml
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    firms = tmp_path / 'RP1_Project/rp1_mv_firms_panels'
    monkeypatch.setattr(workflow, 'FIRMS', firms)
    template = yaml.safe_load((ROOT/'RP1_Project/rp1_mv_firms_panels/configs/ghana_full.yaml').read_text())
    firms.mkdir(parents=True)
    (firms/'source.yaml').write_text(yaml.safe_dump(template))
    config = {'schema':'rp1-local-workflow-v1','study':{'start_yyyymm':201301,'end_yyyymm':201412,'viirs_support_start_yyyymm':201301,'ba2012_support_start_yyyymm':201301}, 'output_root':'out/workflows','firms_config':'RP1_Project/rp1_mv_firms_panels/source.yaml','land_mask':'inputs/land.shp'}
    (tmp_path/'workflow.json').write_text(json.dumps(config))
    state=tmp_path/'out/workflows/check';state.mkdir(parents=True)
    (state/'geo.json').write_text('{}')
    geography = {}
    expected_land = tmp_path/'inputs/land.shp'
    if projected_aoi:
        from types import SimpleNamespace
        geo_config = tmp_path/'geo.yaml'
        geo_config.write_text(yaml.safe_dump({'project_root': '.', 'inputs': {'national': {'path': 'inputs/land.shp'}}}))
        config['geo_config'] = 'geo.yaml'
        (tmp_path/'workflow.json').write_text(json.dumps(config))
        geography['gee_upload'] = 'out/workflows/check/gee_upload'
        expected_land = tmp_path/geography['gee_upload']/'layers/gha_admin0/gha_admin0.shp'
        monkeypatch.setitem(sys.modules, 'stage_gee_handoff', SimpleNamespace(verify=lambda _: {
            'run_id': 'check', 'national_relative_path': 'layers/gha_admin0/gha_admin0.shp'}))
    monkeypatch.setattr(workflow, 'verified_geo', lambda _: geography)
    calls=[]
    def fake_run(command, cwd):
        calls.append(command)
        assert command[command.index('--repo-root')+1] == firms
        generated=yaml.safe_load(Path(command[command.index('--config')+1]).read_text())
        assert generated['processing']['time_range']['start_yyyymm']==201301
        assert generated['processing']['time_range']['end_yyyymm']==201412
        assert generated['io']['inputs']['land_mask']==str(expected_land)
        assert command[command.index('--years-modis')+1]=='2013-2014'
    monkeypatch.setattr(workflow,'run',fake_run)
    monkeypatch.setattr(sys,'argv',['run_workflow.py','--config','workflow.json','--run-id','check','firms'])
    workflow.main()
    assert len(calls)==1
    receipt=json.loads((state/'firms.json').read_text())
    assert receipt['af_root']=='RP1_Project/rp1_mv_firms_panels/out/runs/check/rp1_af_exports'
    assert receipt['config_path']=='RP1_Project/rp1_mv_firms_panels/configs/generated/check.yaml'


def test_gee_inputs_packages_existing_geo_without_changing_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    config = {'schema': 'rp1-local-workflow-v1', 'study': {'start_yyyymm': 200101, 'end_yyyymm': 202412},
              'output_root': 'out/workflows', 'geo_config': 'geo.yaml'}
    (tmp_path/'workflow.json').write_text(json.dumps(config))
    state = tmp_path/'out/workflows/check'
    state.mkdir(parents=True)
    receipt = state/'geo.json'
    receipt.write_text('{"original":true}')
    monkeypatch.setattr(workflow, 'verified_geo', lambda _: {'source_run': 'geo_data_prep/out/check'})
    calls = []
    monkeypatch.setattr(workflow, 'gee_upload_bundle', lambda *args: (calls.append(args) or (state/'gee_upload', {})))
    monkeypatch.setattr(sys, 'argv', ['workflow', '--config', 'workflow.json', '--run-id', 'check', 'gee-inputs'])
    workflow.main()
    assert calls == [(tmp_path/'geo_data_prep/out/check', state, tmp_path/'geo.yaml', 'check')]
    assert receipt.read_text() == '{"original":true}'


def test_gee_bundle_reuse_verifies_and_rejects_another_run(tmp_path, monkeypatch):
    from types import SimpleNamespace
    destination = tmp_path/'gee_upload'
    destination.mkdir()
    calls = []
    module = SimpleNamespace(verify=lambda p: (calls.append(p) or {'run_id': 'other'}),
                             build=lambda *args: pytest.fail('Existing bundle must not be overwritten'))
    monkeypatch.setitem(sys.modules, 'stage_gee_handoff', module)
    with pytest.raises(ValueError, match='different geography run'):
        workflow.gee_upload_bundle(tmp_path/'source', tmp_path, tmp_path/'geo.yaml', 'check')
    assert calls == [destination]


def test_new_geo_builds_upload_bundle_before_applying_handoff(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    config = {'schema': 'rp1-local-workflow-v1', 'study': {'start_yyyymm': 200101, 'end_yyyymm': 202412},
              'output_root': 'out/workflows', 'geo_config': 'geo.yaml'}
    (tmp_path/'workflow.json').write_text(json.dumps(config))
    (tmp_path/'geo.yaml').write_text(yaml.safe_dump({'project_root': '.', 'outputs': {'root': 'geo_out'}}))
    operations = []
    monkeypatch.setattr(workflow, 'run', lambda *args, **kw: operations.append('geo'))
    monkeypatch.setattr(workflow.geo_handoff, 'build', lambda *args: operations.append('handoff'))
    monkeypatch.setattr(workflow, 'gee_upload_bundle', lambda source, state, cfg, run: (
        operations.append('gee') or (state/'gee_upload', {'run_id': run})))
    def apply(*args):
        operations.append('apply')
        manifest = tmp_path/'RP1_Project/geo_handoff_manifest.json'
        manifest.parent.mkdir()
        manifest.write_text('{}')
    monkeypatch.setattr(workflow.geo_handoff, 'apply', apply)
    monkeypatch.setattr(sys, 'argv', ['workflow', '--config', 'workflow.json', '--run-id', 'check', 'geo'])
    workflow.main()
    assert operations == ['geo', 'handoff', 'gee', 'apply']
    receipt = json.loads((tmp_path/'out/workflows/check/geo.json').read_text())
    assert receipt['source_run'] == 'geo_out/check'
    assert receipt['gee_upload'] == 'out/workflows/check/gee_upload'


@pytest.mark.parametrize('step,backup', [('firms','absolute'), ('geo','relative/backup')])
def test_geo_backup_requires_geo_and_absolute_path(tmp_path, monkeypatch, step, backup):
    value = str(tmp_path/'backup') if backup == 'absolute' else backup
    monkeypatch.setattr(sys, 'argv', ['workflow','--run-id','check','--geo-backup',value,step])
    with pytest.raises(SystemExit) as error:
        workflow.main()
    assert error.value.code == 2


def test_geo_replacement_is_explicit_and_backup_bound(tmp_path, monkeypatch):
    import yaml
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    config={'schema':'rp1-local-workflow-v1','study':{'start_yyyymm':200101,'end_yyyymm':202412},
            'output_root':'out/workflows','geo_config':'geo.yaml'}
    (tmp_path/'workflow.json').write_text(json.dumps(config))
    (tmp_path/'geo.yaml').write_text(yaml.safe_dump({'project_root':'.','outputs':{'root':'geo_out'}}))
    backup=tmp_path/'saved'
    monkeypatch.setattr(workflow, 'run', lambda *a,**kw: None)
    monkeypatch.setattr(workflow.geo_handoff, 'build', lambda *a: None)
    monkeypatch.setattr(workflow,'gee_upload_bundle',lambda source,state,cfg,run:(state/'gee_upload',{}))
    def apply(bundle, root, *, replace, backup_arg):
        assert replace is True and backup_arg == str(backup)
        backup.mkdir()
        (backup/'backup_manifest.json').write_text('{"preserved":true}')
        manifest=root/'RP1_Project/geo_handoff_manifest.json'
        manifest.parent.mkdir()
        manifest.write_text('{}')
        return {'backup':str(backup)}
    monkeypatch.setattr(workflow.geo_handoff,'apply',apply)
    monkeypatch.setattr(sys,'argv',['workflow','--config','workflow.json','--run-id','check','--geo-backup',str(backup),'geo'])
    workflow.main()
    receipt=json.loads((tmp_path/'out/workflows/check/geo.json').read_text())
    assert receipt['previous_handoff_backup']=={'path':str(backup),'manifest_sha256':workflow.sha(backup/'backup_manifest.json')}


@pytest.mark.parametrize('external', [False, True])
def test_analysis_staging_configures_before_provenance(tmp_path, monkeypatch, external):
    monkeypatch.setattr(workflow, 'ROOT', tmp_path)
    analysis = tmp_path/'RP1_Project/rp1_analysis'
    monkeypatch.setattr(workflow, 'ANALYSIS', analysis)
    cfg={'schema':'rp1-local-workflow-v1','study':{'start_yyyymm':201301,'end_yyyymm':202412,'viirs_support_start_yyyymm':201301,'ba2012_support_start_yyyymm':201301},'output_root':'out/workflows'}
    (tmp_path/'workflow.json').write_text(json.dumps(cfg))
    state = tmp_path/'out/workflows/check'
    out = tmp_path/'external/check/c3' if external else state/'merge/c3'
    out.mkdir(parents=True)
    if external:
        state.mkdir(parents=True, exist_ok=True)
        (state/'merge_c3_location.json').write_text(json.dumps({'output_dir': str(out)}))
    (out/'fire_panel_manifest.json').write_text(json.dumps({'merge_run_id':'check_c3','profile_id':'c3','ba_bundle':{'scope':'full'}}))
    monkeypatch.setattr(workflow,'verified_geo',lambda _: {})
    calls=[]
    def fake_run(command):
        calls.append(Path(command[1]).name)
        if calls[-1]=='prepare_profile_handoff.py':
            assert command[2] == out
        if calls[-1]=='regenerate_data_provenance.py':
            (analysis/'data').mkdir(parents=True,exist_ok=True)
            (analysis/'data/input_sha256.json').write_text('{}')
            (analysis/'config').mkdir(parents=True,exist_ok=True)
            (analysis/'config/data_schema_contract.yml').write_text('test contract')
    monkeypatch.setattr(workflow,'run',fake_run)
    monkeypatch.setattr(sys,'argv',['run_workflow.py','--config','workflow.json','--run-id','check','--profile','c3','analysis-inputs'])
    workflow.main()
    assert calls == ['prepare_profile_handoff.py','configure_generated_inputs.py','render_data_schema_contract.py','regenerate_data_provenance.py']
