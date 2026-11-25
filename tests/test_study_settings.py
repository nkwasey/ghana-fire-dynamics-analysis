"""Scientific run calendars and identifiers have explicit, reproducible inputs."""
import importlib.util
from pathlib import Path
import pytest

spec = importlib.util.spec_from_file_location('study_settings_test', Path(__file__).resolve().parents[1]/'tools/study_settings.py')
settings = importlib.util.module_from_spec(spec)
spec.loader.exec_module(settings)


def test_current_and_extended_studies_preserve_independent_support_starts():
    current = settings.validate_study({'start_yyyymm': 200101, 'end_yyyymm': 202412})
    extended = settings.validate_study(dict(current, end_yyyymm=202512))
    assert current == settings.DEFAULT_STUDY
    assert {k:v for k,v in current.items() if k != 'end_yyyymm'} == {k:v for k,v in extended.items() if k != 'end_yyyymm'}


@pytest.mark.parametrize('changes', [
    {'end_yyyymm': 202413}, {'start_yyyymm': 202501}, {'end_yyyymm': 202411},
    {'start_yyyymm': True}, {'analysis_overlap_start_yyyymm': 202501},
    {'accidental_setting': 202401},
])
def test_invalid_or_incomplete_year_contract_is_rejected(changes):
    with pytest.raises(ValueError):
        settings.validate_study(settings.DEFAULT_STUDY | changes)


@pytest.mark.parametrize('workflow,expected', [
    ('rp1_submission_c3', 'rp1_submission_c3'), ('study', 'study_c3'),
    ('study_c3_notes', 'study_c3_notes_c3'),
])
def test_profile_identity_is_added_once_without_stripping_identifiers(workflow, expected):
    assert settings.analysis_run_id(workflow) == expected
