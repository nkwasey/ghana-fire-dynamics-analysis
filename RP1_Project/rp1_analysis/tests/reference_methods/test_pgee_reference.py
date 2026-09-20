from __future__ import annotations

import numpy as np
import pytest

from rp1_analysis_v1.pgee import PGEEError, fit_firth_pgee_independence
from .pgee_reference_implementations import firth_coefficients_reference


def _case(kind: str):
    rng=np.random.default_rng(4107)
    n=120
    x=np.linspace(-2,2,n)
    z=(np.arange(n)%3==0).astype(float)
    X=np.column_stack([np.ones(n),x,z])
    if kind=='complete':
        x=(np.arange(n)>=n//2).astype(float)
        z=(np.arange(n)%2==0).astype(float)
        X=np.column_stack([np.ones(n),x,z])
        y=x.copy()
    elif kind=='quasi':
        y=(x>0).astype(float); y[10]=1.0
    elif kind=='near':
        y=(x>0).astype(float); y[[10,100]]=[1.0,0.0]
    elif kind=='none':
        p=1/(1+np.exp(-(-0.3+0.7*x-0.4*z))); y=rng.binomial(1,p).astype(float)
    else: raise ValueError(kind)
    return X,y


@pytest.mark.parametrize('kind',['complete','quasi','near','none'])
def test_pgee_coefficients_match_independent_firth_objective(kind):
    X,y=_case(kind)
    observed,_,score,_=fit_firth_pgee_independence(X,y,tolerance=1e-8,max_iterations=250,max_step_halvings=40)
    expected=firth_coefficients_reference(X,y)
    assert np.isfinite(observed).all()
    assert score < 1e-6
    np.testing.assert_allclose(observed,expected,rtol=2e-5,atol=2e-5)


def test_pgee_is_deterministic():
    X,y=_case('complete')
    first=fit_firth_pgee_independence(X,y,tolerance=1e-8,max_iterations=250,max_step_halvings=40)[0]
    second=fit_firth_pgee_independence(X,y,tolerance=1e-8,max_iterations=250,max_step_halvings=40)[0]
    np.testing.assert_array_equal(first,second)


def test_rank_defect_fails_closed():
    X,y=_case('none')
    bad=np.column_stack([X,X[:,1]])
    with pytest.raises(PGEEError,match='rank-deficient'):
        fit_firth_pgee_independence(bad,y,tolerance=1e-8,max_iterations=250,max_step_halvings=40)
