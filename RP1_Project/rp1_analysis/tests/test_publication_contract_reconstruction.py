from __future__ import annotations
import hashlib, json
from pathlib import Path
import pandas as pd
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.publication_sources import load_publication_authorities

ROOT=Path(__file__).resolve().parents[1]; CONFIG=ROOT/'config'
def _bundle(): return load_configuration_bundle(CONFIG)
def _sources(): return load_publication_authorities(paths=ProjectPaths(ROOT))

def test_exact_publication_identity_and_counts() -> None:
    b=_bundle(); main_tables=[x for x in b.output.tables if x.role=='manuscript']; supp_tables=[x for x in b.output.tables if x.role=='supplementary']; main_fig=[x for x in b.figure.figures if x.role=='manuscript']; supp_fig=[x for x in b.figure.figures if x.role=='supplementary']
    assert [x.output_id for x in main_tables]==['T1','T2','T3']; assert [x.output_id for x in supp_tables]==['S1','S2','S3','S4','S5','S6']
    assert [x.figure_id for x in main_fig]==['F2','F3','F4','F5','F6']; assert [x.figure_id for x in supp_fig]==['S1']; assert 'F1' not in {x.figure_id for x in b.figure.figures}

def test_table1_has_five_acz_rows_and_no_repeated_global_moran() -> None:
    f=_sources()['table1_acz_summary']; assert len(f)==5 and f['parent_code'].nunique()==5; assert not any('moran' in c.lower() for c in f.columns)

def test_table2_has_exact_three_continuous_model_rows() -> None:
    f=_sources()['table2_rq3_model']; assert len(f)==3; assert f['term'].tolist()==['log2_viirs_det_primary','log2_viirs_frp_mean_mw','log2_modis_burnable_km2_union_ba2012']; assert f['predictor_role'].tolist()==['focal','focal','adjustment']

def test_f2_semantic_projection_has_only_two_rate_panels() -> None:
    b=_bundle(); spec=next(x for x in b.figure.figures if x.figure_id=='F2'); assert spec.source_attribute=='long_run_spatial_rate_presentation_source'
    f=_sources()[spec.source_attribute]; assert list(dict.fromkeys(f['panel'].astype(str)))==['direct_acz_long_run_rate','district_long_run_rate']; assert len(f)==265

def test_f4_uses_exact_rq2_publication_fields_and_frozen_order() -> None:
    b=_bundle(); spec=next(x for x in b.figure.figures if x.figure_id=='F4'); assert spec.source_attribute=='annual_trend_source'
    assert tuple(spec.renderer_options['panel_order'])==('COASTAL ZONE','FOREST ZONE','GUINEA SAVANNAH','SUDAN SAVANNAH','TRANSITION ZONE')
    f=_sources()[spec.source_attribute]; assert len(f)==120 and f['parent_code'].nunique()==5 and f.groupby('parent_code',observed=True)['year'].nunique().eq(24).all()

def test_f5_focal_panel_has_exactly_two_effects() -> None:
    f=_sources()['cross_product_observability_presentation_source']; focal=f.loc[f['panel'].eq('focal_adjusted_associations')]
    assert len(focal)==2; assert focal['term'].tolist()==['VIIRS detection count (per doubling)','Mean FRP (per doubling)']; assert not focal['term'].str.contains('burnable',case=False,na=False).any()

def test_supplement_s3_has_one_global_moran_and_local_rows() -> None:
    f=_sources()['supplement_s3_spatial']; assert (f['record_type'].astype(str)=='global_moran_national').sum()==1; local=f.loc[f['record_type'].astype(str).eq('local_moran')]; assert len(local)==250 and local['unit_id'].nunique()==250

def test_supplement_s4_is_complete_24_year_by_five_acz_authority() -> None:
    f=_sources()['supplement_s4_rq2']; assert len(f)==120 and f['parent_code'].nunique()==5 and f.groupby('parent_code',observed=True)['year'].nunique().eq(24).all()

def test_supplement_s5_contains_full_model_and_exact_probability_outputs() -> None:
    f=_sources()['supplement_s5_rq3']; assert (f['record_type'].eq('coefficient')).sum()==31; std=f.loc[f['record_type'].eq('standardised_probability')]; assert len(std)==4 and std['predictor_id'].nunique()==2

def test_publication_runtime_does_not_recompute_rq_statistics() -> None:
    source=(ROOT/'src/rp1_analysis_v1/publication.py').read_text(); assert 'build_rq1_tables' not in source and 'build_rq2_tables' not in source and 'build_rq3_tables' not in source; assert 'load_publication_authorities' in source

def test_materialised_source_manifest_is_hash_closed_and_semantic() -> None:
    mp=ROOT/'data/authorities/publication/SOURCE_MANIFEST.json'; m=json.loads(mp.read_text()); assert m['satscan_dependent_sources_materialised'] is False
    assert set(m['sources'])=={'table1_acz_summary','table2_rq3_model','supplement_s1_populations','supplement_s2_district_rq1','supplement_s3_spatial','supplement_s4_rq2','supplement_s5_rq3','long_run_spatial_rate_presentation_source','seasonality_spatial_organisation_presentation_source','annual_trend_source','cross_product_observability_presentation_source','district_seasonal_diagnostics_source'}
    for name,item in m['sources'].items():
        path=ROOT/item['path']; assert path.is_file(),name; assert hashlib.sha256(path.read_bytes()).hexdigest()==item['sha256']; f=pd.read_csv(path); assert len(f)==item['rows'] and list(f.columns)==item['columns']

def test_satscan_sources_are_not_materialised_without_genuine_results() -> None:
    s=_sources(); assert 'table3_satscan_clusters' not in s and 'supplement_s6_satscan' not in s and 'cluster_membership_source' not in s and 'cluster_recurrence_source' not in s
