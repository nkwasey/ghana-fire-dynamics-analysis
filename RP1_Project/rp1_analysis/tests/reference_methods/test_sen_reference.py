from __future__ import annotations

import json
from pathlib import Path

import pytest

from rp1_analysis_v1.inference import sens_slope
from .reference_implementations import sen_reference

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/reference_methods/sen_slope.json"


def test_sen_slope_matches_independent_pairwise_reference() -> None:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    inp = fixture["input"]
    observed = sens_slope(
        inp["y"], x=inp["x"], confidence_level=inp["confidence_level"]
    )
    expected = sen_reference(
        inp["y"], x=inp["x"], confidence_level=inp["confidence_level"]
    )
    assert observed.slope == pytest.approx(expected["slope"], abs=1e-12)
    assert observed.ci_low == pytest.approx(expected["ci_low"], abs=1e-12)
    assert observed.ci_high == pytest.approx(expected["ci_high"], abs=1e-12)
