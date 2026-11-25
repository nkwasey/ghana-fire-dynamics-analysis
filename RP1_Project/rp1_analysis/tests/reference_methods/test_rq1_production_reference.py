from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import box

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.inference import benjamini_hochberg
from rp1_analysis_v1.inequality import gini_coefficient
from rp1_analysis_v1.seasonality import circular_mean_resultant
from rp1_analysis_v1.spatial_scale import (
    ANNUAL_RATE_FIELD,
    PRIMARY_RATE_FIELD,
    acz_long_run_burned_area_summary,
    within_acz_absolute_departure,
    within_acz_dispersion,
)
from rp1_analysis_v1.spatial_stats import (
    global_morans_i,
    local_moran_smaller_tail_plus_one,
    local_morans_i,
    queen_contiguity_weights,
)

ROOT = Path(__file__).resolve().parents[2]
ANALYSIS = load_configuration_bundle(ROOT / "config").analysis


def _monthly_panel(specs: list[tuple[str, str, str, float, float]]) -> pd.DataFrame:
    """Create 24 complete years; BA amount is an annual total placed in January."""
    rows = []
    for unit_id, code, name, annual_ba, fixed_area in specs:
        for year in range(2001, 2025):
            for month in range(1, 13):
                rows.append(
                    {
                        "unit_id": unit_id,
                        "unit_code": code,
                        "unit_name": name,
                        "yyyymm": year * 100 + month,
                        "year": year,
                        "month": month,
                        "modis_ba_km2_ba2001": float(annual_ba if month == 1 else 0.0),
                        "modis_burnable_km2_union_ba2001": float(fixed_area),
                    }
                )
    return pd.DataFrame(rows)


def _five_units(first: tuple[str, str, str, float, float], second: tuple[str, str, str, float, float] | None = None):
    specs = [first]
    if second is not None:
        specs.append(second)
    while len(specs) < 5:
        i = len(specs)
        specs.append((f"dummy_{i}", f"D{i}", f"DUMMY {i}", 1.0, 10.0))
    return _monthly_panel(specs)


def _local_kwargs() -> dict[str, object]:
    local = ANALYSIS.research_questions["rq1"]["spatial"]["local"]
    return {
        "family_name": str(local["multiplicity_family"]),
        "upper_tail_comparison": str(local["upper_tail_comparison"]),
        "tie_allocation": str(local["tie_allocation"]),
        "multiply_smaller_tail_by_two": bool(local["multiply_smaller_tail_by_two"]),
    }


def test_a_rate_denominator_changes_rate_for_same_ba() -> None:
    panel = _five_units(
        ("a", "A", "A", 10.0, 100.0),
        ("b", "B", "B", 10.0, 200.0),
    )
    out = acz_long_run_burned_area_summary(panel, ANALYSIS).set_index("unit_id")
    assert out.loc["a", PRIMARY_RATE_FIELD] == pytest.approx(10.0)
    assert out.loc["b", PRIMARY_RATE_FIELD] == pytest.approx(5.0)


def test_b_fixed_support_does_not_change_when_annual_ba_changes() -> None:
    panel = _five_units(("a", "A", "A", 1.0, 100.0))
    # Change annual BA in 2010 without touching the fixed denominator.
    panel.loc[(panel.unit_id == "a") & (panel.year == 2010) & (panel.month == 1), "modis_ba_km2_ba2001"] = 20.0
    out = acz_long_run_burned_area_summary(panel, ANALYSIS).set_index("unit_id")
    assert out.loc["a", "fixed_burnable_union_km2"] == pytest.approx(100.0)


def test_c_direct_acz_support_is_not_mean_of_district_rates() -> None:
    # District rates would be 100 and 0, whose unweighted mean is 50.  Direct
    # ACZ support is BA=1 over area=10, hence rate=10.
    panel = _five_units(("z", "Z", "ZONE", 1.0, 10.0))
    direct = acz_long_run_burned_area_summary(panel, ANALYSIS).set_index("unit_id").loc["z", PRIMARY_RATE_FIELD]
    district_rate_mean = np.mean([100.0 * 1.0 / 1.0, 100.0 * 0.0 / 9.0])
    assert direct == pytest.approx(10.0)
    assert direct != pytest.approx(district_rate_mean)


def test_d_gini_uses_rates_not_absolute_burden() -> None:
    district = pd.DataFrame(
        {
            "parent_id": ["z", "z", "z"],
            "parent_code": ["Z"] * 3,
            "parent_name": ["ZONE"] * 3,
            PRIMARY_RATE_FIELD: [10.0, 10.0, 10.0],
            "mean_annual_ba_km2": [1.0, 10.0, 100.0],
        }
    )
    row = within_acz_dispersion(district).iloc[0]
    assert row["district_rate_gini"] == pytest.approx(0.0)
    assert gini_coefficient(district["mean_annual_ba_km2"]) > 0.0


def test_e_maximum_overlap_parent_assignment_is_deterministic(tmp_path: Path) -> None:
    """Exercise the installed Stage 1 input contract without research outputs."""
    import yaml
    from geo_data_prep.pipeline import prepare

    source_geometry = box(500000.0, 1000000.0, 510000.0, 1001000.0)
    districts = gpd.GeoDataFrame(
        [{"district_id": "d", "district_name": "District D", "geometry": source_geometry}],
        geometry="geometry", crs="EPSG:32630",
    )
    zones = gpd.GeoDataFrame(
        [
            {"zone_id": "left", "zone_name": "LEFT", "zone_code": "L", "geometry": box(500000.0, 1000000.0, 504000.0, 1001000.0)},
            {"zone_id": "right", "zone_name": "RIGHT", "zone_code": "R", "geometry": box(504000.0, 1000000.0, 510000.0, 1001000.0)},
        ], geometry="geometry", crs=districts.crs,
    )
    districts.to_file(tmp_path / "districts.gpkg", driver="GPKG", index=False)
    zones.to_file(tmp_path / "zones.gpkg", driver="GPKG", index=False)
    config = {
        "project_root": ".",
        "inputs": {
            "districts": {"path": "districts.gpkg", "id_field": "district_id", "name_field": "district_name"},
            "zones": {"path": "zones.gpkg", "id_field": "zone_id", "name_field": "zone_name", "code_field": "zone_code"},
        },
        "crs": {"working": "EPSG:32630", "area": "EPSG:32630", "output": "EPSG:32630"},
        "outputs": {"root": "out", "splits": False, "plots": False},
    }
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
    first = prepare(config_path)
    second = prepare(config_path)
    assert first[2].iloc[0]["zone_id"] == "right"
    pd.testing.assert_frame_equal(first[2], second[2])
    assert float(first[2].iloc[0]["dominant_overlap_share"]) == pytest.approx(0.6)
    assert first[1].crs == districts.crs
    assert first[1].geometry.iloc[0].equals_exact(source_geometry, tolerance=0)
    assert not (tmp_path / "out").exists()


def test_f_departure_is_raw_district_minus_direct_parent_rate() -> None:
    district = pd.DataFrame({"unit_id": ["d"], "parent_id": ["z"], "parent_code": ["Z"], PRIMARY_RATE_FIELD: [17.5]})
    acz = pd.DataFrame({"unit_id": ["z"], PRIMARY_RATE_FIELD: [12.0]})
    row = within_acz_absolute_departure(district, acz).iloc[0]
    assert row["within_acz_absolute_departure"] == pytest.approx(5.5)


def test_g_circular_statistics_known_month_distributions() -> None:
    jan = [1.0] + [0.0] * 11
    r = circular_mean_resultant(jan)
    assert r.mean_month == pytest.approx(1.0)
    assert r.resultant_length == pytest.approx(1.0)
    opposite = [0.5, 0, 0, 0, 0, 0, 0.5, 0, 0, 0, 0, 0]
    r2 = circular_mean_resultant(opposite)
    assert r2.resultant_length == pytest.approx(0.0, abs=1e-14)
    assert r2.mean_month is None


def test_h_queen_includes_corner_touch_but_not_gap() -> None:
    geometry = gpd.GeoDataFrame(
        [
            {"dist_id": "a", "geometry": box(0, 0, 1, 1)},
            {"dist_id": "corner", "geometry": box(1, 1, 2, 2)},
            {"dist_id": "gap", "geometry": box(3, 3, 4, 4)},
        ],
        geometry="geometry",
        crs="EPSG:32630",
    )
    w = queen_contiguity_weights(geometry)
    assert "corner" in w.neighbours["a"]
    assert "gap" not in w.neighbours["a"]


def test_i_island_receives_no_artificial_link() -> None:
    geometry = gpd.GeoDataFrame(
        [
            {"dist_id": "a", "geometry": box(0, 0, 1, 1)},
            {"dist_id": "b", "geometry": box(1, 0, 2, 1)},
            {"dist_id": "island", "geometry": box(10, 10, 11, 11)},
        ],
        geometry="geometry",
        crs="EPSG:32630",
    )
    w = queen_contiguity_weights(geometry, island_policy="exclude_from_inference")
    assert w.islands == ("island",)
    assert w.neighbours["island"] == ()
    assert "island" not in w.active_ids


def test_j_global_moran_matches_independent_matrix_calculation() -> None:
    geometry = gpd.GeoDataFrame(
        [{"dist_id": str(i), "geometry": box(i, 0, i + 1, 1)} for i in range(4)],
        geometry="geometry",
        crs="EPSG:32630",
    )
    w = queen_contiguity_weights(geometry)
    x = np.array([1.0, 2.0, 5.0, 7.0])
    W = w.row_standardised_matrix()
    z = x - x.mean()
    manual = (len(x) / W.sum()) * float(z @ W @ z) / float(z @ z)
    result = global_morans_i(x, w, permutations=31, random_seed=123)
    assert result.morans_i == pytest.approx(manual)
    assert result.expected_i == pytest.approx(-1.0 / 3.0)


def test_k_local_statistic_p_rule_and_bh_family_are_independent() -> None:
    geometry = gpd.GeoDataFrame(
        [{"dist_id": str(i), "geometry": box(i, 0, i + 1, 1)} for i in range(5)],
        geometry="geometry",
        crs="EPSG:32630",
    )
    w = queen_contiguity_weights(geometry)
    x = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
    local = local_morans_i(x, w, permutations=99, random_seed=22, alpha=0.05, **_local_kwargs())
    z = (x - x.mean()) / np.std(x, ddof=0)
    # Cell 2 has neighbours 1 and 3 in the chain.
    manual_i2 = z[2] * np.mean([z[1], z[3]])
    assert local.set_index("unit_id").loc["2", "local_morans_i"] == pytest.approx(manual_i2)
    simulated = np.array([-2.0, -1.0, 0.0, 1.0, 1.0, 3.0])
    # This low-level compatibility case deliberately exercises the legacy
    # undoubled convention. The production calls above use current configured
    # arguments from _local_kwargs(); independent current-convention parity is
    # checked in test_reference_methods.py.
    p = local_moran_smaller_tail_plus_one(
        simulated, 1.0,
        upper_tail_comparison="greater_than_or_equal", tie_allocation="upper_tail",
        multiply_smaller_tail_by_two=False,
    )
    # >=1 has 3 values; complement has 3, therefore (3+1)/(6+1).
    assert p == pytest.approx(4.0 / 7.0)
    eligible = local.loc[local["diagnostic_status"].eq("ok")]
    independent_bh = benjamini_hochberg(eligible["permutation_p"].tolist(), family_name="independent", alpha=0.05)
    assert eligible["bh_q"].to_numpy() == pytest.approx(independent_bh.adjusted_p_values)


def test_l_same_seed_config_and_input_are_deterministic() -> None:
    geometry = gpd.GeoDataFrame(
        [{"dist_id": str(i), "geometry": box(i, 0, i + 1, 1)} for i in range(6)],
        geometry="geometry",
        crs="EPSG:32630",
    )
    w = queen_contiguity_weights(geometry)
    x = np.array([1.0, 3.0, 2.0, 8.0, 5.0, 13.0])
    g1 = global_morans_i(x, w, permutations=199, random_seed=20260822)
    g2 = global_morans_i(x, w, permutations=199, random_seed=20260822)
    assert g1.to_dict() == g2.to_dict()
    l1 = local_morans_i(x, w, permutations=199, random_seed=20260822, alpha=0.05, **_local_kwargs())
    l2 = local_morans_i(x, w, permutations=199, random_seed=20260822, alpha=0.05, **_local_kwargs())
    pd.testing.assert_frame_equal(l1, l2, check_exact=True)
