import importlib.util, json, sys
from pathlib import Path
import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
spec=importlib.util.spec_from_file_location('retry_workflow', TOOLS/'run_workflow.py')
w=importlib.util.module_from_spec(spec); spec.loader.exec_module(w)

def setup(monkeypatch,tmp_path):
    root=tmp_path; firms=root/'RP1_Project/rp1_mv_firms_panels'; state=root/'out/workflows/local_test'; state.mkdir(parents=True)
    (root/'configs').mkdir(); (firms/'data/metadata').mkdir(parents=True)
    (firms/'data/metadata/unit_universe.csv').write_text('level\nacz\ndistrict\n')
    (state/'geo.json').write_text('{}'); cfgp=firms/'firms.yaml'; cfgp.write_text('test')
    (state/'firms.json').write_text(json.dumps({'geo_receipt_sha256':w.sha(state/'geo.json'),'config_path':str(cfgp.relative_to(root)),'config_sha256':w.sha(cfgp),'af_root':'RP1_Project/rp1_mv_firms_panels/out/af'}))
    (root/'configs/merge.json').write_text(json.dumps({'profiles':{'c3':{'source_label':'c3','source_schema_version':'rp1_ba_c3_extended_v2','quality_policy':'c3_preserve_admission_v1','method_version':'c3_methods_v1_schema_v2'}}}))
    cfg={'schema':'rp1-local-workflow-v1','study':{'start_yyyymm':200101,'end_yyyymm':202412},'output_root':'out/workflows','merge_config':'configs/merge.json'}
    (root/'configs/workflow.json').write_text(json.dumps(cfg))
    for k,v in [('ROOT',root),('FIRMS',firms)]: monkeypatch.setattr(w,k,v)
    monkeypatch.setattr(w,'verified_geo',lambda state: {})
    (state/'ba_c3.json').write_text('{}')
    profile={'source_label':'c3','source_schema_version':'rp1_ba_c3_extended_v2','quality_policy':'c3_preserve_admission_v1','method_version':'c3_methods_v1_schema_v2'}
    monkeypatch.setattr(w,'verify_ba_handoff',lambda *_: {'profile_contract':profile,**{key:str(state/key) for key in ('ba2001_root','ba2012_root','source_lock','bundle_manifest','bundle_handoff')}})
    monkeypatch.setattr(w,'run',lambda *a,**kw:None)
    monkeypatch.setattr(sys,'argv',['run_workflow','--run-id','local_test','--profile','c3','merge'])
    return state

def test_retry_integrity(monkeypatch,tmp_path):
    state=setup(monkeypatch,tmp_path)
    w.main()
    runtime=state/'merge_c3.json'; original=runtime.read_bytes()
    with pytest.raises(ValueError,match='already started'): w.main()
    monkeypatch.setattr(sys,'argv',['run_workflow','--run-id','local_test','--profile','c3','--retry-merge','merge'])
    w.main(); assert runtime.read_bytes()==original
    (state/'merge/c3').mkdir(parents=True)
    with pytest.raises(ValueError,match='output directory already exists'): w.main()

def test_retry_changed_and_missing(monkeypatch,tmp_path):
    state=setup(monkeypatch,tmp_path)
    monkeypatch.setattr(sys,'argv',['run_workflow','--run-id','local_test','--profile','c3','--retry-merge','merge'])
    with pytest.raises(ValueError,match='existing merge runtime'): w.main()
    (state/'merge_c3.json').write_text('{}')
    with pytest.raises(ValueError,match='configuration differs'): w.main()

def test_retry_can_relocate_failed_publication_and_reuses_binding(monkeypatch, tmp_path):
    state = setup(monkeypatch, tmp_path)
    commands = []
    monkeypatch.setattr(w, 'run', lambda command, **kw: commands.append(command))
    w.main()
    destination = tmp_path / 'native-output'
    monkeypatch.setattr(sys, 'argv', ['run_workflow', '--run-id', 'local_test', '--profile', 'c3', '--retry-merge', '--merge-output-root', str(destination), 'merge'])
    w.main()
    expected = destination / 'local_test/c3'
    assert Path(commands[-1][-1]) == expected
    assert json.loads((state / 'merge_c3_location.json').read_text())['output_dir'] == str(expected)
    monkeypatch.setattr(sys, 'argv', ['run_workflow', '--run-id', 'local_test', '--profile', 'c3', '--retry-merge', 'merge'])
    w.main()
    assert Path(commands[-1][-1]) == expected
    expected.mkdir(parents=True)
    with pytest.raises(ValueError, match='recorded merge output directory already exists'):
        monkeypatch.setattr(sys, 'argv', ['run_workflow', '--run-id', 'local_test', '--profile', 'c3', '--retry-merge', '--merge-output-root', str(tmp_path / 'other'), 'merge'])
        w.main()

def test_merge_output_root_must_be_absolute(monkeypatch, tmp_path):
    setup(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, 'argv', ['run_workflow', '--run-id', 'local_test', '--profile', 'c3', '--merge-output-root', 'relative', 'merge'])
    with pytest.raises(ValueError, match='must be an absolute path'):
        w.main()


def test_interrupted_handoff_verifies_origin_manifest_and_bytes(tmp_path):
    merged = tmp_path / 'merge'; merged.mkdir()
    raw = tmp_path / 'raw'; raw.mkdir()
    content = b'panel data'
    (merged / 'panel.csv').write_bytes(content)
    (raw / 'panel.csv').write_bytes(content)
    manifest = {'outputs': {
        'panel': {'staged_path': '/external/panel.csv', 'origin_path': '/external/panel.csv', 'sha256': w.sha(merged / 'panel.csv')},
        'manifest': {'staged_path': '/external/fire_panel_manifest.json', 'origin_path': '/external/fire_panel_manifest.json'},
    }}
    source = json.dumps(manifest).encode()
    (merged / 'fire_panel_manifest.json').write_bytes(source)
    (raw / 'original_merger_manifest.json').write_bytes(source)
    relocated = json.loads(source)
    for record in relocated['outputs'].values():
        record['staged_path'] = 'RP1_Project/rp1_analysis/data/raw/' + Path(record['staged_path']).name
    relocated['analysis_handoff'] = {'original_manifest_file': 'original_merger_manifest.json', 'original_manifest_sha256': w.sha(merged / 'fire_panel_manifest.json'), 'note': 'Output paths describe the Stage 5 analysis input location; source provenance and output hashes are unchanged.'}
    (raw / 'fire_panel_manifest.json').write_text(json.dumps(relocated))
    w.verify_interrupted_handoff(merged, raw)
    (raw / 'panel.csv').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='hash differs'):
        w.verify_interrupted_handoff(merged, raw)
    (raw / 'panel.csv').write_bytes(content)
    relocated['outputs']['panel']['origin_path'] = 'invented/path'
    (raw / 'fire_panel_manifest.json').write_text(json.dumps(relocated))
    with pytest.raises(ValueError, match='handoff manifest differs'):
        w.verify_interrupted_handoff(merged, raw)


def test_analysis_resume_verifies_before_continuing(monkeypatch, tmp_path):
    state = setup(monkeypatch, tmp_path)
    analysis = tmp_path / 'analysis'
    (analysis / 'data/raw').mkdir(parents=True)
    (analysis / 'data/input_sha256.json').write_text('{}')
    (analysis / 'config').mkdir()
    (analysis / 'config/data_schema_contract.yml').write_text('test contract')
    merged = tmp_path / 'external/local_test/c3'
    merged.mkdir(parents=True)
    (merged / 'fire_panel_manifest.json').write_text(json.dumps({'merge_run_id':'local_test_c3','profile_id':'c3','ba_bundle':{'scope':'full'}}))
    (state / 'merge_c3_location.json').write_text(json.dumps({'output_dir':str(merged)}))
    monkeypatch.setattr(w, 'ANALYSIS', analysis)
    operations = []
    monkeypatch.setattr(w, 'verify_interrupted_handoff', lambda source, target: operations.append('verify'))
    monkeypatch.setattr(w, 'run', lambda command, **kw: operations.append(Path(command[1]).name))
    monkeypatch.setattr(sys, 'argv', ['run_workflow','--run-id','local_test','--profile','c3','--resume-analysis-inputs','analysis-inputs'])
    w.main()
    assert operations == ['verify', 'configure_generated_inputs.py', 'render_data_schema_contract.py', 'regenerate_data_provenance.py']
    assert json.loads((state / 'analysis_inputs.json').read_text())['profile'] == 'c3'


def test_completed_handoff_is_verified_without_rebuilding(monkeypatch, tmp_path):
    state = setup(monkeypatch, tmp_path)
    analysis = tmp_path / 'analysis'
    (analysis / 'data/raw').mkdir(parents=True)
    (analysis / 'config').mkdir()
    contract = analysis / 'config/data_schema_contract.yml'
    contract.write_text('test contract')
    data = analysis / 'data/raw/panel.csv'
    data.write_bytes(b'panel')
    inventory = analysis / 'data/input_sha256.json'
    inventory.write_text(json.dumps({'files': [{'staged_path': 'data/raw/panel.csv',
        'sha256': w.sha(data), 'size_bytes': data.stat().st_size}]}))
    merged = state / 'merge/c3'
    merged.mkdir(parents=True)
    source_manifest = merged / 'fire_panel_manifest.json'
    source_manifest.write_text(json.dumps({'merge_run_id': 'local_test_c3', 'profile_id': 'c3','ba_bundle':{'scope':'full'}}))
    receipt = state / 'analysis_inputs.json'
    receipt.write_text(json.dumps({'profile': 'c3', 'merger_manifest_sha256': w.sha(source_manifest),
                                   'input_inventory_sha256': w.sha(inventory),
                                   'input_contract_sha256': w.sha(contract)}))
    receipt_bytes = receipt.read_bytes()
    monkeypatch.setattr(w, 'ANALYSIS', analysis)
    checked = []
    monkeypatch.setattr(w, 'configured_analysis_inputs', lambda: {'data/raw/panel.csv'})
    monkeypatch.setattr(w, 'verify_interrupted_handoff', lambda *args: checked.append(True))
    monkeypatch.setattr(w, 'run', lambda *args, **kw: pytest.fail('Completed handoff must not rebuild'))
    monkeypatch.setattr(sys, 'argv', ['workflow', '--run-id', 'local_test', '--profile', 'c3',
                                    '--resume-analysis-inputs', 'analysis-inputs'])
    w.main()
    assert checked == [True] and receipt.read_bytes() == receipt_bytes
    data.write_bytes(b'altered')
    with pytest.raises(ValueError, match='input changed'):
        w.main()
    data.write_bytes(b'panel')
    monkeypatch.setattr(w, 'configured_analysis_inputs', lambda: {'data/raw/panel.csv', 'data/raw/new.csv'})
    with pytest.raises(ValueError, match='configured input contract'):
        w.main()
    contract.write_text('changed contract')
    with pytest.raises(ValueError, match='input contract changed'):
        w.main()
