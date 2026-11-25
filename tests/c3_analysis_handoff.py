"""Isolated geography/configuration fixture for the real c3 runtime input gate."""
from __future__ import annotations
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely.geometry import box
from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.integration import validate_governed_inputs
from rp1_analysis_v1.paths import ProjectPaths

ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "RP1_Project/rp1_analysis"


def module(name):
    spec=importlib.util.spec_from_file_location("isolated_c3_"+name,ANALYSIS/"scripts"/(name+".py"))
    obj=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


def complete_runtime_handoff(analysis_root, universe, end_year=2024):
    """Use actual configuration, scripts, loading and validation without fitting."""
    analysis_root=Path(analysis_root)
    shutil.copytree(ANALYSIS/"config",analysis_root/"config")
    shutil.copy2(ANALYSIS/"pyproject.toml",analysis_root/"pyproject.toml")
    units=pd.read_csv(universe,keep_default_na=False)
    zones, districts, crosswalk = [], [], []
    for index, unit in enumerate(units.loc[units.level.eq("acz")].to_dict("records")):
        geometry=box(500000+index*2500,700000,502000+index*2500,702000)
        zones.append({"zone_id":unit["unit_id"],"zone_code":unit["unit_code"],
                      "zone_name":unit["unit_name"],"geometry":geometry})
        children=units.loc[units.parent_id.eq(unit["unit_id"])]
        assert len(children)==1, "Fixture deliberately has one complete district per direct zone"
        district=children.iloc[0]
        districts.append({"dist_id":district.unit_id,"dist_name":district.unit_name,
            "zone_id":unit["unit_id"],"zone_code":unit["unit_code"],"zone_name":unit["unit_name"],
            "ovl_share":1.0,"geometry":geometry})
        crosswalk.append({"district_id":district.unit_id,"zone_id":unit["unit_id"],
            "zone_code":unit["unit_code"],"zone_name":unit["unit_name"],
            "original_district_area_sq_km":4.0,"dominant_overlap_area_sq_km":4.0,
            "dominant_overlap_share":1.0,"assignment_method":"maximum_original_polygon_overlap",
            "working_crs":"EPSG:32630"})
    geo=analysis_root/"data/geo";geo.mkdir(parents=True)
    gpd.GeoDataFrame(zones,crs="EPSG:32630").to_file(geo/"acz.shp",encoding="UTF-8")
    gpd.GeoDataFrame(districts,crs="EPSG:32630").to_file(geo/"districts_within_acz.shp",encoding="UTF-8")
    reference=analysis_root/"data/reference";reference.mkdir(parents=True)
    path=reference/"district_to_acz_max_overlap.csv"
    pd.DataFrame(crosswalk).to_csv(path,index=False)
    provenance={"schema":"district-to-zone-crosswalk-provenance-v1","analysis_crs":"EPSG:32630",
        "implementation_identity":"independent_synthetic_fixture",
        "crosswalk":{"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),"rows":len(crosswalk)}}
    for name,stem in (("source_district_geometry","districts_within_acz"),("source_acz_geometry","acz")):
        parts={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(geo.glob(stem+".*"))}
        provenance[name]={"parts":parts,"bundle_sha256":hashlib.sha256(json.dumps(parts,sort_keys=True).encode()).hexdigest()}
    (reference/"district_to_acz_max_overlap.provenance.json").write_text(json.dumps(provenance))
    (analysis_root.parent/"geo_handoff_manifest.json").write_text(json.dumps({
        "schema":"synthetic-geo-handoff","purpose":"independent source-only input validation fixture",
        "zones":len(zones),"districts":len(districts)}))
    # Full scientific windows are copied unchanged; only observed geography and
    # staged locations are configured by the actual production handoff script.
    before=load_configuration_bundle(analysis_root/"config").analysis
    result=module("configure_generated_inputs").configure(analysis_root)
    assert result["structural_start"]=="2001-01" and result["structural_end"]==f"{end_year}-12"
    after=load_configuration_bundle(analysis_root/"config").analysis
    assert after.study['temporal_windows']['long_run'] == {'start': '2001-01', 'end': f'{end_year}-12'}
    assert after.study['temporal_windows']['overlap_monthly'] == {'start': '2012-02', 'end': f'{end_year}-12'}
    assert after.study['temporal_windows']['overlap_complete_years'] == {'start': 2013, 'end': end_year}
    expected_questions = dict(before.research_questions)
    expected_questions['rq2'] = dict(expected_questions['rq2'], expected_n_per_series=end_year-2001+1)
    assert after.research_questions == expected_questions
    docs=analysis_root/"docs";docs.mkdir()
    (docs/"Data_Schema_Contract.md").write_text(module("render_data_schema_contract").render(analysis_root))
    shutil.copy2(ANALYSIS/"docs/Data_Contract.md",docs/"Data_Contract.md")
    module("render_data_contract_roles").update_document(analysis_root,check=False)
    subprocess.run([sys.executable,str(ANALYSIS/"scripts/regenerate_data_provenance.py"),
                    "--subproject-root",str(analysis_root)],check=True,capture_output=True,text=True)
    bundle=load_configuration_bundle(analysis_root/"config")
    report=validate_governed_inputs(ProjectPaths(analysis_root),bundle=bundle)
    assert report["status"]=="PASS" and report["canonical_input_identity"]=="MATCH"
    assert report["governed_file_count"]==18
    assert len(report["current_input_identities"])==18
    assert sum(row["rows"] for row in report["c3_evidence_summary"]) == 120*((end_year-2001+1)+(end_year-2012+1))
    assert sum(row["withheld_rows"] for row in report["rq3_mcd64a1_support_by_month"]) == (end_year-2012+1)*len(districts)
    assert report["populations"]["DISTRICT_UNITS"]==5
    assert report["populations"]["PAIRED_DISTRICTS"]==0
    assert report["populations"]["LONG_RUN_DISTRICTS"]==5
    return report

