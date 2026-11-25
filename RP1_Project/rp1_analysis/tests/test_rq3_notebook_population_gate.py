"""The notebook gate uses the validated run's realised RQ3 population."""
import json
from pathlib import Path
from types import SimpleNamespace as NS
import pytest


class NonemptyRows:
    empty = False
    def __len__(self):
        return 1


def gate_source():
    notebook = json.loads((Path(__file__).parents[1] / 'RP1_Analysis_v1.ipynb').read_text())
    cells = [c for c in notebook['cells'] if c.get('id') == 'rp1-code-03-02']
    assert len(cells) == 1
    return ''.join(cells[0]['source'])


def context(rows=3, clusters=2, converged=True):
    fit = NS(n_clusters=clusters, design_dimension=2, converged=converged,
             coefficients_finite=True, covariance_finite=True)
    rq3 = NS(model_population=[1, 2, 3], production_pgee=NS(production=NS(fit=fit)),
             gee_design=NS(term_order=['intercept', 'x'], reference_distribution='normal'),
             standardised_probability_source=NonemptyRows())
    # The configuration explicitly leaves realised counts unresolved.
    contract = NS(analysis=NS(research_questions={'rq3': {'model_population': 'rq3_model'}},
                               study={'populations': {'rq3_model': {'rows': None, 'units': None}}}))
    return dict(rq3=rq3, contracts=contract, data_contract=NS(rq3_gee_rows=rows, rq3_gee_units=2),
                rq3_parameters=NS(reference_distribution='normal'),
                display=lambda obj: None, pd=NS(DataFrame=lambda obj: obj))


def test_gate_accepts_realised_counts_when_config_is_unset():
    ctx=context()
    exec(compile(gate_source(), 'rq3_gate', 'exec'), ctx)
    assert ctx['rq3_gate'] == 'PASS'


@pytest.mark.parametrize('kwargs', [dict(rows=4), dict(clusters=3), dict(converged=False)])
def test_gate_rejects_population_or_fit_failure(kwargs):
    with pytest.raises(AssertionError):
        exec(compile(gate_source(), 'rq3_gate', 'exec'), context(**kwargs))
