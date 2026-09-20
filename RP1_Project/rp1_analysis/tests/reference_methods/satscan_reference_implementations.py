"""Independent test-only SaTScan interface references.

This module deliberately imports no ``rp1_analysis_v1`` code.  It provides
small transparent reference calculations and text parsing used to qualify the
production SaTScan interface without reusing the implementation under test.
"""
from __future__ import annotations

from calendar import monthrange
import re
from typing import Mapping


class SaTScanReferenceError(ValueError):
    """Raised when a test-only reference input is structurally invalid."""


def _parse_month_token(value: str) -> tuple[int, int]:
    token = str(value).strip().replace("/", "-")
    match = re.fullmatch(r"(\d{4})-(\d{1,2})", token)
    if not match:
        raise SaTScanReferenceError(f"month token must be YYYY-MM; got {value!r}")
    year, month = (int(part) for part in match.groups())
    if month < 1 or month > 12:
        raise SaTScanReferenceError(f"invalid calendar month: {value!r}")
    return year, month


def monthly_study_bounds_reference(start_month: str, end_month: str) -> tuple[str, str]:
    """Return SaTScan-valid first-day/last-day monthly study boundaries."""
    start_year, start_number = _parse_month_token(start_month)
    end_year, end_number = _parse_month_token(end_month)
    if (end_year, end_number) < (start_year, start_number):
        raise SaTScanReferenceError("monthly study period is reversed")
    end_day = monthrange(end_year, end_number)[1]
    return f"{start_year}/{start_number}/1", f"{end_year}/{end_number}/{end_day}"


def parse_parameter_assignments_reference(text: str) -> dict[str, str]:
    """Parse unique ``key=value`` assignments without production helpers."""
    assignments: dict[str, str] = {}
    for raw in str(text).splitlines():
        line = raw.strip()
        if not line or line.startswith((";", "[")) or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key in assignments:
            raise SaTScanReferenceError(f"duplicate parameter assignment: {key}")
        assignments[key] = value.strip().replace("\\", "/")
    return assignments


def expected_model_assignments_reference(*, model: str, population_path: str | None) -> Mapping[str, str]:
    """Independent structural contract for the two governed SaTScan models."""
    if model == "discrete_poisson":
        if not population_path:
            raise SaTScanReferenceError("discrete Poisson requires population/exposure")
        return {"ModelType": "0", "PopulationFile": str(population_path).replace("\\", "/"), "IncludeRelativeRisksCensusAreasASCII": "y"}
    if model == "space_time_permutation":
        if population_path is not None:
            raise SaTScanReferenceError("space-time permutation forbids population/exposure")
        return {"ModelType": "2", "PopulationFile": "", "IncludeRelativeRisksCensusAreasASCII": "n"}
    raise SaTScanReferenceError(f"unsupported model: {model!r}")


def expected_frozen_common_assignments_reference() -> Mapping[str, str]:
    """Frozen RP1 secondary-scan interface values that must not drift."""
    return {
        "PrecisionCaseTimes": "2", "AnalysisType": "3", "ScanAreas": "1",
        "TimeAggregationUnits": "2", "TimeAggregationLength": "1",
        "MaxSpatialSizeInPopulationAtRisk": "50", "MinimumTemporalClusterSize": "1",
        "MaxTemporalSizeInterpretation": "1", "MaxTemporalSize": "12",
        "IncludeClusters": "0", "MonteCarloReps": "999",
        "ReportHierarchicalClusters": "y", "CriteriaForReportingSecondaryClusters": "0",
        "ReportGiniClusters": "n", "ReportClusterRank": "y", "SpatialWindowShapeType": "0",
    }
