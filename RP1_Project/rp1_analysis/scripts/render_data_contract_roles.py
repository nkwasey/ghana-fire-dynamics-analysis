#!/usr/bin/env python3
"""Render the config-derived scientific-role projection in Data_Contract.md."""
from __future__ import annotations

import argparse
from pathlib import Path
import yaml

START = "<!-- BEGIN CONFIG-DERIVED SCIENTIFIC ROLE PROJECTION -->"
END = "<!-- END CONFIG-DERIVED SCIENTIFIC ROLE PROJECTION -->"


def _resolve_role(field_roles: dict, role: str) -> str:
    group, key = role.split(".", 1)
    return str(field_roles[group][key])


def render_projection(root: Path) -> str:
    analysis = yaml.safe_load((root / "config" / "analysis_contract.yml").read_text(encoding="utf-8"))
    output = yaml.safe_load((root / "config" / "output_contract.yml").read_text(encoding="utf-8"))
    realised = yaml.safe_load(
        (root / "data" / "authorities" / "rq3" / "realised_run_metadata.json").read_text(encoding="utf-8")
    )
    figures = yaml.safe_load((root / "config" / "figure_contract.yml").read_text(encoding="utf-8"))
    fr = analysis["field_roles"]
    rq2 = analysis["research_questions"]["rq2"]
    rq3 = analysis["research_questions"]["rq3"]
    sec = analysis["secondary_analysis"]

    focal = [p for p in rq3["predictors"] if p["role"] == "focal"]
    adjustments = [p for p in rq3["predictors"] if p["role"] == "adjustment"]
    factors = rq3["factors"]
    scenarios = {s["scenario_id"]: s for s in sec["scenarios"]}
    realised_design_columns = tuple(str(x) for x in realised["rq3_design_columns"])
    if not realised_design_columns:
        raise ValueError("RQ3 realised design authority contains no columns")

    pub_tables = output["publication_outputs"]["tables"]
    main_tables = [x["id"] for x in pub_tables if x["role"] == "manuscript"]
    supp_tables = [x["id"] for x in pub_tables if x["role"] == "supplementary"]
    main_figs = [x["id"] for x in figures["figures"] if x["role"] == "manuscript"]
    supp_figs = [x["id"] for x in figures["figures"] if x["role"] == "supplementary"]

    lines = [
        START,
        "## Executable scientific-role projection",
        "",
        "This section is generated from the executable configuration. It is a human-readable projection, not a second scientific authority.",
        "",
        "### RQ2 executable authority",
        "",
        "| Item | Configured value |",
        "|---|---|",
        f"| Effect estimator | `{rq2['effect_estimator']}` |",
        f"| Inferential test | `{rq2['inferential_test']['method']}` |",
        f"| Burned-area field | `{_resolve_role(fr, rq2['rate']['numerator_role'])}` |",
        f"| Fixed denominator | `{_resolve_role(fr, rq2['rate']['denominator_role'])}` |",
        f"| Denominator support | `{rq2['rate']['denominator_support']}` |",
        f"| Requires distinct realised observations | `{str(rq2['inferential_test']['reference_admissibility']['requires_distinct_observations']).lower()}` |",
        f"| On ties | `{rq2['inferential_test']['reference_admissibility']['on_ties']}` |",
        f"| Bandwidth rule | `{rq2['inferential_test']['bandwidth_rule']}` |",
        f"| Variance floor | `{rq2['inferential_test']['variance_floor']}` |",
        f"| Permutations | `{rq2['inferential_test']['permutations']}` |",
        f"| p-value method | `{rq2['inferential_test']['p_value_method']}` |",
        f"| Multiple-testing method | `{rq2['multiple_testing']['method']}` |",
        f"| Multiple-testing family size | `{rq2['multiple_testing']['family_size']}` |",
        "| Additional denominator analysis | `none` |",
        "",
        "### RQ3 executable field roles",
        "",
        "Population construction and regression design are distinct. A field used to establish support or VIIRS positivity does not automatically enter the regression matrix.",
        "",
        "| Role class | Configured field(s) |",
        "|---|---|",
        f"| Population/support | `{fr['rq3']['viirs_support']}`, `{fr['rq3']['ba2012_support']}`, `{fr['rq3']['viirs_presence']}` |",
        f"| Outcome component | `{_resolve_role(fr, rq3['outcome']['burned_area_presence_role'])}` |",
        f"| Focal predictors | {', '.join('`'+_resolve_role(fr,p['field_role'])+'`' for p in focal)} |",
        f"| Continuous adjustment predictor | {', '.join('`'+_resolve_role(fr,p['field_role'])+'`' for p in adjustments)} |",
        f"| Categorical adjustments | {', '.join('`'+_resolve_role(fr,f['field_role'])+'`' for f in factors)} |",
        "",
        "| Model property | Configured value |",
        "|---|---|",
        f"| Estimator | `{rq3['estimator']}` |",
        f"| Working correlation | `{rq3['working_correlation']}` |",
        f"| Covariance | `{rq3['covariance']}` |",
        f"| Coefficient reference | `{rq3['reference_distribution']}` |",
        f"| Month reference | `{factors[0]['reference_label']}` (`{factors[0]['reference']}`) |",
        f"| Year reference | `{factors[1]['reference_label']}` |",
        f"| ACZ reference | `{factors[2]['reference_label']}` (`{factors[2]['reference']}`) |",
        f"| Excluded predictor roles | {', '.join('`'+x+'`' for x in rq3['excluded_predictor_roles'])} |",
        f"| Realised design | `{len(realised_design_columns)} columns` |",
        "",
        "### Secondary SaTScan executable authority",
        "",
        "| Item | Configured value |",
        "|---|---|",
        f"| MCD model | `{scenarios['MCD64A1_POISSON_PRIMARY']['model']}` |",
        f"| MCD exposure role | `{scenarios['MCD64A1_POISSON_PRIMARY']['exposure_role']}` |",
        f"| VIIRS model | `{scenarios['VIIRS_STP_PRIMARY']['model']}` |",
        f"| VIIRS exposure | `{'null' if scenarios['VIIRS_STP_PRIMARY']['exposure_role'] is None else scenarios['VIIRS_STP_PRIMARY']['exposure_role']}` |",
        f"| Maximum spatial size | `{sec['common']['max_spatial_percent']}%` |",
        f"| Maximum temporal length | `{sec['common']['max_temporal_months']} months` |",
        f"| Monte Carlo replications | `{sec['common']['monte_carlo_replicates']}` |",
        f"| Reporting method | `{sec['common']['reporting_method']}` |",
        f"| Geographical overlap | `{str(sec['common']['geographical_overlap']).lower()}` |",
        f"| Gini-optimised reporting | `{str(sec['common']['gini_optimised_reporting']).lower()}` |",
        "",
        "### Publication contract projection",
        "",
        f"- Main tables: **{len(main_tables)}** — {', '.join('`'+x+'`' for x in main_tables)}.",
        "- External manuscript Figure 1: author supplied; no runtime asset or generated-output requirement.",
        f"- Generated main figures: **{len(main_figs)}** — {', '.join('`'+x+'`' for x in main_figs)}.",
        f"- Supplementary tables: **{len(supp_tables)}** — {', '.join('`'+x+'`' for x in supp_tables)}.",
        f"- Supplementary figures: **{len(supp_figs)}** — {', '.join('`'+x+'`' for x in supp_figs)}.",
        END,
    ]
    return "\n".join(lines)


def update_document(root: Path, *, check: bool) -> None:
    path = root / "docs" / "Data_Contract.md"
    text = path.read_text(encoding="utf-8")
    projection = render_projection(root)
    if START in text or END in text:
        if START not in text or END not in text:
            raise SystemExit("Data_Contract.md has an incomplete generated-section marker pair")
        before, rest = text.split(START, 1)
        _, after = rest.split(END, 1)
        expected = before.rstrip() + "\n\n" + projection + "\n" + after.lstrip("\n")
    else:
        anchor = "## Secondary SaTScan fields"
        if anchor not in text:
            raise SystemExit(f"Data_Contract.md is missing anchor: {anchor}")
        before, after = text.split(anchor, 1)
        expected = before.rstrip() + "\n\n" + projection + "\n\n" + anchor + after
    if check:
        if text != expected:
            raise SystemExit("Data_Contract.md executable-role projection is not synchronised with configuration")
    else:
        path.write_text(expected, encoding="utf-8", newline="\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    update_document(root, check=args.check)
    print("RP1_DATA_CONTRACT_ROLE_PROJECTION=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
