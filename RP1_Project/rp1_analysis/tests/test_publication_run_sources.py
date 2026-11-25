from pathlib import Path
from types import SimpleNamespace
import json
import pytest
from rp1_analysis_v1 import publication_sources as ps

class Paths:
    def __init__(self, root): self.root = root.resolve()
    def resolve_inside(self, p):
        target = (self.root / p).resolve()
        if not target.is_relative_to(self.root): raise ValueError('path escape')
        return target
    @property
    def all_hashed_inputs(self): return (self.root/'data/raw/input.csv',)
    @property
    def input_hash_inventory(self): return self.root/'data/input_sha256.json'


def _source_bundle(configuration_sha256="config"):
    spec = SimpleNamespace(source_attribute="table", builder_options={})
    return SimpleNamespace(
        configuration_sha256=configuration_sha256,
        output=SimpleNamespace(tables=(spec,)),
        figure=SimpleNamespace(figures=()),
    )

@pytest.fixture
def run(tmp_path,monkeypatch):
    p=Paths(tmp_path); (tmp_path/'config').mkdir(); (tmp_path/'data/raw').mkdir(parents=True)
    (tmp_path/'src/rp1_analysis_v1').mkdir(parents=True)
    (tmp_path/'src/rp1_analysis_v1/a.py').write_text('code')
    (tmp_path/'RP1_Analysis_v1.ipynb').write_text(json.dumps({'cells': [{'cell_type': 'code', 'source': ['x = 1\n'], 'metadata': {}, 'outputs': [], 'execution_count': None}]}))
    (tmp_path/'data/input_sha256.json').write_text('{}');(tmp_path/'data/raw/input.csv').write_text('input')
    monkeypatch.setattr(ps,'load_configuration_bundle',lambda _: _source_bundle())
    d=tmp_path/'out/publication_sources/run1'; d.mkdir(parents=True); f=d/'table.csv';f.write_text('value\n1\n')
    manifest={'schema':'rp1-publication-sources-run-v2','run_id':'run1','configuration_sha256':'config','input_identity':ps._source_input_identity(p),'sources':{'table':{'path':str(f.relative_to(tmp_path)),'sha256':ps._digest(f)}}}
    (d/ps.MANIFEST_NAME).write_text(json.dumps(manifest));return p,d,manifest

def test_valid_and_stale_input(run):
    p,d,m=run; assert ps.verify_primary_publication_sources(p,'run1')['run_id']=='run1'
    (p.root/'data/raw/input.csv').write_text('changed')
    with pytest.raises(ps.PublicationSourceError,match='inputs or code'):ps.verify_primary_publication_sources(p,'run1')

def test_changed_source_and_code(run):
    p,d,m=run;(d/'table.csv').write_text('tampered')
    with pytest.raises(ps.PublicationSourceError,match='modified'):ps.verify_primary_publication_sources(p,'run1')
    (d/'table.csv').write_text('value\n1\n'); (p.root/'src/rp1_analysis_v1/a.py').write_text('changed')
    with pytest.raises(ps.PublicationSourceError,match='inputs or code'):ps.verify_primary_publication_sources(p,'run1')

def test_mismatch_and_escape(run):
    p,d,m=run;m['run_id']='other';(d/ps.MANIFEST_NAME).write_text(json.dumps(m))
    with pytest.raises(ps.PublicationSourceError,match='identity'):ps.verify_primary_publication_sources(p,'run1')
    m['run_id']='run1';m['sources']['table']['path']='data/raw/input.csv';(d/ps.MANIFEST_NAME).write_text(json.dumps(m))
    with pytest.raises(ps.PublicationSourceError,match='unsafe'):ps.verify_primary_publication_sources(p,'run1')
    with pytest.raises(ps.PublicationSourceError,match='Invalid'):ps.verify_primary_publication_sources(p,'../bad')

def test_real_governed_paths_hash_current_files(tmp_path):
    from rp1_analysis_v1.paths import ProjectPaths
    root=tmp_path; (root/'data/raw').mkdir(parents=True); (root/'src/rp1_analysis_v1').mkdir(parents=True)
    (root/'src/rp1_analysis_v1/mod.py').write_text('code'); (root/'RP1_Analysis_v1.ipynb').write_text(json.dumps({'cells':[{'cell_type':'code','source':'pass','metadata':{}}]}))
    (root/'data/raw/input.csv').write_text('one')
    (root/'data/input_sha256.json').write_text(json.dumps({'schema_version':'v','provenance_schema_version':'rp1-input-provenance-v2','files':[{'staged_path':'data/raw/input.csv'}]}))
    paths=ProjectPaths(root); a=ps._source_input_identity(paths)
    (root/'data/raw/input.csv').write_text('two');b=ps._source_input_identity(paths)
    assert a['inventory_sha256']==b['inventory_sha256'] and a['files']!=b['files']

def test_config_change_rejected(run,monkeypatch):
    p,d,m=run
    monkeypatch.setattr(ps,'load_configuration_bundle',lambda _:SimpleNamespace(configuration_sha256='different'))
    with pytest.raises(ps.PublicationSourceError,match='configuration identity'):ps.verify_primary_publication_sources(p,'run1')


def test_notebook_output_save_does_not_change_identity_but_source_and_tags_do(run):
    p, _, _ = run
    path = p.root/'RP1_Analysis_v1.ipynb'
    nb = json.loads(path.read_text())
    nb['cells'][0].update(outputs=[{'output_type': 'stream', 'name': 'stdout', 'text': ['saved\n']}], execution_count=8)
    nb['metadata'] = {'save_timestamp': 'changed'}
    nb['cells'][0]['metadata']['execution'] = {'start': 'now'}
    path.write_text(json.dumps(nb, indent=2))
    ps.verify_primary_publication_sources(p, 'run1')
    nb['cells'][0]['source'] = ['x = 2\n']
    path.write_text(json.dumps(nb))
    with pytest.raises(ps.PublicationSourceError, match=r'code:RP1_Analysis_v1.ipynb'):
        ps.verify_primary_publication_sources(p, 'run1')
    nb['cells'][0]['source'] = ['x = 1\n']
    nb['cells'][0]['metadata']['tags'] = ['skip-execution']
    path.write_text(json.dumps(nb))
    with pytest.raises(ps.PublicationSourceError, match=r'code:RP1_Analysis_v1.ipynb'):
        ps.verify_primary_publication_sources(p, 'run1')


def test_identity_difference_reports_changed_added_and_removed_paths(run):
    p, _, _ = run
    before = ps._source_input_identity(p)
    (p.root/'data/raw/input.csv').write_text('changed')
    (p.root/'src/rp1_analysis_v1/a.py').unlink()
    (p.root/'src/rp1_analysis_v1/b.py').write_text('new')
    (p.root/'data/input_sha256.json').write_text('{"changed":true}')
    with pytest.raises(ps.PublicationSourceError) as error:
        ps._require_same_identity(before, ps._source_input_identity(p), 'Inputs changed')
    message = str(error.value)
    for name in ['files:data/raw/input.csv', 'code:src/rp1_analysis_v1/a.py', 'code:src/rp1_analysis_v1/b.py', 'inventory_sha256']:
        assert name in message


def test_legacy_manifest_retains_raw_notebook_identity(run):
    p, d, manifest = run
    manifest['schema'] = 'rp1-publication-sources-run-v1'
    manifest['input_identity'] = ps._source_input_identity(p, legacy=True)
    (d/ps.MANIFEST_NAME).write_text(json.dumps(manifest))
    ps.verify_primary_publication_sources(p, 'run1')
    path = p.root/'RP1_Analysis_v1.ipynb'
    path.write_text(json.dumps(json.loads(path.read_text()), indent=2))
    with pytest.raises(ps.PublicationSourceError, match=r'code:RP1_Analysis_v1.ipynb'):
        ps.verify_primary_publication_sources(p, 'run1')


def test_notebook_source_identity_tracks_order_and_rejects_malformed_notebook():
    cells = [{'cell_type':'code', 'source':'a=1', 'metadata':{}},
             {'cell_type':'markdown', 'source':['text'], 'metadata':{}}]
    original = ps._notebook_payload_digest({'cells':cells})
    assert original != ps._notebook_payload_digest({'cells':list(reversed(cells))})
    with pytest.raises(ps.PublicationSourceError, match='notebook source'):
        ps._notebook_payload_digest({'cells':[{'cell_type':'code', 'source':5}]})


def test_configuration_change_reports_file(run, monkeypatch):
    p, _, _ = run
    before = SimpleNamespace(configuration_sha256='old', file_hashes={'analysis.yml':'a'})
    after = SimpleNamespace(configuration_sha256='new', file_hashes={'analysis.yml':'b'})
    monkeypatch.setattr(ps, 'load_configuration_bundle', lambda _: after)
    with pytest.raises(ps.PublicationSourceError, match='config/analysis.yml'):
        ps._require_same_configuration(p, before, 'Configuration changed')
