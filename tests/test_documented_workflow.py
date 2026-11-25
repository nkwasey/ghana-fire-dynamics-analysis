"""Check that the main runbook agrees with the executable public interfaces.

These checks inspect source declarations and prose; they do not acquire data,
execute workflow stages, read credentials or assert scientific outcomes.
"""
from __future__ import annotations

import ast
import importlib.util
import json
from pathlib import Path
import re
import shlex

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"
LINK_SPEC = importlib.util.spec_from_file_location(
    'documented_workflow_links', ROOT / 'tools/documentation_links.py')
LINKS = importlib.util.module_from_spec(LINK_SPEC)
LINK_SPEC.loader.exec_module(LINKS)


def readme() -> str:
    return README.read_text(encoding="utf-8")


def public_workflow_arguments() -> tuple[set[str], set[str]]:
    tree = ast.parse((ROOT / "tools/run_workflow.py").read_text(encoding="utf-8"))
    flags, steps = set(), set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "add_argument"):
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                if arg.value.startswith("--"):
                    flags.add(arg.value)
                elif arg.value == "step":
                    for keyword in node.keywords:
                        if keyword.arg == "choices":
                            steps.update(ast.literal_eval(keyword.value))
    assert steps, "The workflow's declared public steps could not be inspected"
    return flags, steps


def test_readme_contains_one_ordered_five_stage_route():
    headings = re.findall(r"^## (.+)$", readme(), flags=re.MULTILINE)
    assert headings == [
        "Inputs and configuration", "Environment",
        "Stage 1: Prepare geography",
        "Stage 2: Admit burned-area exports",
        "Stage 3: Prepare active-fire panels",
        "Stage 4: Assemble the monthly panels",
        "Stage 5: Full analysis handoff and notebook",
        "Export presentation figures", "Testing and outputs",
    ]


def test_main_workflow_examples_use_real_cli_and_one_identity():
    flags, steps = public_workflow_arguments()
    commands = [shlex.split(line) for line in readme().splitlines()
                if line.startswith("python tools/run_workflow.py ")]
    assert [command[-1] for command in commands] == [
        "geo", "consolidate-ba", "archive-plan", "archive", "archive-admit",
        "firms", "merge", "analysis-inputs",
    ]
    for command in commands:
        assert command[-1] in steps
        assert {token for token in command if token.startswith("--")} <= flags
        assert command[command.index("--config") + 1] == "configs/workflow.json"
        assert command[command.index("--run-id") + 1] == "ghana_fire_study"


def test_stage_three_owns_both_firms_components():
    section = readme().split("## Stage 3: Prepare active-fire panels", 1)[1].split("## Stage 4:", 1)[0]
    assert "rp1_firms_archive" in section and "rp1_mv_firms_panels" in section
    stage_three_steps = ("archive-plan", "archive", "archive-admit", "firms")
    for step in stage_three_steps:
        assert re.search(r"^python tools/run_workflow\.py .+ " + step + r"$", section, re.MULTILINE)
    assert "[NASA FIRMS key setup](docs/FIRMS_KEY_SETUP.md)" in section
    assert "FIRMS_KEY_SETUP.md#" not in section
    sp_guide = (ROOT / "docs/FIRMS_SP_INPUTS.md").read_text(encoding="utf-8")
    first_use = sp_guide.split("## Prepare standard-processing inputs", 1)[1].split("## ", 1)[0]
    examples = [shlex.split(line) for line in first_use.splitlines()
                if line.startswith("python tools/run_workflow.py ")]
    assert tuple(example[-1] for example in examples) == stage_three_steps
    assert {example[example.index("--run-id") + 1] for example in examples} == {"ghana_fire_study"}


def test_documented_study_settings_equal_default_workflow():
    block = re.search(r"```json\n(.*?)\n```", readme(), re.DOTALL)
    assert block is not None
    documented = json.loads("{" + block.group(1) + "}")["study"]
    configured = json.loads((ROOT / "configs/workflow.json").read_text(encoding="utf-8"))["study"]
    assert documented == configured


def test_interactive_scan_route_precedes_controlled_alternative():
    section = readme().split("## Stage 5: Full analysis handoff and notebook", 1)[1].split("## Export presentation figures", 1)[0]
    assert section.index("RP1_NOTEBOOK_RUN_ID") < section.index("04-01")
    assert section.index("04-01") < section.index("04-02") < section.index("RESULTS_VALIDATED")
    assert section.index("restricted-burned-area-scan") < section.index("90 and 99")
    assert "validate_run.py --run-id ghana_fire_study" in section
    guide = (ROOT / "docs/ANALYSIS_EXECUTION.md").read_text(encoding="utf-8")
    assert "scripts/execute_notebook.py --run-id ghana_fire_study_controlled" in guide
    assert "--integrate-results" in guide
    for expected in ("MCD64A1_POISSON_PRIMARY.prm", "VIIRS_STP_PRIMARY.prm",
                     "out/runs/ghana_fire_study_sec", "<prefix>.col.txt",
                     "<prefix>.gis.txt", "EXTERNAL_RESULTS_REQUIRED",
                     "RP1_ANALYSIS_V1_RUN_VALIDATION=PASS"):
        assert expected in guide


def test_presentation_commands_follow_documented_analysis_identity():
    section = readme().split("## Export presentation figures", 1)[1].split("## Testing and outputs", 1)[0]
    commands = [shlex.split(line) for line in section.splitlines()
                if line.startswith("python scripts/export_presentation_figures.py ")]
    assert commands[0][-1] == "--list"
    for command in commands[1:]:
        assert command[command.index("--run-dir") + 1] == "out/runs/ghana_fire_study_close"
    assert "requires validated external SaTScan results" in section


def test_local_markdown_document_links_resolve():
    broken = []
    for path in ROOT.rglob("*.md"):
        if any(part in {"out", ".git", "dist", "build", "__pycache__", ".pytest_cache"} for part in path.relative_to(ROOT).parts):
            continue
        broken.extend((path.relative_to(ROOT).as_posix(), item)
                      for item in LINKS.local_link_issues(path))
    assert not broken, broken


def test_key_setup_is_local_and_does_not_print_the_key():
    guide = (ROOT / "docs/FIRMS_KEY_SETUP.md").read_text(encoding="utf-8")
    assert 'read -r -s -p "NASA FIRMS MAP_KEY: " FIRMS_MAP_KEY' in guide
    assert 'Read-Host "NASA FIRMS MAP_KEY" -AsSecureString' in guide
    assert "ZeroFreeBSTR" in guide
    assert "outside" in guide and "key_file" in guide
    assert "FIRMS_KEY_SETUP.md" in (ROOT / "docs/FIRMS_ARCHIVE_INTEGRATION.md").read_text(encoding="utf-8")
    assert "origin" in guide and "ENVIRONMENT_AND_RECOVERY.md" in guide
    assert not re.search(r"print\(os\.(?:getenv\(['\"]FIRMS_MAP_KEY|environ\[['\"]FIRMS_MAP_KEY)", guide)


def test_documentation_has_no_known_utf8_corruption():
    markers = ("\u00e2\u20ac", "\ufffd", "\u00ef\u00bb\u00bf")
    corrupted = []
    for path in ROOT.rglob("*.md"):
        if any(part in {"out", ".git", "dist", "build", ".pytest_cache"} for part in path.relative_to(ROOT).parts):
            continue
        text = path.read_text(encoding="utf-8")
        if any(marker in text for marker in markers):
            corrupted.append(path.relative_to(ROOT).as_posix())
    assert not corrupted, corrupted
