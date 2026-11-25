"""Direct input references for generated-data integration tests.

These checks independently derive integration references from current inputs.
Mathematical examples live in tests/fixtures/reference_methods.
"""
from functools import lru_cache
from pathlib import Path

import pandas as pd

from rp1_analysis_v1.config import load_configuration_bundle
from rp1_analysis_v1.variables import resolve_field_role

ROOT = Path(__file__).resolve().parents[1]


@lru_cache(maxsize=1)
def panel_input_reference(panel_id="district_monthly"):
    bundle = load_configuration_bundle(ROOT / "config")
    return pd.read_csv(ROOT / bundle.data_schema.panels[panel_id].path)


def population_input_reference(population):
    bundle = load_configuration_bundle(ROOT / "config")
    panel = panel_input_reference()
    spec = bundle.analysis.study["populations"][population]
    start, end = (int(str(spec[x]).replace("-", "")) for x in ("start", "end"))
    panel = panel.loc[panel.yyyymm.between(start, end)].copy()
    denominator = resolve_field_role(bundle.analysis, spec["denominator_role"])
    complete = panel.groupby("unit_id")[denominator].agg(lambda x: x.notna().all() and x.gt(0).all())
    for role in spec.get("support_roles", ()):
        flag = resolve_field_role(bundle.analysis, role)
        complete &= panel.groupby("unit_id")[flag].agg(lambda x: x.eq(1).all())
    return panel.loc[panel.unit_id.isin(complete.index[complete])].copy()


def long_run_input_reference():
    return population_input_reference("long_run_district")


def input_population_sizes():
    long_run, paired, model = long_run_input_reference(), paired_input_reference(), model_input_reference()
    panel = panel_input_reference()
    return {
        "ACZ_MONTHLY_ROWS": len(panel_input_reference("acz_monthly")),
        "DISTRICT_MONTHLY_ROWS": len(panel), "DISTRICT_UNITS": panel.unit_id.nunique(),
        "LONG_RUN_DISTRICTS": long_run.unit_id.nunique(), "LONG_RUN_ROWS": len(long_run),
        "PAIRED_DISTRICTS": paired.unit_id.nunique(), "PAIRED_ROWS": len(paired),
        "RQ3_GEE_DISTRICTS": model.unit_id.nunique(), "RQ3_GEE_ROWS": len(model),
    }


@lru_cache(maxsize=1)
def paired_input_reference():
    return population_input_reference("paired_overlap")


@lru_cache(maxsize=1)
def model_input_reference():
    paired = paired_input_reference()
    model = paired.loc[paired.viirs_det_primary.gt(0)].copy()
    model["mismatch_y"] = 1 - model.modis_ba_any_ba2012.astype(int)
    return model


def cluster_reference():
    return model_input_reference().groupby("unit_id").mismatch_y.agg(["size", "sum"])


def factor_outcome_reference():
    frame = model_input_reference()
    bundle = load_configuration_bundle(ROOT / "config")
    records = []
    for spec in bundle.analysis.research_questions["rq3"]["factors"]:
        field = str(resolve_field_role(bundle.analysis, str(spec["field_role"])))
        for level, group in frame.groupby(field, observed=True):
            y1, n = int(group.mismatch_y.sum()), len(group)
            # The diagnostic authority names factors by their source field.
            records.append({"factor": field, "level": str(level),
                            "n": n, "y1": y1, "y0": n - y1,
                            "complete_separation": y1 in (0, n)})
    return pd.DataFrame(records)


def factor_outcomes_by_key(table):
    """Align factor results by their explicit string keys, independent of category order."""
    result = table.copy()
    for column in ("factor", "level"):
        result[column] = result[column].astype(str)
    result = result.set_index(["factor", "level"], verify_integrity=True)
    return result.sort_index()


def design_terms_reference():
    bundle = load_configuration_bundle(ROOT / "config")
    frame = model_input_reference()
    spec = bundle.analysis.research_questions["rq3"]
    terms = ["Intercept", *(str(item["term_name"]) for item in spec["predictors"])]
    for factor in spec["factors"]:
        field = str(resolve_field_role(bundle.analysis, str(factor["field_role"])))
        levels = sorted(frame[field].unique())
        terms.extend(f"{factor['term_prefix']}_{level}" for level in levels if level != factor["reference"])
    return tuple(terms)
