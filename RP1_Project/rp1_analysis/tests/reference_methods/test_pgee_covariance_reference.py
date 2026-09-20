from __future__ import annotations

import numpy as np

from rp1_analysis_v1.pgee import (
    fit_firth_pgee_independence,
    fit_pgee_with_morel_standard_normal_inference,
    morel_bokossa_neerchal_covariance,
)
from .pgee_reference_implementations import mbn_covariance_reference


def _clustered_fixture():
    rng=np.random.default_rng(712)
    sizes=[5,9,4,8,6,10,7,5,9,6,8,7,5,10,6,8,5,9,7,6]
    cluster=np.concatenate([[i]*n for i,n in enumerate(sizes)])
    n=len(cluster); x=rng.normal(size=n); z=(np.arange(n)%4==0).astype(float)
    X=np.column_stack([np.ones(n),x,z])
    eta=-0.4+0.8*x-0.5*z
    p=1/(1+np.exp(-eta)); y=rng.binomial(1,p).astype(float)
    # one valid all-Y=1 cluster exercises the covariance with homogeneous clusters
    y[cluster==0]=1.0
    return X,y,cluster


def test_morel_covariance_matches_independent_reference():
    X,y,cluster=_clustered_fixture(); beta=fit_firth_pgee_independence(X,y,tolerance=1e-8,max_iterations=250,max_step_halvings=40)[0]
    observed=morel_bokossa_neerchal_covariance(X,y,cluster,beta)
    expected=mbn_covariance_reference(X,y,cluster,beta)
    np.testing.assert_allclose(observed[0],expected[0],rtol=2e-12,atol=2e-12)
    np.testing.assert_allclose(observed[1:],expected[1:],rtol=2e-12,atol=2e-12)
    assert np.all(np.isfinite(observed[0]))
    assert np.allclose(observed[0],observed[0].T)
    assert np.linalg.eigvalsh(observed[0]).min()>0


def test_standard_normal_reference_has_no_finite_df_authority():
    X,y,cluster=_clustered_fixture()
    result=fit_pgee_with_morel_standard_normal_inference(
        X,y,cluster,alpha=0.05,tolerance=1e-8,max_iterations=250,max_step_halvings=40
    )
    assert result.n_clusters == len(np.unique(cluster))
    assert result.design_dimension == X.shape[1]
    assert not hasattr(result, "degrees_of_freedom")
    assert np.isfinite(result.standard_errors).all()
    assert np.isfinite(result.wald_z).all()
    assert np.isfinite(result.standard_normal_p).all()


def test_standard_normal_wald_matches_independent_formula():
    import math
    from statistics import NormalDist

    X, y, cluster = _clustered_fixture()
    result = fit_pgee_with_morel_standard_normal_inference(
        X, y, cluster, alpha=0.05, tolerance=1e-8, max_iterations=250, max_step_halvings=40
    )
    normal = NormalDist()
    critical = normal.inv_cdf(0.975)
    for beta, se, z, p, low, high in zip(
        result.coefficients,
        result.standard_errors,
        result.wald_z,
        result.standard_normal_p,
        result.standard_normal_ci_low,
        result.standard_normal_ci_high,
        strict=True,
    ):
        expected_z = float(beta / se)
        expected_p = 2.0 * (1.0 - normal.cdf(abs(expected_z)))
        assert math.isclose(float(z), expected_z, rel_tol=0.0, abs_tol=1e-14)
        assert math.isclose(float(p), expected_p, rel_tol=0.0, abs_tol=2e-15)
        assert math.isclose(float(low), float(beta - critical * se), rel_tol=0.0, abs_tol=1e-14)
        assert math.isclose(float(high), float(beta + critical * se), rel_tol=0.0, abs_tol=1e-14)
