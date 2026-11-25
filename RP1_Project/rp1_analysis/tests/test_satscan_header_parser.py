from pathlib import Path
import math

import pytest

from rp1_analysis_v1.satscan_io import (
    MODEL_DISCRETE_POISSON,
    MODEL_SPACE_TIME_PERMUTATION,
    ExternalResultValidationError,
    parse_cluster_file,
    parse_membership_file,
)


ROOT = Path(__file__).resolve().parent
REFERENCE = ROOT / "fixtures/reference_methods/satscan"


def test_poisson_distinguishes_ode_rr_and_log_likelihood():
    path = REFERENCE / "known_good.col.txt"
    out = parse_cluster_file(path, alpha=0.05, model=MODEL_DISCRETE_POISSON)
    first = out.iloc[0]
    assert len(out) == 1
    assert first.case_count == 4
    assert first.expected_count == 2
    assert first.observed_expected_ratio == 2.0
    assert first.relative_risk == 2.5
    assert first.log_likelihood_ratio == 12.3
    assert "likelihood_ratio" not in out.columns
    assert first.test_statistic_type == "LLR"


def test_stp_never_invents_rr_or_llr():
    path = REFERENCE / "known_good_stp.col.txt"
    first = parse_cluster_file(path, alpha=0.05, model=MODEL_SPACE_TIME_PERMUTATION).iloc[0]
    assert first.case_count == 4
    assert math.isnan(first.expected_count)
    assert first.conditional_expected == 2
    assert first.observed_expected_ratio == 2.0
    assert first.test_statistic == 12.3
    assert first.test_statistic_type == "TEST_STAT"
    assert math.isnan(first.log_likelihood_ratio)
    assert math.isnan(first.relative_risk)


def test_header_reorder_has_no_effect(tmp_path):
    fixture = REFERENCE / "known_good.col.txt"
    lines = [line.split() for line in fixture.read_text().splitlines()]
    order = list(reversed(range(len(lines[0]))))
    target = tmp_path / "reordered.col.txt"
    target.write_text("\n".join(" ".join(row[i] for i in order) for row in lines))
    actual = parse_cluster_file(target, alpha=0.05, model=MODEL_DISCRETE_POISSON)
    expected = parse_cluster_file(fixture, alpha=0.05, model=MODEL_DISCRETE_POISSON)
    assert actual.equals(expected)


def test_membership_is_header_driven(tmp_path):
    target = tmp_path / "reordered.gis.txt"
    target.write_text("P_VALUE CLUSTER LOCATION\n0.01 1 A\n0.01 1 B\n")
    actual = parse_membership_file(target, alpha=0.05)
    assert actual.location_id.tolist() == ["A", "B"]


@pytest.mark.parametrize("change,match", [
    (lambda s: s.replace("REL_RISK", "ODE"), "duplicate header"),
    (lambda s: s.replace(" ODE ", " UNKNOWN "), "observed_expected_ratio"),
    (lambda s: s.replace(" REL_RISK ", " UNKNOWN "), "relative_risk"),
    (lambda s: s.replace(" LLR ", " TEST_STAT "), "does not match|relative risk"),
    (lambda s: s.replace(" 0.01 ", " bananas "), "p-value format"),
    (lambda s: s.replace(" 0.01 ", " <0.1 "), "indeterminate"),
    (lambda s: s.replace("2020/1/1", "2020/2/31"), "not a valid date"),
    (lambda s: s.replace("2020/1/1", "2020/1/1/garbage"), "full SaTScan date"),
    (lambda s: s.replace(" 10000 10000 ", " -1 10000 "), "radius"),
])
def test_corrupt_or_incompatible_sources_fail_closed(tmp_path, change, match):
    source = (REFERENCE / "known_good.col.txt").read_text()
    path = tmp_path / "bad.col.txt"
    path.write_text(change(source))
    with pytest.raises(ExternalResultValidationError, match=match):
        parse_cluster_file(path, alpha=0.05, model=MODEL_DISCRETE_POISSON)


def test_reported_p_qualifier_is_preserved_without_false_precision(tmp_path):
    source = (REFERENCE / "known_good.col.txt").read_text().replace(" 0.01 ", " <0.001 ")
    path = tmp_path / "censored.col.txt"
    path.write_text(source)
    row = parse_cluster_file(path, alpha=0.05, model=MODEL_DISCRETE_POISSON).iloc[0]
    assert row.p_value_report == "<0.001"
    assert row.p_value == 0.001


def test_duplicate_membership_and_malformed_rows_fail(tmp_path):
    path = tmp_path / "bad.gis.txt"
    path.write_text("LOC_ID CLUSTER P_VALUE\n1 1 0.01\n1 1 0.01\n")
    with pytest.raises(ExternalResultValidationError, match="Duplicate"):
        parse_membership_file(path, alpha=0.05)
    path.write_text("LOC_ID CLUSTER P_VALUE\n1 1\n")
    with pytest.raises(ExternalResultValidationError, match="Malformed"):
        parse_membership_file(path, alpha=0.05)
