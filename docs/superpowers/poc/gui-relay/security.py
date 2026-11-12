#!/usr/bin/env python3
"""Prototype-only file and socket path hardening.

This module is not production HAIBOX code. It exists so the disposable GUI
prototype fails closed when its state directory or password file is not owned
and writable only by the current user.
"""

from __future__ import annotations

import contextlib
import os
import stat
from pathlib import Path

PRIVATE_DIRECTORY_MODE = 0o700
PASSWORD_FILE_MODE = 0o600


class SecurityError(RuntimeError):
    """A safe, operator-facing prototype security failure."""


def _absolute(path: Path | str) -> Path:
    return Path(path).expanduser().absolute()


def ensure_private_directory(path: Path | str, *, create: bool = False) -> Path:
    """Return an absolute owner-controlled 0700 directory or fail closed."""

    target = _absolute(path)
    if create:
        try:
            target.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=False)
        except FileExistsError:
            pass
        except OSError as exc:
            raise SecurityError(f"cannot create private directory {target}: {exc}") from exc

    try:
        info = target.lstat()
    except OSError as exc:
        raise SecurityError(f"cannot stat private directory {target}: {exc}") from exc

    if stat.S_ISLNK(info.st_mode):
        raise SecurityError(f"private directory {target} is a symlink")
    if not stat.S_ISDIR(info.st_mode):
        raise SecurityError(f"private directory {target} is not a directory")
    if info.st_uid != os.getuid():
        raise SecurityError(f"private directory {target} is not owned by uid {os.getuid()}")
    if stat.S_IMODE(info.st_mode) != PRIVATE_DIRECTORY_MODE:
        raise SecurityError(
            f"private directory {target} must have mode 0700, "
            f"not {stat.S_IMODE(info.st_mode):04o}"
        )
    return target


def _remove_existing_regular_file(target: Path) -> None:
    try:
        info = target.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode):
        raise SecurityError(f"refusing to replace symlink {target}")
    if not stat.S_ISREG(info.st_mode):
        raise SecurityError(f"refusing to replace non-regular file {target}")
    target.unlink()


def write_password_file(path: Path | str, password: str) -> Path:
    """Create a 0600 password file in a verified private directory.

    The final path is removed first only when it is a regular file. A symlink,
    directory, or other special file is rejected. The new file is created with
    ``O_EXCL`` and ``O_NOFOLLOW`` and its mode, owner, and type are rechecked.
    """

    if not password:
        raise SecurityError("refusing to write an empty password")

    target = _absolute(path)
    parent = ensure_private_directory(target.parent, create=True)
    target = parent / target.name
    _remove_existing_regular_file(target)

    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_NOFOLLOW", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    fd = os.open(target, flags, PASSWORD_FILE_MODE)
    try:
        os.fchmod(fd, PASSWORD_FILE_MODE)
        payload = password.encode("utf-8")
        offset = 0
        while offset < len(payload):
            offset += os.write(fd, payload[offset:])
        os.fsync(fd)
    except BaseException:
        with contextlib.suppress(OSError):
            os.close(fd)
        with contextlib.suppress(OSError):
            target.unlink()
        raise
    else:
        os.close(fd)

    info = target.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        with contextlib.suppress(OSError):
            target.unlink()
        raise SecurityError(f"password file {target} is not a regular file")
    if info.st_uid != os.getuid():
        with contextlib.suppress(OSError):
            target.unlink()
        raise SecurityError(f"password file {target} is not owned by uid {os.getuid()}")
    if stat.S_IMODE(info.st_mode) != PASSWORD_FILE_MODE:
        with contextlib.suppress(OSError):
            target.unlink()
        raise SecurityError(
            f"password file {target} must have mode 0600, "
            f"not {stat.S_IMODE(info.st_mode):04o}"
        )
    return target


def remove_password_file(path: Path | str) -> bool:
    """Remove a password file without following a final symlink."""

    target = _absolute(path)
    try:
        info = target.lstat()
    except FileNotFoundError:
        return False
    if stat.S_ISDIR(info.st_mode):
        raise SecurityError(f"refusing to remove directory {target}")
    target.unlink()
    return True
