"""Independent c3 evidence cases; no national/generated inputs are required."""
from __future__ import annotations
import hashlib
import numpy as np
import pandas as pd
from rp1_ba_contracts.c3 import FIELDS, GRID, METHOD, POLICY, SCHEMA
from rp1_analysis_v1.ba_support import BASE, EVIDENCE_SCHEMA, PRIMARY_FIELDS


def row(level="district", family="ba2012", month=1, kind="zero"):
    r = {name: "0" for name in FIELDS}
    start = 2001 if family == "ba2001" else 2012
    r.update(
        run_id=f"source_{family}_{month}", schema_version=SCHEMA, level=level,
        unit_id="coastal_zone" if level == "acz" else "district_1",
        unit_code="CZ" if level == "acz" else "D1",
        unit_name="COASTAL ZONE" if level == "acz" else "District One",
        parent_level="" if level == "acz" else "acz",
        parent_id="" if level == "acz" else "coastal_zone",
        parent_code="" if level == "acz" else "CZ",
        parent_name="" if level == "acz" else "COASTAL ZONE",
        yyyymm=str(202400 + month), year="2024", month=str(month),
        modis_ba_km2="0", modis_burned_pixel_count="0", modis_ba_any="0",
        modis_burnable_km2_union="10", modis_burnable_km2_annual="5",
        modis_burned_frac_union="0", modis_burned_frac_annual="0",
        modis_aoi_area_land_km2="20", modis_zero_union_den_flag="0",
        modis_zero_annual_den_flag="0", ba_domain=family.upper(),
        ba_domain_start_year=str(start), ba_domain_end_year="2024",
        ba_status="ADMITTED", ba_coverage_status="NO_SUPPORTED_EVIDENCE",
        ba_source_status="ADMITTED", ba_source_count="1", ba_source_index=f"2024_{month:02d}_01",
        ba_lc_source_indexes="|".join(f"lc_{year}" for year in range(start, 2025)),
        ba_product="MODIS/061/MCD64A1", ba_lc_product="MODIS/061/MCD12Q1",
        ba_boundary_asset=f"projects/synthetic/{level}", ba_ghana_asset="projects/synthetic/ghana",
        ba_grid_crs="SR-ORG:6974", ba_grid_transform=",".join(map(str, GRID)),
        ba_reducer="sum_unweighted_centroid", ba_sampled_pixel_count="100",
        ba_known_union_area_km2="10", ba_state_unsupported_km2="10",
        ba_supported_fraction="",
    )
    if kind in {"positive", "anomaly", "annual_unknown"}:
        r.update(modis_ba_km2="2", modis_burned_pixel_count="4", modis_ba_any="1",
                 modis_burned_frac_union="0.2", modis_burned_frac_annual="0.4",
                 ba_coverage_status="PARTIAL_EVIDENCE", ba_known_union_burned_km2="2",
                 ba_state_accepted_km2="2", ba_state_unsupported_km2="8",
                 ba_full_period_only_km2="2", ba_supported_area_km2="2", ba_supported_fraction="1")
    if kind == "anomaly":
        r.update(ba_status="SOURCE_PIXEL_ANOMALY", ba_anomaly_area_km2="1", ba_anomaly_pixel_count="1",
                 ba_reason_positive_special_km2="1", ba_reason_special_km2="1")
        for name in ("modis_ba_km2", "modis_burned_pixel_count", "modis_ba_any",
                     "modis_burnable_km2_union", "modis_burned_frac_union", "modis_burned_frac_annual"):
            r[name] = ""
    if kind == "annual_unknown":
        r.update(ba_annual_unknown_km2="1", modis_burnable_km2_annual="",
                 modis_burned_frac_annual="", modis_zero_annual_den_flag="")
    if kind == "zero_union":
        r.update(ba_status="ZERO_UNION_DENOMINATOR", ba_coverage_status="NO_KNOWN_UNION_PIXELS",
                 modis_burnable_km2_union="0", modis_burnable_km2_annual="0",
                 modis_burned_frac_union="", modis_burned_frac_annual="",
                 modis_zero_union_den_flag="1", modis_zero_annual_den_flag="1",
                 ba_known_union_area_km2="0", ba_state_unsupported_km2="0")
    return r


def fixture():
    rows, panels, families = [], {}, []
    kinds = ["zero", "positive", "anomaly", "annual_unknown", "zero_union"]
    for level in ("acz", "district"):
        panel = []
        for month, kind in enumerate(kinds, 1):
            target = {"unit_id": "coastal_zone" if level == "acz" else "district_1",
                      "yyyymm": 202400 + month, "year": 2024, "month": month, "ba2012_supported_flag": 1,
                      "ba2012_structural_missing_flag": 0}
            for family in ("ba2001", "ba2012"):
                source = row(level, family, month, kind)
                filename = f"rp1_ba_{level}_monthly_c3_CZ_{family.upper()}_2024_ext.csv"
                sha = hashlib.sha256(filename.encode()).hexdigest()
                rows.append({**source, "family": family, "source_path": "sources/" + filename,
                             "source_sha256": sha, "source_row": month})
                for name in PRIMARY_FIELDS:
                    target[name + "_" + family] = float(source[name]) if source[name] else np.nan
                if month == 1:
                    families.append({"source_kind": family, "level": level,
                                     "files": [{"filename": filename, "sha256": sha}]})
            panel.append(target)
        panels[level] = pd.DataFrame(panel)
    manifest = {
        "profile_id": "c3",
        "profile_contract": {"source_label":"c3", "source_schema_version":SCHEMA,
                             "quality_policy":POLICY, "method_version":METHOD},
        "ba_observation_support": {"schema_version":EVIDENCE_SCHEMA, "profile_id":"c3",
            "source_schema_version":SCHEMA,
            "quality_policy":POLICY, "method_version":METHOD,
            "sidecar_output":"ba_observation_support.csv", "source_values_preserved":True},
        "families": families, "ba_bundle":{"scope":"full"},
    }
    return pd.DataFrame(rows, columns=BASE), manifest, panels["acz"], panels["district"]

