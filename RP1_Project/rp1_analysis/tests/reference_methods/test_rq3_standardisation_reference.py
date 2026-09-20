from __future__ import annotations

import math

import numpy as np

from rp1_analysis_v1.gee import average_counterfactual_probability


def _manual_expit(value: float) -> float:
    if value >= 0.0:
        return 1.0 / (1.0 + math.exp(-value))
    e = math.exp(value)
    return e / (1.0 + e)


def test_predictive_standardisation_matches_manual_average_on_known_design() -> None:
    # Intercept, focal predictor, observed adjustment.  The focal column is
    # counterfactually fixed while the adjustment values remain row-specific.
    X = np.asarray(
        [
            [1.0, -1.0, 0.0],
            [1.0, 0.0, 1.0],
            [1.0, 1.0, -0.5],
            [1.0, 2.0, 0.5],
        ],
        dtype=float,
    )
    beta = np.asarray([-0.4, 0.7, -0.3], dtype=float)
    transformed_q = 0.75

    observed = average_counterfactual_probability(
        X, beta, term_index=1, transformed_value=transformed_q
    )

    manual = 0.0
    for row in X.tolist():
        row[1] = transformed_q
        eta = sum(float(a) * float(b) for a, b in zip(row, beta.tolist(), strict=True))
        manual += _manual_expit(eta)
    manual /= len(X)

    np.testing.assert_allclose(observed, manual, rtol=0.0, atol=1e-15)
