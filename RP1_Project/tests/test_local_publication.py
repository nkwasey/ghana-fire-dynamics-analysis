"""Publication must remain atomic and reject collisions on each backend."""
import ctypes
import errno
from concurrent.futures import ThreadPoolExecutor

import pytest

from RP1_Project import rp1_local_io as publication


class FakeRename:
    def __init__(self, error):
        self.error = error

    def __call__(self, *_args):
        ctypes.set_errno(self.error)
        return -1


@pytest.mark.parametrize('error', [errno.EINVAL, errno.EOPNOTSUPP, errno.ENOSYS])
def test_wsl_fallback_only_for_unsupported_linux_rename(tmp_path, monkeypatch, error):
    class Library:
        renameat2 = FakeRename(error)
    calls = []
    monkeypatch.setattr(ctypes, 'CDLL', lambda *args, **kwargs: Library())
    monkeypatch.setattr(publication, '_is_wsl', lambda: True)
    monkeypatch.setattr(publication, '_publish_wsl_windows_drive', lambda source, dest: calls.append((source, dest)))
    monkeypatch.setattr(publication.os, 'name', 'posix')
    monkeypatch.setattr(publication.sys, 'platform', 'linux')
    source, target = tmp_path/'source', tmp_path/'target'
    publication.publish_directory_no_replace(source, target)
    assert calls == [(source, target)]


def test_linux_collision_never_invokes_wsl_fallback(tmp_path, monkeypatch):
    class Library:
        renameat2 = FakeRename(errno.EEXIST)
    monkeypatch.setattr(ctypes, 'CDLL', lambda *args, **kwargs: Library())
    monkeypatch.setattr(publication, '_is_wsl', lambda: True)
    monkeypatch.setattr(publication, '_publish_wsl_windows_drive', lambda *args: pytest.fail('unsafe fallback'))
    monkeypatch.setattr(publication.os, 'name', 'posix')
    monkeypatch.setattr(publication.sys, 'platform', 'linux')
    with pytest.raises(publication.PublicationError, match='errno'):
        publication.publish_directory_no_replace(tmp_path/'source', tmp_path/'target')


def test_unavailable_wsl_interop_fails_closed(tmp_path, monkeypatch):
    class Library:
        renameat2 = FakeRename(errno.EINVAL)
    def unavailable(*args):
        raise publication.PublicationError('interop unavailable')
    monkeypatch.setattr(ctypes, 'CDLL', lambda *args, **kwargs: Library())
    monkeypatch.setattr(publication, '_is_wsl', lambda: True)
    monkeypatch.setattr(publication, '_publish_wsl_windows_drive', unavailable)
    monkeypatch.setattr(publication.os, 'name', 'posix')
    monkeypatch.setattr(publication.sys, 'platform', 'linux')
    with pytest.raises(publication.PublicationError, match='interop unavailable'):
        publication.publish_directory_no_replace(tmp_path/'source', tmp_path/'target')


def test_wsl_translation_refuses_linux_unc_paths(tmp_path, monkeypatch):
    class Result:
        stdout = '\\\\wsl.localhost\\Ubuntu\\home\\target\n'
    monkeypatch.setattr(publication.subprocess, 'run', lambda *args, **kwargs: Result())
    with pytest.raises(publication.PublicationError, match='not a Windows drive path'):
        publication._wsl_windows_path(tmp_path/'target')


@pytest.mark.parametrize('windows_path', [
    'C:\\data\\target.\n', 'C:\\data\\target \n', 'C:\\data\\NUL.txt\n',
    'C:\\data\\bad?name\n',
])
def test_wsl_translation_refuses_ambiguous_windows_names(tmp_path, monkeypatch, windows_path):
    class Result:
        stdout = windows_path
    monkeypatch.setattr(publication.subprocess, 'run', lambda *args, **kwargs: Result())
    with pytest.raises(publication.PublicationError, match='not unambiguous'):
        publication._wsl_windows_path(tmp_path/'target')


@pytest.mark.skipif(not publication._is_wsl(), reason='requires WSL interoperability')
def test_wsl_windows_drive_move_collision_and_race(tmp_path):
    try:
        publication._wsl_windows_path(tmp_path/'probe')
    except publication.PublicationError:
        pytest.skip('requires a Windows drive mounted in WSL')
    root = tmp_path / 'spaces $ unicode é'
    root.mkdir()
    source = root/'source'; source.mkdir(); (source/'marker').write_text('original')
    target = root/'target'
    publication._publish_wsl_windows_drive(source, target)
    assert (target/'marker').read_text() == 'original' and not source.exists()

    for existing in ('empty', 'file'):
        source = root/('source-'+existing); source.mkdir(); (source/'marker').write_text('new')
        destination = root/existing
        if existing == 'empty': destination.mkdir()
        else: destination.write_text('original')
        with pytest.raises(publication.PublicationError):
            publication._publish_wsl_windows_drive(source, destination)
        assert (source/'marker').read_text() == 'new'
        if existing == 'empty': assert list(destination.iterdir()) == []
        else: assert destination.read_text() == 'original'

    source = root/'source-link'; source.mkdir(); (source/'marker').write_text('new')
    destination = root/'existing-link'
    destination.symlink_to(root/'missing', target_is_directory=True)
    with pytest.raises(publication.PublicationError):
        publication._publish_wsl_windows_drive(source, destination)
    assert destination.is_symlink() and (source/'marker').read_text() == 'new'
    assert not (root/'missing').exists()

    sources = [root/'race-1', root/'race-2']
    for i, source in enumerate(sources):
        source.mkdir(); (source/'marker').write_text(str(i))
    destination = root/'race-result'
    def attempt(source):
        try:
            publication._publish_wsl_windows_drive(source, destination)
            return True
        except publication.PublicationError:
            return False
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(attempt, sources))
    assert sum(results) == 1
    assert (destination/'marker').read_text() == str(results.index(True))
    assert (sources[results.index(False)]/'marker').is_file()


@pytest.mark.skipif(not publication._is_wsl(), reason='requires WSL interoperability')
def test_wsl_mounted_drive_preflight(tmp_path):
    try:
        publication._wsl_windows_path(tmp_path/'probe')
    except publication.PublicationError:
        pytest.skip('requires a Windows drive mounted in WSL')
    publication.preflight_directory_publication(tmp_path/'published')
    assert list(tmp_path.iterdir()) == []
