"""Validate declared study calendars before any workflow state is created."""
from __future__ import annotations

DEFAULT_STUDY = {
    'start_yyyymm': 200101, 'end_yyyymm': 202412,
    'viirs_support_start_yyyymm': 201201, 'ba2012_support_start_yyyymm': 201201,
    'analysis_overlap_start_yyyymm': 201202,
}


def validate_study(study: dict) -> dict:
    if not isinstance(study, dict) or set(study) - set(DEFAULT_STUDY):
        raise ValueError('Study must contain only declared calendar settings')
    if not {'start_yyyymm', 'end_yyyymm'} <= set(study):
        raise ValueError('Study requires start_yyyymm and end_yyyymm')
    resolved = DEFAULT_STUDY | study
    for key, value in resolved.items():
        if type(value) is not int or not 100001 <= value <= 999912 or not 1 <= value % 100 <= 12:
            raise ValueError('Invalid study month: ' + key)
    if resolved['start_yyyymm'] > resolved['end_yyyymm']:
        raise ValueError('Reversed study window')
    if resolved['start_yyyymm'] % 100 != 1 or resolved['end_yyyymm'] % 100 != 12:
        raise ValueError('The scientific workflow requires complete calendar years')
    for key in ('viirs_support_start_yyyymm', 'ba2012_support_start_yyyymm', 'analysis_overlap_start_yyyymm'):
        if resolved[key] > resolved['end_yyyymm']:
            raise ValueError('Required source or paired analysis begins after the study end: ' + key)
    return resolved


def analysis_run_id(workflow_id: str, profile: str = 'c3') -> str:
    """Keep an existing final profile suffix and otherwise add it once."""
    suffix = '_' + profile
    return workflow_id if workflow_id.endswith(suffix) else workflow_id + suffix
