"""Archive-owned orchestration shared by the standalone CLI and RP1 workflow.

Configuration values and returned manifests retain their dictionary contracts.
Validation consumes an accepted archive without refreshing or repairing it.
"""
from __future__ import annotations

from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import tempfile

from . import core
from .core import ArchiveError, load_config
from .exports import export_annual, verify_annual
from .scientific import write_quality_sidecars, verify_quality_sidecars


@contextmanager
def writer_lock(*directories):
    """Serialize Archive writers to shared run and NASA cache directories.

Exclusive file creation works on Windows and POSIX. An abandoned lock is never
silently broken: confirm that its process has stopped before removing it.
"""
    with ExitStack() as stack:
        for root in sorted({Path(p).resolve() for p in directories}, key=str):
            root.mkdir(parents=True, exist_ok=True)
            path = root / '.archive-writer.lock'
            try:
                handle = path.open('x', encoding='utf-8')
            except FileExistsError:
                raise ArchiveError('Another archive writer holds the lock: ' + str(path)) from None
            stack.callback(path.unlink, missing_ok=True)
            with handle:
                json.dump({'pid': os.getpid()}, handle)
        yield


def make_plan(config, refresh=True):
    """Plan requested acquisitions under the shared output/cache writer lock."""
    with writer_lock(config['output'], config['downloads']):
        return core.make_plan(config, refresh)


def download(config, refresh=True):
    """Acquire or verify cache inputs; return the reusable download plan."""
    with writer_lock(config['output'], config['downloads']):
        return core.download(config, refresh)


def _restore(path, data):
    if data is None:
        path.unlink(missing_ok=True)
        return
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        handle.write(data)
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def prepare_and_export(config, plan=None):
    """Prepare, verify, publish annual exports, then publish sparse QA.

Return ``(manifest_dict, export_dict)``. Failed preparation/export retains the
previous accepted manifest/report and annual view. QA is derived after archive
acceptance: its failure leaves verified science/annual exports accepted so QA
can be retried. The complete run and shared cache are held by one writer.
"""
    with writer_lock(config['output'], config['downloads']):
        manifest = Path(config['output']) / 'archive-manifest.json'
        report = manifest.parent / 'verification.json'
        previous = {p: p.read_bytes() if p.exists() else None for p in (manifest, report)}
        try:
            result = core.prepare(config, plan)
            exported = export_annual(manifest, config['output'], verify_source=False)
        except BaseException:
            for path, data in previous.items():
                if path.parent.exists():
                    _restore(path, data)
            raise
        exported['quality_assurance'] = write_quality_sidecars(manifest, manifest.parent / 'qa')
        return result, exported


def validate_archive(manifest, verify_qa=True):
    """Read-only archive, annual-export and optional QA integrity validation.

Historical preparation and QA module hashes describe the producer and need not
equal this installation. QA is checked against current declared flag semantics;
the validator code identity is reported separately from producer provenance.
"""
    manifest = Path(manifest).resolve()
    root = manifest.parent
    locks = (root / '.archive-writer.lock', root / '.annual-export.lock', root / '.qa.qa.lock')
    if any(path.exists() for path in locks):
        raise ArchiveError('Archive publication is active; retry read-only validation after the writer finishes')
    identity = core.sha(manifest)
    result = core.verify(manifest, write_report=False)
    result['annual_exports'] = verify_annual(root, manifest)
    result['annual_exports']['annual_manifest_sha256'] = core.sha(root / 'annual/annual-export.json')
    if verify_qa:
        result['quality_assurance'] = verify_quality_sidecars(manifest, root / 'qa')
    if core.sha(manifest) != identity or any(path.exists() for path in locks):
        raise ArchiveError('Accepted archive changed during read-only validation')
    result['manifest_sha256'] = identity
    result['validator_code_sha256'] = {name: core.sha(Path(__file__).with_name(name)) for name in
                                     ('api.py', 'core.py', 'exports.py', 'scientific.py', 'semantic.py', 'acquisition.py')}
    return result
