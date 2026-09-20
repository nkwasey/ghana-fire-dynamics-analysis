from __future__ import annotations

import json
import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import yaml
from shapely.geometry import box

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.data_io import load_data_authorities
from rp1_analysis_v1.inequality import gini_coefficient
from rp1_analysis_v1.paths import ProjectPaths
from rp1_analysis_v1.seasonality import (
    circular_mean_direction,
    circular_mean_month,
    mean_resultant_length,
    summarise_seasonality,
)
from rp1_analysis_v1.spatial_scale import (
    PRIMARY_RATE_FIELD,
    acz_long_run_burned_area_summary,
    build_district_scale_authority,
    build_rq1_tables,
    cross_scale_reconciliation,
    district_long_run_burned_area_summary,
    within_acz_absolute_departure,
    within_acz_dispersion,
)
from rp1_analysis_v1.spatial_stats import (
    SpatialStatsError,
    build_rq1_spatial_association_authorities,
    global_morans_i,
    local_morans_i,
    queen_contiguity_weights,
)
from rp1_analysis_v1.validation import validate_data_authorities

SUBPROJECT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = SUBPROJECT / "tests/fixtures/reference_methods"


@pytest.fixture(scope="module")
def governed():
    paths = ProjectPaths.discover(SUBPROJECT)
    bundle = load_configuration_bundle(paths.root / "config")
    authorities = load_data_authorities(paths, bundle.data_schema)
    summary = validate_data_authorities(authorities, bundle.analysis, bundle.data_schema)
    return paths, bundle, authorities, summary


@pytest.fixture(scope="module")
def rq1(governed):
    _, bundle, authorities, summary = governed
    return build_rq1_tables(authorities, summary, bundle.analysis)


def _grid_geometry(rows: int, cols: int, *, isolated: bool = False) -> gpd.GeoDataFrame:
    records: list[dict[str, object]] = []
    for r in range(rows):
        for c in range(cols):
            records.append({"dist_id": f"r{r}c{c}", "geometry": box(c, r, c + 1, r + 1)})
    if isolated:
        records.append({"dist_id": "island", "geometry": box(100, 100, 101, 101)})
    return gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:32630")


def _synthetic_cases() -> dict:
    return json.loads((FIXTURE_ROOT / "rq1_synthetic_cases.json").read_text(encoding="utf-8"))


def _local_moran_kwargs() -> dict[str, object]:
    bundle = load_configuration_bundle(SUBPROJECT / "config")
    local = bundle.analysis.research_questions["rq1"]["spatial"]["local"]
    return {
        "family_name": str(local["multiplicity_family"]),
        "upper_tail_comparison": str(local["upper_tail_comparison"]),
        "tie_allocation": str(local["tie_allocation"]),
        "multiply_smaller_tail_by_two": bool(local["multiply_smaller_tail_by_two"]),
    }


def test_rq1_configuration_is_protocol_authority(governed) -> None:
    _, bundle, _, _ = governed
    rq = bundle.analysis.research_questions["rq1"]
    assert rq["annual_rate"]["denominator_support"] == "fixed_ba2001_burnable_union"
    assert tuple(rq["within_acz"]["summaries"]) == ("median", "iqr")
    assert rq["within_acz"]["concentration_method"] == "gini_coefficient"
    assert rq["within_acz"]["metric"] == "district_long_run_rate"
    assert rq["district_departure"]["method"] == "within_acz_rate_difference"
    assert rq["district_departure"]["standardisation"] == "none"
    assert rq["seasonality"]["method"] == "circular_mean_resultant"
    spatial = rq["spatial"]
    assert spatial["weights"]["method"] == "queen_contiguity"
    assert spatial["weights"]["transform"] == "row_standardised"
    assert spatial["weights"]["island_policy"] == "exclude_from_inference"
    assert spatial["global"]["permutations"] == 9999
    assert spatial["local"]["permutations"] == 9999
    assert spatial["local"]["multiplicity_method"] == "benjamini_hochberg"
    assert bundle.analysis.reproducibility["alpha"] == pytest.approx(0.05)
    assert "annual_burnable_area" not in bundle.analysis.field_roles["rq1"]


def test_real_rq1_population_and_fixed_rate(governed) -> None:
    _, bundle, authorities, summary = governed
    acz = acz_long_run_burned_area_summary(authorities.acz_panel, bundle.analysis)
    district = district_long_run_burned_area_summary(
        authorities.district_panel, bundle.analysis, summary.long_run_mask
    )
    assert (len(acz), len(district)) == (5, 250)
    assert acz["n_months"].eq(288).all() and district["n_months"].eq(288).all()
    assert acz["n_years"].eq(24).all() and district["n_years"].eq(24).all()
    coastal_source = authorities.acz_panel.loc[authorities.acz_panel["unit_id"].eq("coastal_zone")]
    coastal = acz.set_index("unit_id").loc["coastal_zone"]
    total = float(coastal_source["modis_ba_km2_ba2001"].sum())
    denominator = float(coastal_source["modis_burnable_km2_union_ba2001"].iloc[0])
    scale = float(bundle.analysis.research_questions["rq1"]["annual_rate"]["scale_per_km2"])
    assert coastal[PRIMARY_RATE_FIELD] == pytest.approx(scale * (total / 24.0) / denominator)


def test_cross_scale_reconciliation_is_rq1_fixed_support_only(governed) -> None:
    _, bundle, authorities, _ = governed
    result = cross_scale_reconciliation(authorities.district_panel, authorities.acz_panel, bundle.analysis)
    assert set(result["field"]) == {
        "modis_ba_km2_ba2001",
        "modis_burnable_km2_union_ba2001",
    }
    assert result["passed"].all()


def test_raw_within_acz_departure_is_not_standardised() -> None:
    district = pd.DataFrame(
        {"unit_id": ["a", "b"], "parent_id": ["z", "z"], "parent_code": ["Z", "Z"], PRIMARY_RATE_FIELD: [0.0, 2.0]}
    )
    acz = pd.DataFrame({"unit_id": ["z"], PRIMARY_RATE_FIELD: [1.5]})
    result = within_acz_absolute_departure(district, acz).set_index("unit_id")
    assert result.loc["a", "within_acz_absolute_departure"] == pytest.approx(-1.5)
    assert result.loc["b", "within_acz_absolute_departure"] == pytest.approx(0.5)
    assert not any("standard" in col.casefold() or "d_star" in col.casefold() for col in result.columns)


def test_median_iqr_and_gini_are_protocol_summaries() -> None:
    district = pd.DataFrame(
        {
            "parent_id": ["z"] * 4,
            "parent_code": ["Z"] * 4,
            "parent_name": ["ZONE"] * 4,
            PRIMARY_RATE_FIELD: [0.0, 2.0, 4.0, 6.0],
            "mean_annual_ba_km2": [1.0, 2.0, 3.0, 10.0],
        }
    )
    row = within_acz_dispersion(district).iloc[0]
    assert row["district_rate_median"] == pytest.approx(3.0)
    assert row["district_rate_iqr"] == pytest.approx(3.0)
    rates = [0.0, 2.0, 4.0, 6.0]
    manual_gini = sum(abs(a - b) for a in rates for b in rates) / (2 * len(rates) * sum(rates))
    assert row["district_rate_gini"] == pytest.approx(manual_gini)
    assert not any("top_five" in c or "top_10" in c for c in row.index)


@pytest.mark.parametrize("name", ["ties", "uniform", "single_positive"])
def test_gini_synthetic_edge_cases(name: str) -> None:
    case = _synthetic_cases()["gini_cases"][name]
    assert gini_coefficient(case["values"]) == pytest.approx(case["expected"])


def test_circular_statistics_synthetic_cases_and_zero_total() -> None:
    cases = _synthetic_cases()["circular_cases"]
    jan = cases["january_only"]["shares"]
    assert circular_mean_month(jan) == pytest.approx(1.0)
    assert circular_mean_direction(jan) == pytest.approx(0.0)
    assert mean_resultant_length(jan) == pytest.approx(1.0)
    uniform = cases["uniform"]["shares"]
    assert mean_resultant_length(uniform) == pytest.approx(0.0, abs=1e-14)
    assert circular_mean_month(uniform) is None
    zero = summarise_seasonality([0.0] * 24, [m for _ in range(2) for m in range(1, 13)])
    assert zero.status == "zero_total"
    assert zero.circular_mean_month is None and zero.mean_resultant_length is None


def test_queen_grid_and_island_policy_are_fail_closed() -> None:
    weights = queen_contiguity_weights(_grid_geometry(2, 2, isolated=True))
    assert weights.islands == ("island",)
    assert set(weights.active_ids) == {"r0c0", "r0c1", "r1c0", "r1c1"}
    assert all(len(weights.neighbours[u]) == 3 for u in weights.active_ids)
    assert np.allclose(weights.row_standardised_matrix().sum(axis=1), 1.0)
    with pytest.raises(SpatialStatsError, match="islands"):
        queen_contiguity_weights(_grid_geometry(2, 2, isolated=True), island_policy="error")


def test_constant_spatial_surface_fails_closed_not_fabricated() -> None:
    weights = queen_contiguity_weights(_grid_geometry(2, 2))
    global_result = global_morans_i([1.0] * 4, weights, permutations=19, random_seed=7)
    assert global_result.morans_i is None and global_result.permutation_p is None
    local = local_morans_i([1.0] * 4, weights, permutations=19, random_seed=7, alpha=0.05, **_local_moran_kwargs())
    assert local["local_morans_i"].isna().all()
    assert local["bh_q"].isna().all()
    assert set(local["lisa_class"]) == {"UNDEFINED"}


def test_spatial_synthetic_positive_and_outlier_cases_are_distinct() -> None:
    cases = _synthetic_cases()["spatial_cases"]
    # A six-cell linear chain is used so neighbourhood relations are transparent.
    records = [{"dist_id": str(i), "geometry": box(i, 0, i + 1, 1)} for i in range(6)]
    geometry = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:32630")
    weights = queen_contiguity_weights(geometry)
    positive = global_morans_i(cases["strong_positive"]["values"], weights, permutations=999, random_seed=12)
    outlier = global_morans_i(cases["spatial_outlier"]["values"], weights, permutations=999, random_seed=12)
    assert positive.morans_i is not None and positive.morans_i > 0
    assert outlier.morans_i is not None and outlier.morans_i < positive.morans_i
    local = local_morans_i(cases["spatial_outlier"]["values"], weights, permutations=999, random_seed=12, alpha=None, **_local_moran_kwargs())
    centre = local.set_index("unit_id").loc["2"]
    assert centre["z_value"] < 0 and centre["spatial_lag_z"] > 0  # raw LH spatial outlier sign pattern


def test_real_rq1_authorities_are_complete_and_protocol_clean(rq1) -> None:
    assert rq1.acz_fire_pattern_reference.shape[0] == 5
    assert rq1.within_acz_district_heterogeneity.shape[0] == 5
    assert rq1.district_scale_authority.shape[0] == 250
    assert rq1.spatial_autocorrelation.shape[0] == 1
    assert rq1.local_moran_authority.shape[0] == 250
    district_cols = " ".join(rq1.district_scale_authority.columns).casefold()
    assert "standardised" not in district_cols and "d_star" not in district_cols
    assert "annual_sensitivity" not in district_cols
    assert "district_rate_gini" in rq1.within_acz_district_heterogeneity.columns
    assert "top_five" not in " ".join(rq1.within_acz_district_heterogeneity.columns)


def test_real_moran_lisa_uses_9999_and_single_explicit_island(rq1) -> None:
    global_row = rq1.spatial_autocorrelation.iloc[0]
    assert global_row["permutations"] == 9999
    assert global_row["n_effective"] == 249
    assert global_row["island_count"] == 1
    assert global_row["island_ids"] == "Accra_Metropolis"
    local = rq1.local_moran_authority
    assert local.loc[local["diagnostic_status"].eq("ok"), "permutations"].eq(9999).all()
    island = local.loc[local["unit_id"].eq("Accra_Metropolis")].iloc[0]
    assert island["lisa_class"] == "ISLAND" and pd.isna(island["permutation_p"])
    eligible = local.loc[local["diagnostic_status"].eq("ok")]
    assert eligible["permutation_p"].notna().all() and eligible["bh_q"].notna().all()
    assert set(local["lisa_class"]).issubset({"HH", "LL", "HL", "LH", "NS", "ISLAND"})
    assert local.loc[~local["fdr_supported"].astype(bool) & ~local["lisa_class"].eq("ISLAND"), "lisa_class"].eq("NS").all()
    assert set(local.loc[local["fdr_supported"].astype(bool), "lisa_class"]).issubset({"HH", "LL", "HL", "LH"})


def test_configured_permutation_mutation_requires_no_source_edit(tmp_path: Path) -> None:
    root = tmp_path / "project"
    shutil.copytree(SUBPROJECT / "config", root / "config")
    shutil.copy2(SUBPROJECT / "pyproject.toml", root / "pyproject.toml")
    raw = yaml.safe_load((root / "config/analysis_contract.yml").read_text(encoding="utf-8"))
    raw["research_questions"]["rq1"]["spatial"]["global"]["permutations"] = 19
    raw["research_questions"]["rq1"]["spatial"]["local"]["permutations"] = 29
    (root / "config/analysis_contract.yml").write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    # Configuration can be loaded after the mutation; source code is unchanged.
    bundle = load_configuration_bundle(root / "config")
    district = pd.DataFrame(
        {
            "unit_id": ["r0c0", "r0c1", "r1c0", "r1c1"],
            "unit_name": ["A", "B", "C", "D"],
            "parent_id": ["z"] * 4,
            "parent_code": ["Z"] * 4,
            "parent_name": ["ZONE"] * 4,
            "within_acz_absolute_departure": [-2.0, -1.0, 1.0, 2.0],
        }
    )
    result = build_rq1_spatial_association_authorities(district, _grid_geometry(2, 2), bundle.analysis)
    assert result.global_table.iloc[0]["permutations"] == 19
    assert result.local_table.loc[result.local_table["diagnostic_status"].eq("ok"), "permutations"].eq(29).all()


def test_rq1_output_ownership_is_declared_in_output_contract(governed) -> None:
    _, bundle, _, _ = governed
    internal = {item.source_attribute: item for item in bundle.output.secondary_outputs}
    assert internal["district_scale_authority"].output_id == "rq1_long_run_district_authority"
    assert internal["local_moran_authority"].output_id == "rq1_local_moran_authority"
    publication = {item.output_id: item for item in bundle.output.tables}
    assert publication["S2"].rq == "RQ1"
    assert publication["S3"].rq == "RQ1"


def test_obsolete_rq1_scientific_authorities_are_absent() -> None:
    paths = [
        SUBPROJECT / "config/analysis_contract.yml",
        SUBPROJECT / "config/figure_contract.yml",
        SUBPROJECT / "config/method_authorities.yml",
        SUBPROJECT / "src/rp1_analysis_v1/spatial_scale.py",
        SUBPROJECT / "src/rp1_analysis_v1/spatial_stats.py",
        SUBPROJECT / "src/rp1_analysis_v1/publication.py",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8").casefold() for path in paths)
    assert "within_acz_standardised_departure" not in combined
    assert "rq1_denominator_comparison" not in combined
    assert "top_five_burden_share" not in combined
    assert "top_10pct_burden_share" not in combined


def test_rq1_maximum_overlap_crosswalk_provenance_is_embedded(rq1) -> None:
    district = rq1.district_scale_authority
    required = {
        "dominant_overlap_share",
        "crosswalk_sha256",
        "source_district_geometry_bundle_sha256",
        "source_acz_geometry_bundle_sha256",
        "crosswalk_analysis_crs",
        "crosswalk_implementation_identity",
    }
    assert required.issubset(district.columns)
    assert district["dominant_overlap_share"].between(0.0, 1.0, inclusive="both").all()
    assert district["crosswalk_sha256"].nunique() == 1
    assert district["crosswalk_sha256"].iloc[0] == "fb42b79ca19ab2a620cac7484c4d92c785374d39b78c52c18618be18e35772d0"
    assert district["crosswalk_analysis_crs"].eq("EPSG:32630").all()


def test_rq1_contract_facing_source_authorities_are_complete(rq1) -> None:
    assert rq1.acz_annual_rates.shape[0] == 120
    assert rq1.district_annual_rates.shape[0] == 6000
    assert rq1.district_annual_rates["fixed_burnable_union_km2"].gt(0).all()
    assert rq1.district_metrics_source.shape[0] == 250
    assert set(rq1.spatial_support_source["panel"]) == {
        "spatial_supports", "direct_acz_long_run_rate", "district_long_run_rate"
    }
    assert rq1.spatial_support_source["panel"].value_counts().to_dict() == {
        "spatial_supports": 260,
        "district_long_run_rate": 250,
        "direct_acz_long_run_rate": 5,
    }
    assert set(rq1.seasonality_spatial_organisation_source["panel"]) == {"acz_seasonality", "district_departure", "local_moran"}
    assert (rq1.spatial_statistics_authority["record_type"] == "global_moran_national").sum() == 1
    assert (rq1.spatial_statistics_authority["record_type"] == "local_moran").sum() == 250


def test_rq1_realised_metadata_records_population_and_spatial_parameters(rq1) -> None:
    meta = rq1.rq1_realised_run_metadata
    assert meta["population"] == {
        "acz_units": 5,
        "district_units": 250,
        "district_months": 72000,
        "years": 24,
        "climatology_months": 12,
    }
    spatial = meta["spatial"]
    assert spatial["candidate_units"] == 250
    assert spatial["non_island_units"] == 249
    assert spatial["island_count"] == 1
    assert spatial["island_ids"] == ["Accra_Metropolis"]
    assert spatial["global_permutations"] == spatial["local_permutations"] == 9999
    assert spatial["local_bh_family_size"] == 249
