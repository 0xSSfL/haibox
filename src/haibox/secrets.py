"""Host-only secret store for one engagement.

Secrets are stored in a mode-0600 JSON file inside the engagement directory.
They are never mounted into a container, never written to the audit log, and
never printed by the CLI.  This MVP relies on host filesystem permissions; it
does not claim to protect against a compromised host account.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from haibox.errors import SecretError
from haibox.utils.time import utc_now

_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]{0,63}$")
_API_VERSION = "haibox/v1"


@dataclass(frozen=True)
class SecretInfo:
    name: str
    created_at: datetime
    updated_at: datetime


class SecretStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def _ensure_parent(self) -> None:
        if self.path.parent.is_symlink():
            raise SecretError(f"secret directory must not be a symbolic link: {self.path.parent}")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            self.path.parent.chmod(0o700)

    def _load(self) -> dict[str, Any]:
        if self.path.parent.is_symlink():
            raise SecretError(
                f"secret directory must not be a symbolic link: {self.path.parent}"
            )
        if self.path.is_symlink():
            raise SecretError(f"secret store must not be a symbolic link: {self.path}")
        if not self.path.exists():
            return {"api_version": _API_VERSION, "secrets": {}}
        try:
            mode = self.path.stat().st_mode & 0o777
            if mode & 0o077:
                self.path.chmod(0o600)
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SecretError(f"cannot read secret store {self.path}: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("secrets"), dict):
            raise SecretError(f"invalid secret store {self.path}")
        return raw

    def _write(self, payload: dict[str, Any]) -> None:
        self._ensure_parent()
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        fd, temp_name = tempfile.mkstemp(
            prefix=".secrets-", suffix=".tmp", dir=str(self.path.parent)
        )
        temp = Path(temp_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(self.path)
            self.path.chmod(0o600)
        except OSError as exc:
            with contextlib.suppress(OSError):
                temp.unlink(missing_ok=True)
            raise SecretError(f"cannot write secret store {self.path}: {exc}") from exc

    def set(self, name: str, value: str) -> SecretInfo:
        if not _NAME_RE.fullmatch(name):
            raise SecretError(
                "secret name must start with a letter and contain only letters, "
                "digits, underscores, or hyphens"
            )
        if not value:
            raise SecretError("secret value must not be empty")
        payload = self._load()
        now = utc_now()
        existing = payload["secrets"].get(name)
        created = existing.get("created_at") if isinstance(existing, dict) else None
        payload["secrets"][name] = {
            "value": value,
            "created_at": created or now.isoformat(),
            "updated_at": now.isoformat(),
        }
        self._write(payload)
        return SecretInfo(
            name=name,
            created_at=datetime.fromisoformat(created) if created else now,
            updated_at=now,
        )

    def get(self, name: str) -> str:
        payload = self._load()
        entry = payload["secrets"].get(name)
        if not isinstance(entry, dict) or not isinstance(entry.get("value"), str):
            raise SecretError(f"secret not found: {name}")
        return str(entry["value"])

    def list(self) -> list[SecretInfo]:
        payload = self._load()
        infos: list[SecretInfo] = []
        for name, entry in sorted(payload["secrets"].items()):
            if not isinstance(entry, dict):
                continue
            try:
                infos.append(
                    SecretInfo(
                        name=name,
                        created_at=datetime.fromisoformat(str(entry["created_at"])),
                        updated_at=datetime.fromisoformat(str(entry["updated_at"])),
                    )
                )
            except (KeyError, ValueError) as exc:
                raise SecretError(f"invalid secret metadata for {name!r}") from exc
        return infos

    def remove(self, name: str) -> None:
        payload = self._load()
        if name not in payload["secrets"]:
            raise SecretError(f"secret not found: {name}")
        del payload["secrets"][name]
        self._write(payload)
