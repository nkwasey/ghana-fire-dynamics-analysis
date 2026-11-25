from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from rp1_analysis_v1.config import load_analysis_contract
from rp1_analysis_v1.data_io import DataAuthorities
from rp1_analysis_v1.district_support import (
    DistrictSupportError,
    _circular_block_multiplicities,
    _describe_block_sensitivity,
    _proof_district_crosswalk,
    build_district_support_diagnostics,
)
from rp1_analysis_v1.spatial_scale import (
    ANNUAL_RATE_FIELD,
    DEPARTURE_FIELD,
    PRIMARY_RATE_FIELD,
    RQ1Tables,
)
from rp1_analysis_v1.spatial_stats import build_rq1_spatial_association_authorities
from rp1_analysis_v1.validation import AnalyticalMask
from rp1_analysis_v1.variables import resolve_field_role
from shapely.geometry import box


@pytest.fixture(scope="module")
def example():
    root = Path(__file__).resolve().parents[1]
    base = load_analysis_contract(root / "config" / "analysis_contract.yml")
    mutable = base.to_dict()
    mutable["study"]["temporal_windows"]["long_run"] = {"start": "2019-01", "end": "2024-12"}
    for name in ("global", "local"):
        mutable["research_questions"]["rq1"]["spatial"][name]["permutations"] = 99
    analysis = replace(
        base, study=mutable["study"], research_questions=mutable["research_questions"]
    )
    area_col = resolve_field_role(analysis, "rq1.fixed_burnable_area")
    ba_col = resolve_field_role(analysis, "rq1.burned_area")
    cases_col = resolve_field_role(analysis, "secondary.mcd64a1_cases")
    denominator = {
        "a": 100.0,
        "b": 10.0,
        "c": 100.0001,
        "d": 60.0,
        "e": 10.000001,
        "f": 150.0,
        "zero": 0.0,
        "withheld": np.nan,
    }
    annual_rates = {
        "a": [1, 2, 3, 4, 5, 6],
        "b": [1, 1, 1, 1, 1, 1],
        "c": [0, 2, 0, 3, 0, 0],
        "d": [2, 4, 6, 8, 10, 12],
        "e": [3, 1, 4, 1, 5, 9],
        "f": [0, 0, 0, 0, 0, 0],
    }
    zones = pd.DataFrame(
        [
            {"unit_id": "zone1", "unit_code": "Z1", "unit_name": "ZONE 1", PRIMARY_RATE_FIELD: 2.5},
            {"unit_id": "zone2", "unit_code": "Z2", "unit_name": "ZONE 2", PRIMARY_RATE_FIELD: 8.0},
        ]
    )
    panel_rows, annual, district_rows, mask_rows = [], [], [], []
    for pos, (unit, area) in enumerate(denominator.items()):
        parent = zones.iloc[int(pos >= 3)]
        metadata = {
            "unit_id": unit,
            "unit_name": unit,
            "parent_id": parent["unit_id"],
            "parent_code": parent["unit_code"],
            "parent_name": parent["unit_name"],
        }
        rates = annual_rates.get(unit, [0] * 6)
        observed = unit in annual_rates
        reason = (
            ""
            if observed
            else "primary_denominator_zero_or_nonpositive"
            if unit == "zero"
            else "c3_primary_withheld"
        )
        mask_rows.append({"unit_id": unit, "eligible": observed, "exclusion_reasons": reason})
        total = 0.0
        for year, rate in enumerate(rates, start=2019):
            if observed:
                annual.append({"unit_id": unit, "year": year, ANNUAL_RATE_FIELD: float(rate)})
            mapped_area = rate * area / 100
            total += mapped_area
            for month in range(1, 13):
                panel_rows.append(
                    {
                        **metadata,
                        "yyyymm": year * 100 + month,
                        area_col: area,
                        ba_col: mapped_area if month == 1 else 0.0,
                        cases_col: rate if month == 1 else 0,
                    }
                )
        if observed:
            mean_rate = float(np.mean(rates))
            district_rows.append(
                {
                    **metadata,
                    "fixed_burnable_union_km2": area,
                    "ba_total_km2": total,
                    "acz_mean_annual_ba_rate": parent[PRIMARY_RATE_FIELD],
                    PRIMARY_RATE_FIELD: mean_rate,
                    DEPARTURE_FIELD: mean_rate - parent[PRIMARY_RATE_FIELD],
                }
            )

    panel = pd.DataFrame(panel_rows)
    panel.loc[(panel["unit_id"] == "withheld") & (panel["yyyymm"] == 201901), cases_col] = np.nan
    geometry = gpd.GeoDataFrame(
        {"dist_id": list(denominator)},
        geometry=[box(i, 0, i + 1, 1) for i in range(len(denominator))],
        crs="EPSG:32630",
    )
    district = pd.DataFrame(district_rows)
    primary = build_rq1_spatial_association_authorities(district, geometry, analysis)
    rq1 = RQ1Tables(
        acz_fire_pattern_reference=zones,
        within_acz_district_heterogeneity=pd.DataFrame(),
        district_scale_authority=district,
        spatial_autocorrelation=primary.global_table,
        reconciliation=pd.DataFrame(),
        district_annual_rates=pd.DataFrame(annual),
        local_moran_authority=primary.local_table,
    )
    authorities = DataAuthorities(
        acz_panel=pd.DataFrame(),
        district_panel=panel,
        key_audit=pd.DataFrame(),
        manifest={},
        merge_summary={},
        acz_geometry=gpd.GeoDataFrame(),
        district_geometry=geometry,
        district_to_acz_crosswalk=pd.DataFrame(),
        district_to_acz_crosswalk_provenance={},
    )
    summary = SimpleNamespace(long_run_mask=AnalyticalMask("test", pd.DataFrame(mask_rows)))
    return rq1, authorities, summary, analysis


def _run(example, **overrides):
    settings = {
        "thresholds_km2": [0, 10, 50, 100, 200],
        "block_lengths_years": [2, 3, 4],
        "primary_block_length_years": 3,
        "bootstrap_replications": 1_001,
        "seed": 123,
        "confidence_level": 0.95,
    }
    return build_district_support_diagnostics(*example, **(settings | overrides))


def test_support_keeps_zero_and_withheld_districts_distinct(example):
    result = _run(example)
    support = result.district_support.set_index("unit_id")
    assert len(support) == 8
    assert support.loc["a", "fixed_burnable_union_km2"] == 100
    assert support.loc["a", "cumulative_mapped_ba_km2"] == 21
    assert support.loc["a", "observed_years"] == 6
    assert support.loc["a", "positive_mapped_years"] == 6
    assert support.loc["a", "annual_rate_iqr"] == pytest.approx(2.5)
    assert support.loc["a", "first_period_mean_rate"] == pytest.approx(2)
    assert support.loc["a", "second_period_mean_rate"] == pytest.approx(5)
    assert support.loc["zero", "fixed_burnable_union_km2"] == 0
    assert support.loc["zero", "cumulative_mapped_ba_km2"] == 0
    assert pd.isna(support.loc["zero", "long_run_rate"])
    assert pd.isna(support.loc["withheld", "fixed_burnable_union_km2"])
    assert pd.isna(support.loc["withheld", "cumulative_mapped_ba_km2"])
    assert pd.isna(support.loc["withheld", "cumulative_burned_pixel_cases"])
    national = result.denominator_distribution.query("scope == 'national'").iloc[0]
    assert national["zero_union_districts"] == 1
    assert national["undefined_union_districts"] == 1
    assert national["baseline_eligible_districts"] == 6
    assert national["median_km2"] == 80


def test_bootstrap_uses_synchronised_calendar_blocks(example):
    # Six years divided into a partial final block of length four.
    actual = _circular_block_multiplicities(6, 4, 20, seed=12)
    starts = np.random.default_rng(12).integers(6, size=(20, 2))
    indices = [
        [(first + i) % 6 for i in range(4)] + [(second + i) % 6 for i in range(2)]
        for first, second in starts
    ]
    expected = np.array([np.bincount(row, minlength=6) for row in indices])
    np.testing.assert_array_equal(actual, expected)
    np.testing.assert_array_equal(actual.sum(axis=1), 6)
    first = _run(example).rate_variability
    second = _run(example, block_lengths_years=[4, 2, 3]).rate_variability
    pd.testing.assert_frame_equal(first, second)
    primary = first.loc[first["is_primary_block"]].set_index("unit_id")
    np.testing.assert_allclose(
        primary.loc["d", ["lower_rate", "upper_rate"]].to_numpy(dtype=float),
        2 * primary.loc["a", ["lower_rate", "upper_rate"]].to_numpy(dtype=float),
    )
    assert primary.loc["c", "interval_status"] == "sparse_mapped_history"
    assert primary.loc["f", "interval_status"] == "all_zero_mapped_history"
    assert primary.loc["f", "lower_rate"] == primary.loc["f", "upper_rate"] == 0
    assert primary.loc["b", "interval_status"] == "constant_mapped_history"


def test_material_endpoint_shift_is_scaled_by_primary_width():
    points = {
        "at_threshold": ((2.0, 6.0), (1.0, 6.0)),
        "below_threshold": ((2.0, 6.0), (2.0, 6.75)),
        "zero_width": ((3.0, 3.0), (2.5, 3.0)),
        "floating_noise": ((3.0, 3.0), (3.0, 3.0 + 1e-13)),
        "single_block": ((3.0, 3.0),),
    }
    frame = pd.DataFrame(
        [
            {
                "unit_id": unit,
                "is_primary_block": index == 0,
                "lower_rate": lower,
                "upper_rate": upper,
            }
            for unit, intervals in points.items()
            for index, (lower, upper) in enumerate(intervals)
        ]
    )
    result = _describe_block_sensitivity(frame, 0.25)
    pd.testing.assert_frame_equal(result[frame.columns], frame)
    summary = result.loc[result["is_primary_block"]].set_index("unit_id")
    assert summary.loc["at_threshold", "lower_endpoint_span_rate"] == 1.0
    assert summary.loc["below_threshold", "upper_endpoint_span_rate"] == 0.75
    assert summary.loc["at_threshold", "primary_interval_width_rate"] == 4.0
    assert summary.loc["at_threshold", "material_endpoint_shift_threshold_rate"] == 1.0
    assert summary.loc["at_threshold", "materially_block_sensitive"]
    assert not summary.loc["below_threshold", "materially_block_sensitive"]
    assert summary.loc["zero_width", "materially_block_sensitive"]
    assert not summary.loc["floating_noise", "materially_block_sensitive"]
    assert summary.loc["single_block", "blocks_compared"] == 1
    assert pd.isna(summary.loc["single_block", "materially_block_sensitive"])


def test_endpoint_metadata_is_ancillary_to_attested_intervals(example):
    default = _run(example).rate_variability
    alternative = _run(example, block_endpoint_materiality_fraction=0.5).rate_variability
    published = [
        "unit_id", "is_primary_block", "block_length_years", "lower_rate", "upper_rate",
        "interval_status", "positive_mapped_years", "interval_method", "confidence_level",
        "bootstrap_replications", "seed",
    ]
    pd.testing.assert_frame_equal(default[published], alternative[published])
    assert default["blocks_compared"].eq(3).all()
    assert default["block_endpoint_materiality_fraction"].eq(0.25).all()
    assert alternative["block_endpoint_materiality_fraction"].eq(0.5).all()
    assert default.loc[default["unit_id"].eq("f"), "materially_block_sensitive"].eq(False).all()
    one_block = _run(example, block_lengths_years=[3]).rate_variability
    assert one_block["blocks_compared"].eq(1).all()
    assert one_block["materially_block_sensitive"].isna().all()


def test_thresholds_use_unrounded_values_fixed_references_and_induced_graph(example):
    result = _run(example)
    districts = result.threshold_districts.set_index(["minimum_fixed_union_km2", "unit_id"])
    initial = districts.loc[0]
    at10 = districts.loc[10]
    at100 = districts.loc[100]
    assert not at10.loc["b", "included"]
    assert at10.loc["e", "included"]
    assert not at100.loc["a", "included"]
    assert at100.loc["c", "included"]
    assert not at10.loc["zero", "included"]
    assert at10.loc["zero", "exclusion_reason"] == "primary_denominator_zero_or_nonpositive"
    assert at10.loc["b", "exclusion_reason"] == "at_or_below_minimum_fixed_union"
    assert pd.isna(at10.loc["b", "local_class"])
    assert at10.loc["a", "local_class"] == "ISLAND"
    assert pd.isna(at10.loc["a", "local_raw_p"])
    assert pd.isna(at10.loc["a", "local_class_changed"])
    assert at10.loc["d", "district_departure"] == initial.loc["d", "district_departure"]
    assert at10.loc["a", "direct_parent_acz_rate"] == 2.5
    assert at10.loc["c", "baseline_departure_rank"] == 3
    assert at10.loc["c", "retained_baseline_departure_rank"] == 2
    assert at10.loc["c", "retained_departure_rank"] == 2
    assert at10.loc["c", "departure_rank_change_shared"] == 0
    assert at10.loc["c", "departure_rank_shift_from_screening"] == -1
    assert pd.isna(at10.loc["b", "retained_departure_rank"])
    assert pd.isna(at10.loc["b", "departure_rank_shift_from_screening"])
    assert pd.isna(at10.loc["withheld", "baseline_departure_rank"])

    totals = result.threshold_summary.set_index("minimum_fixed_union_km2")
    assert list(totals["retained_districts"]) == [6, 5, 4, 2, 0]
    assert totals.loc[0, "queen_edges"] == 5
    assert totals.loc[10, "queen_edges"] == 3
    assert totals.loc[10, "non_island_districts"] == 4
    assert totals.loc[10, "local_bh_family_size"] == 4
    assert totals.loc[10, "removed_fixed_union_km2"] == 10
    assert totals.loc[10, "removed_burned_pixel_cases"] == 6
    assert totals.loc[50, "spatial_status"] == "insufficient_non_island_districts"
    assert totals.loc[200, "non_island_districts"] == 0
    assert pd.isna(totals.loc[200, "global_morans_i"])
    primary = example[0]
    assert totals.loc[0, "global_morans_i"] == primary.spatial_autocorrelation["morans_i"].iloc[0]
    assert initial.loc["a":"f", "local_class"].equals(
        primary.local_moran_authority.set_index("unit_id")["lisa_class"].rename("local_class")
    )

    groups = result.threshold_by_acz.set_index(["minimum_fixed_union_km2", "parent_id"])
    assert groups.loc[(10, "zone1"), "district_count"] == 2
    assert groups.loc[(10, "zone1"), "district_rate_median"] == pytest.approx((3.5 + 5 / 6) / 2)
    zone = groups.loc[(10, "zone1")]
    np.testing.assert_allclose(
        zone[["departure_min", "departure_p05", "departure_median", "departure_p95",
              "departure_max"]].to_numpy(dtype=float),
        np.quantile([-5 / 3, 1], [0, 0.05, 0.5, 0.95, 1]),
    )
    assert zone["shared_departure_rank_change_count"] == 0
    assert zone["max_abs_shared_departure_rank_change"] == 0
    assert zone["screening_departure_rank_shift_count"] == 1
    assert zone["max_abs_screening_departure_rank_shift"] == 1
    assert groups.loc[(200, "zone1"), "district_count"] == 0
    assert pd.isna(groups.loc[(200, "zone1"), "district_rate_gini"])
    assert pd.isna(groups.loc[(200, "zone1"), "departure_median"])
    assert groups.loc[(200, "zone1"), "screening_departure_rank_shift_count"] == 0
    assert pd.isna(groups.loc[(200, "zone1"), "max_abs_screening_departure_rank_shift"])


def test_crosswalk_uses_proof_identity_and_stable_keys(example):
    result = _run(example)
    absent = result.proof_district_crosswalk.set_index("proof_id")
    assert absent["fixed_burnable_union_km2"].isna().all()
    assert absent.loc["D008", "proof_page"] == 43
    assert absent.loc["D198", "proof_page"] == 46
    renamed = result.threshold_districts.copy()
    renamed["unit_id"] = renamed["unit_id"].replace(
        {"b": "Sekyere_Afram_Plains_North", "a": "Adaklu"}
    )
    verified = _proof_district_crosswalk(renamed.iloc[::-1]).set_index("proof_id")
    assert verified.loc["D008", "unit_id"] == "Adaklu"
    assert verified.loc["D008", "fixed_burnable_union_km2"] == 100
    assert verified.loc["D008", "baseline_departure_rank"] == 1
    assert verified.loc["D198", "unit_id"] == "Sekyere_Afram_Plains_North"
    assert verified.loc["D198", "fixed_burnable_union_km2"] == 10
    assert verified.loc["D198", "baseline_departure_rank"] == 2


@pytest.mark.parametrize(
    "settings, message",
    [
        ({"thresholds_km2": [10]}, "start with"),
        ({"thresholds_km2": [0, 10, 10]}, "strictly increasing"),
        ({"block_lengths_years": [2, 4]}, "include the primary"),
        ({"block_lengths_years": [3, 6]}, "shorter than"),
        ({"block_endpoint_materiality_fraction": 0}, "materiality fraction"),
        ({"block_endpoint_materiality_fraction": float("nan")}, "materiality fraction"),
        ({"block_endpoint_materiality_fraction": True}, "materiality fraction"),
    ],
)
def test_invalid_sensitivity_settings_fail_closed(example, settings, message):
    with pytest.raises(DistrictSupportError, match=message):
        _run(example, **settings)


def test_missing_annual_district_year_fails_closed(example):
    rq1, *rest = example
    missing = replace(rq1, district_annual_rates=rq1.district_annual_rates.iloc[1:])
    with pytest.raises(DistrictSupportError, match="Annual rates do not reconcile"):
        _run((missing, *rest))
