from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scientific_input_reference import paired_input_reference, panel_input_reference

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
    manifest_path = ROOT / "data/raw/fire_panel_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    handoff = manifest["analysis_handoff"]
    original_path = manifest_path.with_name(handoff["original_manifest_file"])
    assert _sha(original_path) == handoff["original_manifest_sha256"]
    original = json.loads(original_path.read_text(encoding="utf-8"))
    families = {record["family_name"]: record for record in manifest["families"]}
    original_families = {record["family_name"]: record for record in original["families"]}

    support_record = manifest["outputs"]["ba_observation_support"]
    support_path = PROJECT.parent / support_record["staged_path"]
    assert _sha(support_path) == support_record["sha256"]
    evidence = pd.read_csv(
        support_path, usecols=["family", "level", "source_path", "source_sha256", "source_row"]
    )
    ba2012 = evidence.loc[evidence["family"].eq("ba2012")]
    for level in ("district", "acz"):
        name = f"ba2012_{level}_base"
        family = families[name]
        assert family == original_families[name]
        assert family["support_start_yyyymm"] == 201201
        assert family["support_end_yyyymm"] == 202412
        rows_by_path = ba2012.loc[ba2012["level"].eq(level)].groupby("source_path")
        expected_paths = {item["source_path"] for item in family["files"]}
        assert len(expected_paths) == len(family["files"])
        assert set(rows_by_path.groups) == expected_paths
        for item in family["files"]:
            rows = rows_by_path.get_group(item["source_path"])
            assert rows["source_sha256"].eq(item["sha256"]).all()
            assert sorted(rows["source_row"]) == list(range(1, item["row_count"] + 1))

            # The portable companion preserves row-level provenance without upstream CSV bytes.
            upstream_path = PROJECT.parent / item["staged_path"]
            if upstream_path.exists():
                assert _sha(upstream_path) == item["sha256"]


def test_consolidated_key_and_merge_support_authorities_are_consistent():
    key=pd.read_csv(ROOT/'data/raw/fire_panel_key_audit.csv')
    district=key.loc[key['level'].eq('district')].iloc[0]
    assert int(district['expected_rows'])==len(panel_input_reference())
    assert int(district['actual_rows'])==len(panel_input_reference())
    assert int(district['unique_keys'])==len(panel_input_reference())
    assert int(district['duplicate_key_rows'])==0
    assert bool(district['passes_key_audit'])
    merge=json.loads((ROOT/'data/raw/fire_panel_merge_summary.json').read_text())
    assert merge['district']['ba2012_supported_rows']==int(panel_input_reference().ba2012_supported_flag.eq(1).sum())
    assert merge['district']['ba2012_structural_missing_rows']==int(panel_input_reference().ba2012_structural_missing_flag.eq(1).sum())
    assert merge['acz']['ba2012_supported_rows']==int(panel_input_reference('acz_monthly').ba2012_supported_flag.eq(1).sum())
    assert merge['acz']['ba2012_structural_missing_rows']==int(panel_input_reference('acz_monthly').ba2012_structural_missing_flag.eq(1).sum())


def test_governed_paired_mcd64a1_zeroes_are_supported_not_structural_missing():
    paths=ProjectPaths(ROOT)
    bundle=load_configuration_bundle(ROOT/'config')
    data=load_data_authorities(paths,bundle.data_schema)
    summary=validate_data_authorities(data,bundle.analysis,bundle.data_schema)
    paired=build_paired_overlap_panel(data.district_panel,bundle.analysis,bundle.methods,summary.paired_mask)
    audit=rq3_mcd64a1_support_audit(paired, observation_support=data.ba_observation_support)
    reference = paired_input_reference()
    assert int(audit['rows'].sum())==len(reference)
    assert int(audit['supported_rows'].sum())==int(reference.ba2012_supported_flag.eq(1).sum())
    assert int(audit['structural_missing_rows'].sum())==int(reference.ba2012_structural_missing_flag.eq(1).sum())
    assert int(audit['numeric_missing_rows'].sum())==int(reference.modis_ba_km2_ba2012.isna().sum())
    for month in range(1, 13):
        observed = audit.loc[audit.month.eq(month)].iloc[0]
        source = reference.loc[reference.month.eq(month), 'modis_ba_km2_ba2012']
        assert int(observed.zero_rows) == int(source.eq(0).sum())
        assert int(observed.positive_rows) == int(source.gt(0).sum())
