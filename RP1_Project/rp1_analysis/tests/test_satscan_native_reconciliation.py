from __future__ import annotations

import os
import re
from math import log
from pathlib import Path

import pytest
from rp1_analysis_v1.satscan_io import (
    MODEL_DISCRETE_POISSON,
    MODEL_SPACE_TIME_PERMUTATION,
    ExternalResultValidationError,
    sha256_file,
    validate_external_results,
)


def _refresh_outputs(core: dict[str, Path], authority: Path) -> None:
    # A coherent test family represents outputs generated after the test change
    # to its governed input. The freshness guard is covered separately.
    timestamp = authority.stat().st_mtime_ns + 1_000_000_000
    for output in core.values():
        os.utime(output, ns=(timestamp, timestamp))


@pytest.fixture(params=[MODEL_DISCRETE_POISSON, MODEL_SPACE_TIME_PERMUTATION])
def native_family(request, tmp_path: Path):
    poisson = request.param == MODEL_DISCRETE_POISSON
    # Leap February and unequal month lengths make month-count weighting detectably wrong.
    expected = 19 * (310 / 1000) * (31 / 60) if poisson else (9 * 10) / 19
    oe = 8 / expected
    rr = oe / (11 / (19 - expected))
    statistic = 8 * log(oe) + 11 * log(11 / (19 - expected))
    model_label = "Discrete Poisson" if poisson else "Space-Time Permutation"
    statistic_label = "Log likelihood ratio" if poisson else "Test statistic"
    statistic_header = "LLR" if poisson else "TEST_STAT"
    owned_population = "Population File: small.pop\n" if poisson else ""
    model_population = "Population, averaged over time: 1000\n" if poisson else ""
    cluster_population = f"Population: 310\nRelative risk: {rr:.2f}\n" if poisson else ""
    ascii_population = f" {rr:.2f} 310.00" if poisson else ""
    cluster_population_header = " REL_RISK POPULATION" if poisson else ""
    membership_population_header = " CLU_RR CLU_POP" if poisson else ""
    parameters = (
        "CaseFile=small.cas\nCoordinatesFile=small.geo\nResultsFile=small\n"
        "PrintAsciiColumnHeaders=y\nMostLikelyClusterEachCentroidASCII=y\nCensusAreasReportedClustersASCII=y\n"
        "MaxSpatialSizeInPopulationAtRisk=50\nMonteCarloReps=999\n"
    )
    if poisson:
        parameters += "PopulationFile=small.pop\n"
        (tmp_path / "small.pop").write_text(
            "1 2020/1/1 100\n2 2020/1/1 210\n3 2020/1/1 210\n4 2020/1/1 480\n", encoding="utf-8",
        )
    else:
        parameters += "PopulationFile=\n"
    (tmp_path / "small.cas").write_text(
        "1 8 2020/1/1\n1 1 2020/2/1\n4 2 2020/1/1\n4 8 2020/2/1\n", encoding="utf-8",
    )
    (tmp_path / "small.geo").write_text("1 0 0\n2 1 0\n3 9 0\n4 10 10\n", encoding="utf-8")
    (tmp_path / "small.prm").write_text(parameters, encoding="utf-8")
    core = {
        "report": tmp_path / "small", "col": tmp_path / "small.col.txt", "gis": tmp_path / "small.gis.txt",
    }
    core["report"].write_text(
        f"SaTScan v10.3.3\nusing the {model_label} model.\n"
        "SUMMARY OF DATA\nStudy period: 2020/1/1 to 2020/2/29\n"
        "Number of locations: 4\nTotal number of cases: 19\n"
        f"{model_population}"
        "CLUSTERS DETECTED\n1.Location IDs included.: 1,\n                          2\n"
        "Coordinates / radius: (0,0) / 1\nSpan: 1\nTime frame: 2020/1/1 to 2020/1/31\n"
        f"Number of cases: 8\nExpected cases: {expected:.2f}\nObserved / expected: {oe:.2f}\n"
        f"{cluster_population}{statistic_label}: {statistic:.6f}\nP-value: 0.001\n"
        "PARAMETER SETTINGS\nCase File: small.cas\nCoordinates File: small.geo\nMain Results File: small\n"
        f"{owned_population}"
        "Start Date: 2020/1/1\nEnd Date: 2020/2/29\nTime Precision: Month\nCoordinates: Cartesian\n"
        f"Type of Analysis: Retrospective Space-Time\nProbability Model: {model_label}\n"
        "Scan For Areas With: High Rates\nTime Aggregation Units: Month\nTime Aggregation Length: 1\n"
        "Window Shape: Circular\nMaximum Spatial Cluster Size: 50 percent of population at risk\n"
        "Minimum Temporal Cluster Size: 1 Month\nMaximum Temporal Cluster Size: 1 Month\n"
        "Number of Replications: 999\nP-Value Reporting: Standard Monte Carlo\nReport Gumbel Based P-Values: No\n"
        "Report Hierarchical Clusters: Yes\nCriteria for Reporting Secondary Clusters: No Geographical Overlap\n"
        "Print ASCII Column Headers: Yes\nCluster Information: Yes (ASCII), No (dBase)\n"
        "Location Information: Yes (ASCII), No (dBase)\nProgram completed\n",
        encoding="utf-8",
    )
    core["col"].write_text(
        "CLUSTER LOC_ID X Y RADIUS SPAN START_DATE END_DATE NUMBER_LOC "
        f"{statistic_header} P_VALUE OBSERVED EXPECTED ODE{cluster_population_header} GINI_CLUST\n"
        f"1 1 0 0 1 1 2020/1/1 2020/1/31 2 {statistic:.6f} 0.00100 8 "
        f"{expected:.2f} {oe:.2f}{ascii_population} F\n",
        encoding="utf-8",
    )
    core["gis"].write_text(
        f"LOC_ID CLUSTER P_VALUE CLU_OBS CLU_EXP CLU_ODE{membership_population_header}\n"
        f"1 1 0.00100 8 {expected:.2f} {oe:.2f}{ascii_population}\n"
        f"2 1 0.00100 8 {expected:.2f} {oe:.2f}{ascii_population}\n",
        encoding="utf-8",
    )
    row = {
        "scenario_id": "native_test", "product": "synthetic", "model": request.param,
        "results_prefix": "small", "engine_version_authority": "10.3.3",
        "temporal_start": "2020-01", "temporal_end": "2020-02", "max_temporal_months": 1,
        "prm_path": "small.prm", "prm_sha256": sha256_file(tmp_path / "small.prm"),
        "case_path": "small.cas", "case_sha256": sha256_file(tmp_path / "small.cas"),
        "coordinate_path": "small.geo", "coordinate_sha256": sha256_file(tmp_path / "small.geo"),
    }
    if poisson:
        row.update(population_path="small.pop", population_sha256=sha256_file(tmp_path / "small.pop"))
    return core, row, expected


def test_native_results_match_unequal_calendar_days_or_stp_margins(native_family, tmp_path: Path):
    _, row, expected = native_family
    result = validate_external_results(row, run_dir=tmp_path, alpha=0.05)
    expected_field = "expected_count" if row["model"] == MODEL_DISCRETE_POISSON else "conditional_expected"
    assert list(result.clusters[expected_field]) == [float(f"{expected:.2f}")]
    assert set(result.membership["location_id"]) == {"1", "2"}


@pytest.mark.parametrize("report_line", ["No clusters were found.", "No clusters reported."])
def test_header_only_native_results_require_an_explicit_no_cluster_finding(
    native_family, tmp_path: Path, report_line: str,
):
    core, row, _ = native_family
    for role in ("col", "gis"):
        path = core[role]
        path.write_text(path.read_text(encoding="utf-8").splitlines()[0] + "\n", encoding="utf-8")
    path = core["report"]
    report = path.read_text(encoding="utf-8")
    empty = re.sub(r"(?<=CLUSTERS DETECTED\n)[\s\S]*?(?=PARAMETER SETTINGS)", "", report)
    path.write_text(empty, encoding="utf-8")
    with pytest.raises(ExternalResultValidationError, match="explicit engine finding"):
        validate_external_results(row, run_dir=tmp_path, alpha=0.05)

    report_zero = empty.replace("CLUSTERS DETECTED\n", f"{report_line}\n")
    path.write_text(report_zero, encoding="utf-8")
    result = validate_external_results(row, run_dir=tmp_path, alpha=0.05)
    assert result.clusters.empty
    assert result.membership.empty


@pytest.mark.parametrize(
    "mutation,error",
    [
        ("expected_in_column_only", "report and cluster output disagree on EXPECTED"),
        ("expected_in_all_files", "EXPECTED differs from governed reconstruction"),
        ("zero_case_member_swap", "report and membership locations disagree"),
        ("incorrect_centre", "reported X differs from the governed centre"),
        ("unlisted_centre", "governed centre is not among the window members"),
        ("small_radius", "RADIUS differs from governed reconstruction"),
        ("incorrect_span", "SPAN differs from governed reconstruction"),
        ("omitted_inside_location", "omits a governed location inside its circular window"),
        ("below_window_share", "exceeds the governed spatial-window"),
        ("location_count", "Number of locations differs from governed values"),
        ("total_cases", "Total number of cases differs from governed values"),
        ("observed_cases_in_all_files", "observed cases differ from the governed case window"),
        ("incorrect_max_spatial", "Maximum Spatial Cluster Size differs from governed values"),
        ("incorrect_replications", "Number of Replications differs from governed values"),
        ("missing_max_spatial", "section is missing Maximum Spatial Cluster Size"),
        ("missing_replications", "section is missing Number of Replications"),
        ("compact_report", "native parameter or summary section is missing"),
    ],
)
def test_native_result_authority_rejects_corruption(native_family, tmp_path: Path, mutation, error):
    core, row, expected = native_family

    def rewrite(role: str, pattern: str, replacement: str) -> None:
        path = core[role]
        changed, substitutions = re.subn(pattern, replacement, path.read_text(encoding="utf-8"), flags=re.M)
        assert substitutions
        path.write_text(changed, encoding="utf-8")

    if mutation in {"expected_in_column_only", "expected_in_all_files"}:
        token = re.escape(f"{expected:.2f}")
        rewrite("col", rf"(?<= 8 ){token}(?= )", "7.00")
        if mutation == "expected_in_all_files":
            rewrite("gis", rf"(?<= 8 ){token}(?= )", "7.00")
            rewrite("report", rf"(?<=Expected cases: ){token}$", "7.00")
    elif mutation == "zero_case_member_swap":
        rewrite("gis", r"^2 ", "3 ")
    elif mutation == "incorrect_centre":
        rewrite("report", r"\(0,0\) /", "(0.25,0) /")
        rewrite("col", r"^1 1 0 0 ", "1 1 0.25 0 ")
    elif mutation == "unlisted_centre":
        rewrite("report", r"\(0,0\) /", "(9,0) /")
        rewrite("col", r"^1 1 0 0 ", "1 3 9 0 ")
    elif mutation == "small_radius":
        rewrite("report", r"(?<=\(0,0\) / )1$", "0.75")
        rewrite("col", r"^1 1 0 0 1 1 ", "1 1 0 0 0.75 1 ")
    elif mutation == "incorrect_span":
        rewrite("report", r"(?<=Span: )1$", "0.75")
        rewrite("col", r"^1 1 0 0 1 1 ", "1 1 0 0 1 0.75 ")
    elif mutation == "omitted_inside_location":
        geo = tmp_path / "small.geo"
        geo.write_text("1 0 0\n2 1 0\n3 0.5 0\n4 10 10\n", encoding="utf-8")
        row["coordinate_sha256"] = sha256_file(geo)
        _refresh_outputs(core, geo)
    elif mutation == "below_window_share":
        prm = tmp_path / "small.prm"
        prm.write_text(
            prm.read_text(encoding="utf-8").replace("MaxSpatialSizeInPopulationAtRisk=50", "MaxSpatialSizeInPopulationAtRisk=25"),
            encoding="utf-8",
        )
        row["prm_sha256"] = sha256_file(prm)
        rewrite("report", r"50 percent of population at risk", "25 percent of population at risk")
        _refresh_outputs(core, prm)
    elif mutation == "location_count":
        rewrite("report", r"^Number of locations: 4$", "Number of locations: 5")
    elif mutation == "total_cases":
        rewrite("report", r"^Total number of cases: 19$", "Total number of cases: 20")
    elif mutation == "observed_cases_in_all_files":
        rewrite("report", r"^Number of cases: 8$", "Number of cases: 9")
        for role in ("col", "gis"):
            rewrite(role, r"(?<=0\.00100 )8(?= )", "9")
    elif mutation == "incorrect_max_spatial":
        rewrite("report", r"50 percent of population at risk", "25 percent of population at risk")
    elif mutation == "incorrect_replications":
        rewrite("report", r"^Number of Replications: 999$", "Number of Replications: 99")
    elif mutation == "missing_max_spatial":
        rewrite("report", r"^Maximum Spatial Cluster Size:[^\n]+\n", "")
    elif mutation == "missing_replications":
        rewrite("report", r"^Number of Replications:[^\n]+\n", "")
    else:
        # The governed PRM still requests the native reports, even if the complete
        # result triad is replaced with the compact shape.
        rewrite("report", r"(?<=\n)(?:SUMMARY OF DATA\n|CLUSTERS DETECTED\n|PARAMETER SETTINGS\n)", "")
        rewrite("gis", r"(?<=P_VALUE) CLU_.*$", "")
        rewrite("gis", r"(?<=0\.00100) .+$", "")
    with pytest.raises(ExternalResultValidationError, match=error):
        validate_external_results(row, run_dir=tmp_path, alpha=0.05)


def test_full_native_mode_is_bound_to_the_governed_parameter_file(native_family, tmp_path: Path):
    _, row, _ = native_family
    prm = tmp_path / "small.prm"
    prm.write_text(prm.read_text(encoding="utf-8").replace("PrintAsciiColumnHeaders=y", "PrintAsciiColumnHeaders=n"),
                   encoding="utf-8")
    with pytest.raises(ExternalResultValidationError, match="Parameter-file authority does not match run registry"):
        validate_external_results(row, run_dir=tmp_path, alpha=0.05)


def test_native_spatial_cap_uses_model_specific_study_total(native_family, tmp_path: Path):
    core, row, _ = native_family
    prm = tmp_path / "small.prm"
    prm.write_text(
        prm.read_text(encoding="utf-8").replace("MaxSpatialSizeInPopulationAtRisk=50", "MaxSpatialSizeInPopulationAtRisk=40"),
        encoding="utf-8",
    )
    row["prm_sha256"] = sha256_file(prm)
    report = core["report"]
    report.write_text(
        report.read_text(encoding="utf-8").replace("50 percent of population at risk", "40 percent of population at risk"),
        encoding="utf-8",
    )
    _refresh_outputs(core, prm)
    if row["model"] == MODEL_DISCRETE_POISSON:
        # The included locations carry 31% of the study exposure.
        assert len(validate_external_results(row, run_dir=tmp_path, alpha=0.05).clusters) == 1
    else:
        # Nine of 19 study cases are at the included locations. The cluster
        # month alone has a different denominator.
        with pytest.raises(ExternalResultValidationError, match="spatial-window case maximum"):
            validate_external_results(row, run_dir=tmp_path, alpha=0.05)


def test_native_geometry_uses_unrounded_circle_and_general_format_centre(native_family, tmp_path: Path):
    core, row, _ = native_family
    geo = tmp_path / "small.geo"
    geo.write_text(
        "1 0 1133308.000000\n2 0.997 1133308.000000\n3 0.999 1133308.000000\n4 10 1133318.000000\n",
        encoding="utf-8",
    )
    row["coordinate_sha256"] = sha256_file(geo)
    report, col = core["report"], core["col"]
    report.write_text(report.read_text(encoding="utf-8").replace("(0,0)", "(0,1.13331e+06)"), encoding="utf-8")
    col.write_text(col.read_text(encoding="utf-8").replace("1 1 0 0 1 1 ", "1 1 0 1.13331e+06 1 1 "), encoding="utf-8")
    _refresh_outputs(core, geo)
    assert set(validate_external_results(row, run_dir=tmp_path, alpha=0.05).membership["location_id"]) == {"1", "2"}

    # Scientific notation with trimmed trailing zeroes is still printed at
    # six significant digits. A 50-unit interpretation would admit this error.
    for file in (report, col):
        file.write_text(file.read_text(encoding="utf-8").replace("1.13331e+06", "1.1333e+06"), encoding="utf-8")
    _refresh_outputs(core, geo)
    with pytest.raises(ExternalResultValidationError, match="reported Y differs from the governed centre"):
        validate_external_results(row, run_dir=tmp_path, alpha=0.05)
