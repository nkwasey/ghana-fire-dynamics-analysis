from __future__ import annotations

import hashlib
from pathlib import Path
from io import BytesIO

import pandas as pd
from PIL import Image
from pypdf import PdfReader
import pytest

from rp1_analysis_v1.config import load_configuration_bundle, satscan_parameters
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.mapping import cluster_recurrence_maps_grid, prepare_geography
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.style import PublicationStyle
from rp1_analysis_v1.publication_sources import build_satscan_publication_sources
from rp1_analysis_v1.satscan_io import ParsedSaTScanResults, parse_cluster_file, parse_membership_file
from rp1_analysis_v1.secondary_clusters import build_location_authority, load_scan_scenarios
from rp1_analysis_v1.validation import validate_data_authorities

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests/fixtures/reference_methods/satscan"


def _objects(tmp_path: Path):
    paths = ProjectPaths(ROOT)
    bundle = load_configuration_bundle(ROOT / "config")
    authorities = load_data_authorities(paths, bundle.data_schema)
    summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    params = satscan_parameters(bundle.analysis)
    location = build_location_authority(
        authorities.district_geometry,
        coordinate_crs=str(params.coordinate_crs),
        anchor_method=str(params.coordinate_anchor_method),
    )
    scenarios = list(load_scan_scenarios(bundle.analysis))
    clusters = parse_cluster_file(FIXTURE / "known_good.col.txt", alpha=0.05)
    membership = parse_membership_file(FIXTURE / "known_good.gis.txt", alpha=0.05)
    # Remap the neutral publication fixture to two districts eligible in both governed populations.
    clusters = clusters.copy(); clusters["centroid_location_id"] = "4"
    membership = membership.copy(); membership["location_id"] = ["4", "5"]
    parsed = {
        scenario.scenario_id: ParsedSaTScanResults(
            scenario_id=scenario.scenario_id,
            model=scenario.model,
            clusters=clusters.copy(),
            membership=membership.copy(),
            provenance={"fixture": True},
        )
        for scenario in scenarios
    }
    run_rows = []
    for scenario in scenarios:
        prm = tmp_path / f"{scenario.scenario_id}.prm"
        prm.write_text(
            "AnalysisType=4\n"
            + ("ModelType=0\nPopulationFile=x.pop\n" if scenario.requires_population else "ModelType=2\nPopulationFile=\n")
            + "MaxSpatialSizeInPopulationAtRisk=50\nMaxTemporalSize=12\nMonteCarloReps=999\n"
            + "ReportHierarchicalClusters=y\nReportGiniClusters=n\n",
            encoding="utf-8",
        )
        digest = hashlib.sha256(prm.read_bytes()).hexdigest()
        run_rows.append({
            "model_id": scenario.scenario_id,
            "prm_path": prm.name,
            "prm_sha256": digest,
            "case_path": f"{scenario.scenario_id}.cas",
            "case_sha256": "a" * 64,
            "coordinate_path": f"{scenario.scenario_id}.geo",
            "coordinate_sha256": "b" * 64,
            "population_path": f"{scenario.scenario_id}.pop" if scenario.requires_population else "",
            "population_sha256": "c" * 64 if scenario.requires_population else "",
        })
    return bundle, authorities, summary, location, scenarios, parsed, pd.DataFrame(run_rows)


def test_neutral_reference_fixture_builds_table3_s6_and_figure6_without_stp_rr(tmp_path: Path) -> None:
    _, _, summary, location, scenarios, parsed, registry = _objects(tmp_path)
    result = build_satscan_publication_sources(
        parsed_by_model=parsed,
        scenarios=scenarios,
        location_authority=location,
        data_contract=summary,
        run_registry=registry,
        run_dir=tmp_path,
    )
    t3 = result["table3_satscan_clusters"]
    s6 = result["supplement_s6_satscan"]
    membership = result["cluster_membership_source"]
    f6 = result["cluster_recurrence_source"]
    assert len(t3) == 2
    assert set(t3["product"]) == {"mcd64a1", "viirs"}
    stp = t3.loc[t3["product"].eq("viirs")].iloc[0]
    poisson = t3.loc[t3["product"].eq("mcd64a1")].iloc[0]
    assert pd.isna(stp["relative_risk"]) or stp["relative_risk"] == ""
    assert float(poisson["relative_risk"]) == 2.5
    assert set(s6["record_type"]) == {"cluster", "membership", "coordinate", "parameter", "file"}
    assert (s6.loc[s6["record_type"].eq("coordinate"), "anchor_method"].astype(str).isin({"polygon_centroid", "point_on_surface"})).all()
    stp_s6 = s6.loc[s6["record_type"].eq("cluster") & s6["product"].eq("viirs")]
    assert (stp_s6["relative_risk"].astype(str).eq("")).all()
    assert len(membership) == 4
    assert set(membership.columns) == {"product", "unit_id", "cluster_id"}
    assert len(f6) == 520
    assert set(f6.columns) == {
        "product", "unit_id", "significant_cluster_count", "total_significant_clusters",
        "significant_cluster_fraction", "support_status", "exclusion_reasons",
    }
    assert set(f6.loc[f6["support_status"].eq("valid_nonzero"), "significant_cluster_count"].astype(int)) == {1}
    assert set(f6.loc[f6["support_status"].eq("valid_zero"), "significant_cluster_count"].astype(int)) == {0}


def test_neutral_reference_fixture_renders_two_panel_cluster_map(tmp_path: Path) -> None:
    bundle, authorities, summary, location, scenarios, parsed, registry = _objects(tmp_path)
    result = build_satscan_publication_sources(
        parsed_by_model=parsed,
        scenarios=scenarios,
        location_authority=location,
        data_contract=summary,
        run_registry=registry,
        run_dir=tmp_path,
    )
    map_frame = result["cluster_recurrence_source"]
    assert len(map_frame) == 520
    style = PublicationStyle.from_contract(bundle.figure)
    spec = next(x for x in bundle.figure.figures if x.figure_id == "F6")
    rendered = cluster_recurrence_maps_grid(
        prepare_geography(authorities.district_geometry, authorities.acz_geometry),
        map_frame,
        product_column="product",
        panel_order=["mcd64a1", "viirs"],
        value_column="significant_cluster_count",
        panel_titles=["MCD64A1", "VIIRS"],
        cmap="cividis",
        colorbar_label="Distinct significant clusters containing district",
        colorbar_labelpad_pt=2.0,
        style=style,
        layout=bundle.figure.grid_layouts[spec.layout_role],
        figure_size=style.dimensions_for(spec.layout_role),
    )
    assert len(rendered.png) > 10_000
    assert len(rendered.pdf) > 10_000
    assert Image.open(BytesIO(rendered.png)).size == (2362, 1772)
    page = PdfReader(BytesIO(rendered.pdf)).pages[0]
    assert float(page.mediabox.width) == pytest.approx(566.9291338583, abs=1e-6)
    assert float(page.mediabox.height) == pytest.approx(425.1968503937, abs=1e-6)
    assert (rendered.width_in, rendered.height_in) == pytest.approx((20 / 2.54, 15 / 2.54), abs=1e-12)
