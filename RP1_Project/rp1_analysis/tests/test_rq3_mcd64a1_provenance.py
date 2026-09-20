from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.observability import build_paired_overlap_panel
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.validation import validate_data_authorities, rq3_mcd64a1_support_audit

ROOT=ProjectPaths.discover().root
PROJECT=ROOT.parent


def _sha(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def test_ba2012_manifest_source_hashes_and_support_are_intact():
    manifest=json.loads((ROOT/'data/raw/fire_panel_manifest.json').read_text())
    families={x['family_name']:x for x in manifest['families']}
    for name in ('ba2012_district_base','ba2012_acz_base'):
        family=families[name]
        assert family['support_start_yyyymm']==201201
        assert family['support_end_yyyymm']==202412
        for item in family['files']:
            path=PROJECT.parent/item['staged_path']
            assert path.is_file()
            assert _sha(path)==item['sha256']


def test_consolidated_key_and_merge_support_authorities_are_consistent():
    key=pd.read_csv(ROOT/'data/raw/fire_panel_key_audit.csv')
    district=key.loc[key['level'].eq('district')].iloc[0]
    assert int(district['expected_rows'])==74880
    assert int(district['actual_rows'])==74880
    assert int(district['unique_keys'])==74880
    assert int(district['duplicate_key_rows'])==0
    assert bool(district['passes_key_audit'])
    merge=json.loads((ROOT/'data/raw/fire_panel_merge_summary.json').read_text())
    assert merge['district']['ba2012_supported_rows']==40560
    assert merge['district']['ba2012_structural_missing_rows']==34320
    assert merge['acz']['ba2012_supported_rows']==780
    assert merge['acz']['ba2012_structural_missing_rows']==660


def test_governed_paired_mcd64a1_zeroes_are_supported_not_structural_missing():
    paths=ProjectPaths(ROOT)
    bundle=load_configuration_bundle(ROOT/'config')
    data=load_data_authorities(paths,bundle.data_schema)
    summary=validate_data_authorities(data,bundle.analysis,bundle.data_schema)
    paired=build_paired_overlap_panel(data.district_panel,bundle.analysis,bundle.methods,summary.paired_mask)
    audit=rq3_mcd64a1_support_audit(paired)
    assert int(audit['rows'].sum())==38595
    assert int(audit['supported_rows'].sum())==38595
    assert int(audit['structural_missing_rows'].sum())==0
    assert int(audit['numeric_missing_rows'].sum())==0
    july=audit.loc[audit['month'].eq(7)].iloc[0]
    september=audit.loc[audit['month'].eq(9)].iloc[0]
    assert int(july['zero_rows'])==3237 and int(july['positive_rows'])==0
    assert int(september['zero_rows'])==3226 and int(september['positive_rows'])==11
