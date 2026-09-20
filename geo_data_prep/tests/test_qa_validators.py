from __future__ import annotations

import pandas as pd
import pytest
from geo_data_prep.qa.validators import (
    DEFAULT_SHARE_BOUND_TOL,
    validate_assignment_share_thresholds,
    validate_invalid_geometry_counts,
)


def _assigned_overlap_table(shares: list[float]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "district_id": [f"D{i}" for i in range(len(shares))],
            "ovl_share": shares,
            "is_assigned": [True] * len(shares),
        }
    )


def test_assignment_share_validator_tolerates_machine_precision_boundary_overshoot() -> None:
    share = 1.0 + (DEFAULT_SHARE_BOUND_TOL / 10.0)

    summary = validate_assignment_share_thresholds(
        _assigned_overlap_table([share]),
        share_bound_tol=DEFAULT_SHARE_BOUND_TOL,
    )

    assert summary.status == "pass"
    assert summary.ok is True
    assert summary.details is not None
    assert summary.details["invalid_share_count"] == 0
    assert summary.details["clamped_high_count"] == 1
    assert summary.details["max_share"] == pytest.approx(1.0, abs=1e-15)
    assert summary.details["raw_max_share"] == pytest.approx(share, abs=1e-15)


def test_assignment_share_validator_still_fails_for_material_boundary_violation() -> None:
    share = 1.0 + (DEFAULT_SHARE_BOUND_TOL * 10.0)

    summary = validate_assignment_share_thresholds(
        _assigned_overlap_table([share]),
        share_bound_tol=DEFAULT_SHARE_BOUND_TOL,
    )

    assert summary.status == "fail"
    assert summary.ok is False
    assert summary.details is not None
    assert summary.details["invalid_share_count"] == 1
    assert summary.details["clamped_high_count"] == 0
    assert summary.details["raw_max_share"] is None
    assert summary.details["max_share"] is None


def test_invalid_geometry_metric_emits_pass_with_runtime_layer_counts() -> None:
    summary = validate_invalid_geometry_counts(
        layer_invalid_counts={"zones": 0, "districts": 0},
        warn_above=0,
        fail_above=0,
    )

    assert summary.status == "pass"
    assert summary.ok is True
    assert summary.details == {
        "invalid_geometry_count": 0,
        "layer_invalid_counts": {"zones": 0, "districts": 0},
        "warn_above": 0,
        "fail_above": 0,
    }


def test_invalid_geometry_metric_respects_upper_bound_thresholds() -> None:
    summary = validate_invalid_geometry_counts(
        layer_invalid_counts={"zones": 1, "districts": 0},
        warn_above=0,
        fail_above=0,
    )

    assert summary.status == "fail"
    assert summary.ok is False
    assert summary.details is not None
    assert summary.details["invalid_geometry_count"] == 1
    assert summary.details["layer_invalid_counts"] == {"zones": 1, "districts": 0}
