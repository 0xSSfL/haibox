"""Session credential files for the GUI runtime.

The Xpra server authenticates with a per-session password that lives in a
mode-0600 file inside the container runtime and in a mode-0600 file on the
host.  Both copies are private to the operating-system user that runs the
session, and both are removed when the session ends.
"""

from __future__ import annotations

import os
import secrets
import stat
from pathlib import Path

from haibox.gui.errors import GuiCredentialError

PRIVATE_DIRECTORY_MODE = 0o700
PASSWORD_FILE_MODE = 0o600
PASSWORD_BYTES = 24


def generate_password(length: int = PASSWORD_BYTES) -> str:
    """Return a random, URL-safe session password."""

    if not 16 <= length <= 128:
        raise GuiCredentialError("session password length must be between 16 and 128")
    return secrets.token_urlsafe(length)


def ensure_private_directory(path: Path) -> Path:
    """Return an owner-controlled 0700 directory, creating it when needed."""

    target = Path(path).expanduser().absolute()
    try:
        target.mkdir(mode=PRIVATE_DIRECTORY_MODE, parents=True, exist_ok=True)
    except OSError as exc:
        raise GuiCredentialError(f"cannot create private directory {target}: {exc}") from exc
    try:
        info = target.lstat()
    except OSError as exc:
        raise GuiCredentialError(f"cannot inspect {target}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        raise GuiCredentialError(f"private directory must not be a symlink: {target}")
    if info.st_uid != os.getuid():
        raise GuiCredentialError(f"private directory is not owned by this user: {target}")
    if stat.S_IMODE(info.st_mode) != PRIVATE_DIRECTORY_MODE:
        raise GuiCredentialError(
            f"private directory must have mode 0700: {target}"
        )
    return target


def write_credential(path: Path, secret: str) -> None:
    """Create or replace a mode-0600 credential file.

    The file is created with ``O_EXCL`` and ``O_NOFOLLOW`` so a pre-existing
    symlink can never be followed, and it is created with the final mode so
    the secret is never briefly world-readable.
    """

    target = Path(path).expanduser().absolute()
    if not secret:
        raise GuiCredentialError("session credential must not be empty")
    ensure_private_directory(target.parent)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(target, flags, PASSWORD_FILE_MODE)
    except FileExistsError:
        _replace_regular_file(target, secret)
        return
    except OSError as exc:
        raise GuiCredentialError(f"cannot create credential file {target}: {exc}") from exc
    try:
        os.fchmod(fd, PASSWORD_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise GuiCredentialError(f"cannot write credential file {target}: {exc}") from exc


def _replace_regular_file(target: Path, secret: str) -> None:
    """Replace an existing regular credential file without following links."""

    try:
        info = target.lstat()
    except OSError as exc:
        raise GuiCredentialError(f"cannot inspect credential file {target}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise GuiCredentialError(
            f"refusing to replace a credential file that is not a regular file: {target}"
        )
    if info.st_uid != os.getuid():
        raise GuiCredentialError(f"credential file is not owned by this user: {target}")
    fd = os.open(target, os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW)
    try:
        os.fchmod(fd, PASSWORD_FILE_MODE)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(secret)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise GuiCredentialError(f"cannot write credential file {target}: {exc}") from exc


def read_credential(path: Path) -> str:
    """Read a credential file, refusing anything that is not a regular file."""

    target = Path(path).expanduser().absolute()
    try:
        info = target.lstat()
    except FileNotFoundError as exc:
        raise GuiCredentialError(f"credential file is missing: {target}") from exc
    except OSError as exc:
        raise GuiCredentialError(f"cannot inspect credential file {target}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise GuiCredentialError(
            f"credential file must be a regular file: {target}"
        )
    if info.st_uid != os.getuid():
        raise GuiCredentialError(f"credential file is not owned by this user: {target}")
    try:
        return target.read_text(encoding="utf-8")
    except OSError as exc:
        raise GuiCredentialError(f"cannot read credential file {target}: {exc}") from exc


def remove_credential(path: Path) -> bool:
    """Remove a credential file without following a final symlink."""

    target = Path(path).expanduser().absolute()
    try:
        info = target.lstat()
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise GuiCredentialError(f"cannot inspect credential file {target}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode):
        target.unlink(missing_ok=True)
        return True
    try:
        target.unlink()
    except OSError as exc:
        raise GuiCredentialError(f"cannot remove credential file {target}: {exc}") from exc
    return True
