"""Document navigation must validate fragments as well as existing files."""
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('link_checker_tests', ROOT / 'tools/documentation_links.py')
LINKS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(LINKS)


@pytest.mark.parametrize('fragment', ['missing-section', 'hidden-example', 'fake-anchor'])
def test_existing_file_does_not_make_a_missing_fragment_valid(tmp_path, fragment):
    target = tmp_path / 'guide.md'
    target.write_text('# Real section\n\n```markdown\n## Hidden example\n<a id="fake-anchor"></a>\n```\n', encoding='utf-8')
    source = tmp_path / 'README.md'
    source.write_text(f'[Guide](guide.md#{fragment})\n', encoding='utf-8')
    assert LINKS.local_link_issues(source) == [
        {'line': 1, 'target': 'guide.md#' + fragment, 'reason': 'missing fragment'}]


@pytest.mark.parametrize('fragment', ['real-section', 'real-section-1', 'explicit-anchor',
                                     'named-anchor', 'set-up-map_key', 'setext-heading'])
def test_heading_and_explicit_anchor_targets_resolve(tmp_path, fragment):
    (tmp_path / 'guide.md').write_text(
        '# Real section\n# Real section\n## Set up `MAP_KEY`\n'
        '<a id="explicit-anchor"></a>\n<a name="named-anchor"></a>\n\n'
        'Setext heading\n--------------\n', encoding='utf-8')
    source = tmp_path / 'README.md'
    source.write_text(f'[Guide](guide.md#{fragment})\n', encoding='utf-8')
    assert LINKS.local_link_issues(source) == []


def test_reference_links_and_percent_encoded_paths_are_checked(tmp_path):
    (tmp_path / 'key guide.md').write_text('# Setup\n', encoding='utf-8')
    source = tmp_path / 'README.md'
    source.write_text('[Key setup][key]\n\n[key]: key%20guide.md#setup\n', encoding='utf-8')
    assert LINKS.local_link_issues(source) == []
    source.write_text('[Key setup][key]\n\n[key]: key%20guide.md#absent\n', encoding='utf-8')
    assert LINKS.local_link_issues(source)[0]['reason'] == 'missing fragment'


def test_local_fragments_and_missing_files_are_checked(tmp_path):
    source = tmp_path / 'README.md'
    source.write_text('# Start\n[Here](#start)\n[Absent](#absent)\n[File](missing.md)\n', encoding='utf-8')
    assert [item['reason'] for item in LINKS.local_link_issues(source)] == ['missing fragment', 'missing file']


def test_code_examples_are_not_treated_as_navigation(tmp_path):
    source = tmp_path / 'README.md'
    source.write_text('`[Inline](missing.md#absent)`\n\n```text\n[Example](missing.md#absent)\n```\n', encoding='utf-8')
    assert LINKS.local_link_issues(source) == []
