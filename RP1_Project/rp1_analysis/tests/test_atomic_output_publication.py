"""Atomic output publication retains no-overwrite on Windows and POSIX."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
from threading import Barrier

import pytest

from rp1_analysis_v1 import outputs


def test_publication_does_not_require_an_unsafe_platform_primitive(tmp_path, monkeypatch):
    # A Windows filesystem may deny hard links; POSIX rename may overwrite.
    disallowed = "link" if os.name == "nt" else "rename"

    def reject(*args, **kwargs):
        raise AssertionError(f"No-overwrite publication must not use {disallowed} on this platform")

    monkeypatch.setattr(outputs.os, disallowed, reject)
    destination = tmp_path / "authority.json"
    payload = b'{"valid":true}\n'
    outputs._atomic_write_bytes(destination, payload, overwrite=False)
    assert destination.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [destination]


def test_destination_created_during_publication_is_preserved(tmp_path, monkeypatch):
    destination = tmp_path / "authority.csv"
    primitive = "rename" if os.name == "nt" else "link"
    publish = getattr(outputs.os, primitive)
    competing = b"independent winner\n"

    def competing_writer(source, target):
        # The destination was absent during the writer's initial check.
        assert not Path(target).exists()
        assert Path(source).read_bytes() == b"losing candidate\n"
        Path(target).write_bytes(competing)
        return publish(source, target)

    monkeypatch.setattr(outputs.os, primitive, competing_writer)
    with pytest.raises(FileExistsError):
        outputs._atomic_write_bytes(destination, b"losing candidate\n", overwrite=False)
    assert destination.read_bytes() == competing
    assert list(tmp_path.iterdir()) == [destination]


def test_concurrent_publication_has_one_complete_winner(tmp_path):
    destination = tmp_path / "authority.bin"
    payloads = [bytes([index]) * 131072 for index in range(8)]
    barrier = Barrier(len(payloads))

    def attempt(payload):
        barrier.wait(timeout=10)
        try:
            outputs._atomic_write_bytes(destination, payload, overwrite=False)
        except FileExistsError:
            return False
        return True

    with ThreadPoolExecutor(max_workers=len(payloads)) as pool:
        results = list(pool.map(attempt, payloads))
    assert sum(results) == 1
    assert destination.read_bytes() == payloads[results.index(True)]
    assert list(tmp_path.iterdir()) == [destination]


def test_explicit_overwrite_replaces_complete_payload(tmp_path):
    destination = tmp_path / "authority.txt"
    destination.write_bytes(b"original")
    payload = b"replacement\n" * 65536
    outputs._atomic_write_bytes(destination, payload, overwrite=True)
    assert destination.read_bytes() == payload
    assert list(tmp_path.iterdir()) == [destination]


def test_publication_failure_cleans_staging_and_preserves_original(tmp_path, monkeypatch):
    destination = tmp_path / "authority.json"
    destination.write_bytes(b"original\n")

    def fail(source, target):
        assert Path(source).read_bytes() == b"replacement\n"
        raise PermissionError("publication denied")

    monkeypatch.setattr(outputs.os, "replace", fail)
    with pytest.raises(PermissionError, match="publication denied"):
        outputs._atomic_write_bytes(destination, b"replacement\n", overwrite=True)
    assert destination.read_bytes() == b"original\n"
    assert list(tmp_path.iterdir()) == [destination]


@pytest.mark.parametrize("writer_kind", ["configuration", "presentation"])
def test_sibling_authority_writers_preserve_collision_contract(tmp_path, writer_kind):
    if writer_kind == "configuration":
        from rp1_analysis_v1.config import _atomic_create_text
        write = lambda text: _atomic_create_text(tmp_path / "authority.json", text)
        collision = FileExistsError
    else:
        from rp1_analysis_v1.presentation_export import PresentationOutputError, PresentationOutputWriter
        writer = PresentationOutputWriter(tmp_path)
        write = lambda text: writer.write_text("authority.json", text)
        collision = PresentationOutputError
    write("first\n")
    with pytest.raises(collision):
        write("second\n")
    assert (tmp_path / "authority.json").read_bytes() == b"first\n"
    assert list(tmp_path.iterdir()) == [tmp_path / "authority.json"]
