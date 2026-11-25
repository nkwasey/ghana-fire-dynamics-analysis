"""Safety tests for handoff preparation and no-overwrite application."""
import importlib.util
import json
from pathlib import Path
import pytest

MODULE = Path(__file__).resolve().parents[1] / 'tools' / 'stage_geo_handoff.py'
spec = importlib.util.spec_from_file_location('stage_geo_handoff', MODULE)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

@pytest.fixture
def source_run(tmp_path, monkeypatch):
    run = tmp_path / 'run'
    run.mkdir()
    files = {}
    for i, relative in enumerate(mod.MAPPING):
        target = run / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f'sample {i}', encoding='utf-8')
        files[relative] = {'bytes': target.stat().st_size, 'sha256': mod.sha256(target)}
    contract = run / 'contract/stage1_contract_manifest.json'
    contract.parent.mkdir(parents=True)
    contract.write_text('{}')
    files['contract/stage1_contract_manifest.json'] = {'bytes': contract.stat().st_size, 'sha256': mod.sha256(contract)}
    qa = run / 'qa/qa_summary.json'
    qa.parent.mkdir(parents=True)
    qa.write_text('{}')
    files['qa/qa_summary.json'] = {'bytes': qa.stat().st_size, 'sha256': mod.sha256(qa)}
    fingerprint = run / 'inputs_fingerprint.json'
    fingerprint.write_text('{}')
    files['inputs_fingerprint.json'] = {'bytes': fingerprint.stat().st_size, 'sha256': mod.sha256(fingerprint)}
    (run / 'outputs_manifest.json').write_text(json.dumps({'schema': 'geo-data-output-manifest-v1', 'run_id': 'sample', 'files': files}))
    monkeypatch.setattr(mod, 'check_identities', lambda run: {'run_id': 'sample', 'qa_status': 'WARN', 'warning_count': 1, 'layers': {'analysis_boundaries': {'crs': 'EPSG:32630'}}})
    monkeypatch.setattr(mod, 'verify_projected_bundle', lambda *args: None)
    return run

def test_build_checks_all_hashes_and_creates_mirrored_bundle(source_run, tmp_path):
    bundle = tmp_path / 'handoff'
    result = mod.build(source_run, bundle)
    assert set(result['files']) == set(mod.MAPPING.values())
    assert result['source_run']['qa_status'] == 'WARN'
    assert (bundle / mod.MAPPING['unit_universe.csv']).is_file()
    assert (bundle / mod.MAPPING['analysis_boundaries/acz.shp']).is_file()
    assert not any('gha_admin0' in str(path) for path in bundle.rglob('*'))
    assert result['schema'] == 'rp1-geo-handoff-v2'
    assert result['boundary_crs'] == 'EPSG:32630'
    for base in ('acz', 'districts_within_acz'):
        for ext in mod.EXTENSIONS:
            firms = bundle / mod.FIRMS / f'data/raw/boundaries/{base}{ext}'
            analysis = bundle / mod.ANALYSIS / f'data/geo/{base}{ext}'
            assert firms.read_bytes() == analysis.read_bytes() == (source_run / f'analysis_boundaries/{base}{ext}').read_bytes()

def test_tampered_source_stops_before_publication(source_run, tmp_path):
    (source_run / 'unit_universe.csv').write_text('tampered')
    bundle = tmp_path / 'handoff'
    with pytest.raises(mod.HandoffError, match='Hash or size mismatch'):
        mod.build(source_run, bundle)
    assert not bundle.exists()

def test_apply_is_non_overwriting_and_preserves_land_mask(source_run, tmp_path):
    bundle = tmp_path / 'handoff'
    mod.build(source_run, bundle)
    root = tmp_path / 'copy'
    land = root / mod.FIRMS / 'data/raw/boundaries/gha_admin0.shp'
    land.parent.mkdir(parents=True)
    land.write_bytes(b'governed land mask')
    result = mod.apply(bundle, root)
    assert result['created_files'] == len(mod.MAPPING) + 1
    assert land.read_bytes() == b'governed land mask'
    assert (root / mod.PROJECT_MANIFEST).exists()
    with pytest.raises(mod.HandoffError, match='already exists'):
        mod.apply(bundle, root)
    assert land.read_bytes() == b'governed land mask'

def test_one_collision_blocks_every_file_before_copy(source_run, tmp_path):
    bundle = tmp_path / 'handoff'
    mod.build(source_run, bundle)
    root = tmp_path / 'copy'
    existing = root / mod.MAPPING['analysis_boundaries/acz.shp']
    existing.parent.mkdir(parents=True)
    existing.write_bytes(b'old')
    with pytest.raises(mod.HandoffError, match='already exists'):
        mod.apply(bundle, root)
    assert existing.read_bytes() == b'old'
    assert not (root / mod.MAPPING['unit_universe.csv']).exists()

def test_altered_bundle_is_rejected_before_apply(source_run, tmp_path):
    bundle = tmp_path / 'handoff'
    mod.build(source_run, bundle)
    (bundle / mod.MAPPING['unit_universe.csv']).write_text('altered')
    root = tmp_path / 'copy'
    (root / 'RP1_Project').mkdir(parents=True)
    with pytest.raises(mod.HandoffError, match='Hash or size mismatch'):
        mod.apply(bundle, root)
    assert not (root / mod.PROJECT_MANIFEST).exists()


def test_bundle_may_be_kept_within_separate_project_output_directory(source_run, tmp_path):
    root = tmp_path / 'copy'
    (root / 'RP1_Project').mkdir(parents=True)
    bundle = root / 'out/handoffs/example'
    mod.build(source_run, bundle)
    assert mod.apply(bundle, root)['created_files'] == len(mod.MAPPING) + 1
    assert (root / mod.PROJECT_MANIFEST).is_file()

def test_explicit_replacement_backs_up_originals_and_preserves_land_mask(source_run, tmp_path):
    bundle = tmp_path / 'handoff'
    mod.build(source_run, bundle)
    root = tmp_path / 'copy'
    old = root / mod.MAPPING['unit_universe.csv']
    old.parent.mkdir(parents=True)
    old.write_bytes(b'original universe')
    land = root / mod.FIRMS / 'data/raw/boundaries/gha_admin0.shp'
    land.parent.mkdir(parents=True)
    land.write_bytes(b'original land')
    backup = tmp_path / 'archive'
    result = mod.apply(bundle, root, replace=True, backup_arg=backup)
    assert result['previously_existing_files'] == 1
    assert (backup / mod.MAPPING['unit_universe.csv']).read_bytes() == b'original universe'
    assert old.read_bytes() == (bundle / mod.MAPPING['unit_universe.csv']).read_bytes()
    assert land.read_bytes() == b'original land'
    snapshot = json.loads((backup / 'backup_manifest.json').read_text())
    assert mod.MAPPING['unit_universe.csv'] in snapshot['original_files']
    assert mod.MAPPING['analysis_boundaries/acz.shp'] in snapshot['originally_absent']

def test_replace_rejects_existing_backup_before_mutation(source_run, tmp_path):
    bundle = tmp_path / 'handoff'; mod.build(source_run, bundle)
    root = tmp_path / 'copy'; old = root / mod.MAPPING['unit_universe.csv']
    old.parent.mkdir(parents=True); old.write_bytes(b'old')
    backup = tmp_path / 'archive'; backup.mkdir()
    with pytest.raises(mod.HandoffError, match='Backup directory already exists'):
        mod.apply(bundle, root, replace=True, backup_arg=backup)
    assert old.read_bytes() == b'old'
    assert not (root / mod.PROJECT_MANIFEST).exists()

def test_replace_requires_explicit_backup(source_run, tmp_path):
    bundle = tmp_path / 'handoff'; mod.build(source_run, bundle)
    root = tmp_path / 'copy'; (root / 'RP1_Project').mkdir(parents=True)
    with pytest.raises(mod.HandoffError, match='requires --replace'):
        mod.apply(bundle, root, replace=True)

def test_replacement_failure_rolls_back_created_and_replaced_files(source_run, tmp_path, monkeypatch):
    bundle = tmp_path / 'handoff'; mod.build(source_run, bundle)
    root = tmp_path / 'copy'; original_paths = list(mod.MAPPING.values())[:2]
    for relative in original_paths:
        path = root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text('historical ' + relative)
    original_replace = mod.os.replace
    state = {'n': 0}
    def fail_once(src, dest):
        state['n'] += 1
        if state['n'] == 3:
            raise OSError('simulated interruption')
        return original_replace(src, dest)
    monkeypatch.setattr(mod.os, 'replace', fail_once)
    backup = tmp_path / 'archive'
    with pytest.raises(OSError, match='simulated interruption'):
        mod.apply(bundle, root, replace=True, backup_arg=backup)
    for relative in original_paths:
        assert (root / relative).read_text() == 'historical ' + relative
    assert (backup / 'backup_manifest.json').is_file()
    assert not (root / mod.PROJECT_MANIFEST).exists()

@pytest.fixture
def spatial_source_run(tmp_path):
    import geopandas as gpd
    from shapely.geometry import box
    run = tmp_path / 'spatial_run'
    (run / 'boundaries').mkdir(parents=True)
    (run / 'analysis_boundaries').mkdir()
    (run / 'contract').mkdir()
    (run / 'qa').mkdir()
    (run / 'crosswalks').mkdir()
    units = [
        'unit_type,level,unit_id,unit_code,unit_name,parent_level,parent_id,parent_code,parent_name,area_sqkm',
        'zone,acz,z,Z,ZONE,,,,,1',
        'district,district,a,,ALPHA,acz,z,Z,ZONE,1',
        'district,district,b,,BETA,acz,z,Z,ZONE,1',
    ]
    (run / 'unit_universe.csv').write_text('\n'.join(units) + '\n')
    walk = run / 'crosswalks/district_to_acz_max_overlap.csv'
    walk.write_text('district_id,zone_id,zone_code,zone_name,original_district_area_sq_km,dominant_overlap_area_sq_km,dominant_overlap_share,assignment_method,working_crs\na,z,Z,ZONE,1,1,1,maximum,EPSG:32630\nb,z,Z,ZONE,1,1,1,maximum,EPSG:32630\n')
    fingerprint = {'districts':{'bundle_sha256':'a'*64}, 'zones':{'bundle_sha256':'b'*64}}
    (run / 'inputs_fingerprint.json').write_text(json.dumps(fingerprint))
    provenance = {'schema':'district-to-zone-crosswalk-provenance-v1','crosswalk': {'sha256': mod.sha256(walk),'rows':2}, 'source_district_geometry':fingerprint['districts'],'source_acz_geometry':fingerprint['zones'],'implementation_identity':'test','analysis_crs':'EPSG:32630'}
    (run / 'crosswalks/district_to_acz_max_overlap.provenance.json').write_text(json.dumps(provenance))
    (run / 'qa/qa_summary.json').write_text(json.dumps({
        'status': 'WARN',
        'checks': {'handoff_eligible': True, 'area_tolerance_m2': 0.0001},
        'warnings': ['example'],
    }))
    (run / 'contract/stage1_contract_manifest.json').write_text(json.dumps({'run_id':'synthetic','handoff_eligible':True,'geometry_crs':'EPSG:4326','analysis_handoff':{'crs':'EPSG:32630','exact_parent_district_union':True,'districts_relative_path':'analysis_boundaries/districts_within_acz.shp','zones_relative_path':'analysis_boundaries/acz.shp'}}))
    d = gpd.GeoDataFrame({'dist_id':['a','b'],'dist_name':['ALPHA','BETA'],'zone_id':['z','z'],'zone_name':['ZONE','ZONE'],'zone_code':['Z','Z'],'ovl_share':[1.,1.]}, geometry=[box(-1,6,-.9,6.1),box(-.9,6,-.8,6.1)], crs=4326)
    for group, district in [('boundaries',d),('analysis_boundaries',d.to_crs(32630))]:
        district.to_file(run / group / 'districts_within_acz.shp',index=False)
        z=gpd.GeoDataFrame({'zone_id':['z'],'zone_name':['ZONE'],'zone_code':['Z']},geometry=[district.geometry.union_all()],crs=district.crs)
        z.to_file(run / group / 'acz.shp',index=False)
    return run

def test_real_spatial_identity_and_crs_hierarchy(spatial_source_run):
    data=mod.check_identities(spatial_source_run)
    assert data['districts']==2 and data['zones']==1
    assert data['layers']['analysis_boundaries']['crs']=='EPSG:32630'

def test_rejects_internally_consistent_but_spatially_shifted_projected_layers(spatial_source_run):
    import geopandas as gpd
    for name in ('acz','districts_within_acz'):
        path=spatial_source_run / 'analysis_boundaries' / (name+'.shp')
        layer=gpd.read_file(path)
        layer.geometry=layer.geometry.translate(xoff=10)
        layer.to_file(path,index=False)
    with pytest.raises(mod.HandoffError,match='Projected district does not match source coordinates'):
        mod.check_identities(spatial_source_run)


def test_rejects_overlapping_projected_districts_even_with_an_exact_parent_union(spatial_source_run):
    import geopandas as gpd
    from shapely.geometry import Polygon

    native_path = spatial_source_run / 'boundaries/districts_within_acz.shp'
    native = gpd.read_file(native_path)
    native.loc[0, 'geometry'] = Polygon([
        (-1, 6), (-.9, 6), (-.9, 6.05), (-.9, 6.1), (-1, 6.1), (-1, 6),
    ])
    projected = native.to_crs(32630)
    assert native.geometry.iloc[0].touches(native.geometry.iloc[1])
    assert projected.geometry.iloc[0].intersection(projected.geometry.iloc[1]).area > 1
    for group, districts in [('boundaries', native), ('analysis_boundaries', projected)]:
        directory = spatial_source_run / group
        districts.to_file(directory / 'districts_within_acz.shp', index=False)
        zones = gpd.read_file(directory / 'acz.shp')
        zones.loc[0, 'geometry'] = districts.geometry.union_all()
        zones.to_file(directory / 'acz.shp', index=False)
    with pytest.raises(mod.HandoffError, match='Analysis district overlaps'):
        mod.check_identities(spatial_source_run)


def test_real_projected_bundle_delivers_identical_crs_to_both_consumers(spatial_source_run, tmp_path):
    import geopandas as gpd
    files = {path.relative_to(spatial_source_run).as_posix(): {'bytes': path.stat().st_size, 'sha256': mod.sha256(path)}
             for path in spatial_source_run.rglob('*') if path.is_file()}
    (spatial_source_run / 'outputs_manifest.json').write_text(json.dumps({
        'schema': 'geo-data-output-manifest-v1', 'run_id': 'synthetic', 'files': files}))
    bundle = tmp_path / 'projected_handoff'
    manifest = mod.build(spatial_source_run, bundle)
    mod.verify_projected_bundle(bundle, manifest)
    project = tmp_path / 'consumer'
    (project / 'RP1_Project').mkdir(parents=True)
    mod.apply(bundle, project)
    for base in ('acz', 'districts_within_acz'):
        left = project / mod.FIRMS / f'data/raw/boundaries/{base}.shp'
        right = project / mod.ANALYSIS / f'data/geo/{base}.shp'
        assert gpd.read_file(left).crs.to_epsg() == gpd.read_file(right).crs.to_epsg() == 32630


def test_apply_respects_schema_declared_source_paths(source_run, tmp_path):
    import shutil
    bundle = tmp_path / 'declared_layout_bundle'
    records = {}
    for target, relative in mod.handoff_sources('rp1-geo-handoff-v1').items():
        path = bundle / target
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source_run / relative, path)
        records[target] = {'bytes': path.stat().st_size, 'sha256': mod.sha256(path), 'source_relative_path': relative}
    (bundle / mod.BUNDLE_MANIFEST).write_text(json.dumps({
        'schema': 'rp1-geo-handoff-v1', 'source_run': {'run_id': 'synthetic_layout'}, 'files': records}))
    project = tmp_path / 'layout_consumer'
    (project / 'RP1_Project').mkdir(parents=True)
    mod.apply(bundle, project)
    target = project / mod.FIRMS / 'data/raw/boundaries/acz.shp'
    assert target.read_bytes() == (source_run / 'boundaries/acz.shp').read_bytes()
