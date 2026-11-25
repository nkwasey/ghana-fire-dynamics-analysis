"""Standard-library atomic publication for local RP1 directory bundles."""
from __future__ import annotations

import base64
import errno
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from typing import Callable


class PublicationError(ValueError):
    """The filesystem cannot safely publish a new directory."""


def _is_wsl() -> bool:
    try:
        return 'microsoft' in Path('/proc/sys/kernel/osrelease').read_text().lower()
    except OSError:
        return False


def _wsl_windows_path(path: Path) -> str:
    # Resolve parent symlinks in Linux, but never follow the final component:
    # an existing destination symlink must remain an existing destination.
    absolute = path.parent.resolve() / path.name
    if any(ord(char) < 32 for char in str(absolute)):
        raise PublicationError(f'WSL publication path contains a control character: {absolute!s}')
    try:
        result = subprocess.run(['wslpath', '-w', str(absolute)], check=True,
                                capture_output=True, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise PublicationError(f'Cannot translate WSL publication path {absolute}: {exc}') from exc
    windows_path = result.stdout.rstrip('\r\n')
    # Exclude WSL's \\wsl.localhost UNC paths and remote shares. This fallback
    # is only for Windows drive paths and does not copy between filesystems.
    if not re.match(r'^[A-Za-z]:\\', windows_path):
        raise PublicationError(f'WSL publication path is not a Windows drive path: {absolute}')
    for part in windows_path[3:].split('\\'):
        if (not part or part[-1] in ' .'
                or any(char in '<>:"|?*' or ord(char) < 32 for char in part)
                or re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)', part, re.I)):
            raise PublicationError(f'WSL publication path is not unambiguous to Windows: {absolute}')
    return windows_path


def _publish_wsl_windows_drive(staging: Path, target: Path) -> None:
    """Use Win32 MoveFileW for a non-replacing rename on a WSL Windows drive."""
    source = _wsl_windows_path(staging)
    destination = _wsl_windows_path(target)
    if source[:2].lower() != destination[:2].lower():
        raise PublicationError('WSL publication source and destination are on different drives')

    # Encode values separately to avoid treating paths as PowerShell code, and
    # encode the script as required by Windows PowerShell -EncodedCommand.
    def literal(value: str) -> str:
        encoded = base64.b64encode(value.encode('utf-8')).decode('ascii')
        return "[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('" + encoded + "'))"

    script = r'''
$ErrorActionPreference = 'Stop'
try {
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class Rp1MoveFile {
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true, ExactSpelling = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool MoveFileW(string source, string destination);
}
'@
''' + '\n$source = ' + literal(source) + '\n$destination = ' + literal(destination) + r'''
if (-not [Rp1MoveFile]::MoveFileW($source, $destination)) {
    $errorCode = [Runtime.InteropServices.Marshal]::GetLastWin32Error()
    [Console]::Error.WriteLine("MoveFileW failed with Windows error " + $errorCode)
    exit 1
}
exit 0
} catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    exit 1
}
'''
    encoded_script = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        result = subprocess.run(['powershell.exe', '-NoLogo', '-NoProfile', '-NonInteractive',
                                 '-EncodedCommand', encoded_script],
                                capture_output=True, text=True, errors='replace')
    except OSError as exc:
        raise PublicationError(f'Cannot start Windows publication via WSL interoperability: {exc}') from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).strip()
        raise PublicationError(f'Windows non-replacing directory move failed: {detail or result.returncode}')


def publish_directory_no_replace(staging: Path, target: Path) -> None:
    """Atomically publish on Windows/Linux, refusing every existing destination."""
    if os.name == "nt":
        try:
            os.rename(staging, target)
        except OSError as exc:
            raise PublicationError(
                f"Cannot publish output directory without replacement ({staging} -> {target}): {exc}. "
                "Use a filesystem supporting atomic non-replacing directory rename."
            ) from exc
        return
    if not sys.platform.startswith("linux"):
        raise PublicationError("Atomic non-replacing directory publication is supported on Linux and Windows only")
    import ctypes
    library = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(library, "renameat2", None)
    if renameat2 is None:
        error = errno.ENOSYS
    else:
        renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
        renameat2.restype = ctypes.c_int
        if renameat2(-100, os.fsencode(staging), -100, os.fsencode(target), 1) == 0:
            return
        error = ctypes.get_errno()
    if error in (errno.EINVAL, errno.EOPNOTSUPP, errno.ENOSYS) and _is_wsl():
        try:
            _publish_wsl_windows_drive(staging, target)
            return
        except PublicationError as exc:
            raise PublicationError(
                f'Linux non-replacing rename failed ({os.strerror(error)}, errno {error}); '
                f'WSL Windows-drive publication also failed: {exc}. '
                'Check WSL interoperability or use an output directory on a supported filesystem.'
            ) from exc
    if error:
        hint = (
            " The filesystem may not support RENAME_NOREPLACE; on WSL, use an output "
            "directory on the native Linux filesystem (for example under your Linux home)."
            if error in (errno.EINVAL, errno.EOPNOTSUPP, errno.ENOSYS) else ""
        )
        raise PublicationError(
            f"Cannot publish output directory without replacement ({staging} -> {target}): "
            f"{os.strerror(error)} (errno {error}).{hint}"
        )


def preflight_directory_publication(
    target: Path, *, publisher: Callable[[Path, Path], None] | None = None,
) -> None:
    """Probe publication and collision protection on the intended filesystem."""
    publish = publisher or publish_directory_no_replace
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".publication-probe-", dir=target.parent) as probe:
        probe_dir = Path(probe)
        source = probe_dir / "source"
        source.mkdir()
        try:
            publish(source, probe_dir / "destination")
        except (ValueError, OSError) as exc:
            raise PublicationError(f"Output publication preflight failed for {target}: {exc}") from exc
        source = probe_dir / "collision-source"
        existing = probe_dir / "collision-destination"
        source.mkdir()
        existing.mkdir()
        (source / "source-marker").write_text("source", encoding="utf-8")
        try:
            publish(source, existing)
        except (ValueError, OSError):
            if not ((source / "source-marker").is_file() and existing.is_dir() and not any(existing.iterdir())):
                raise PublicationError(f"Output publication preflight failed for {target}: existing destination was modified")
        else:
            raise PublicationError(f"Output publication preflight failed for {target}: existing destination was not protected")
