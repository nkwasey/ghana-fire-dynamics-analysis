from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]
DOMAIN_MODULES=(
    'spatial_scale.py','trend_robustness.py','observability.py','seasonality.py','spatial_stats.py','gee.py'
)
NUMBERED_SOURCE=re.compile(r'^[tfs]\d+_source$',re.I)
NUMBERED_BUILD=re.compile(r'^_build_[tfs]\d+',re.I)
NUMBERED_COLUMNS=re.compile(r'^[TFS]\d+_COLUMNS$')
BANNED_COMPATIBILITY_PHRASES=(
    'Backward-compatible alias',
    'Compatibility accessor for the former',
    'Compatibility entry point',
    'Compatibility projection for older',
    'Kept for compatibility',
    'Compatibility fields are retained',
    'backwards compatibility',
    'backward compatibility',
    'legacy test fixture',
    'repository transitions',
)

def test_domain_modules_expose_no_publication_numbered_scientific_api() -> None:
    src=ROOT/'src/rp1_analysis_v1'
    offenders=[]
    for name in DOMAIN_MODULES:
        path=src/name; tree=ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                token=node.name
                if NUMBERED_SOURCE.match(token) or NUMBERED_BUILD.match(token) or NUMBERED_COLUMNS.match(token):
                    offenders.append(f'{name}:{token}')
            elif isinstance(node,(ast.Assign,ast.AnnAssign)):
                targets=node.targets if isinstance(node,ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target,ast.Name):
                        token=target.id
                        if NUMBERED_SOURCE.match(token) or NUMBERED_BUILD.match(token) or NUMBERED_COLUMNS.match(token):
                            offenders.append(f'{name}:{token}')
    assert not offenders, offenders

def test_production_code_has_no_unexplained_migration_compatibility_wording() -> None:
    roots=[ROOT/'src',REPO/'geo_data_prep/src',REPO/'RP1_Project/rp1_mv_firms_panels/src']
    offenders=[]
    for base in roots:
        for path in base.rglob('*.py'):
            text=path.read_text(encoding='utf-8')
            for phrase in BANNED_COMPATIBILITY_PHRASES:
                if phrase.casefold() in text.casefold():
                    offenders.append(f'{path.relative_to(REPO)}: {phrase}')
    assert not offenders, offenders
