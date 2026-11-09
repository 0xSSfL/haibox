"""Append-only, hash-chained audit log.

Each engagement has its own log, and the platform has one for operations that
are not tied to an engagement.  Entries are JSON Lines.  The hash of each entry
covers the previous hash, so deleting or editing an entry breaks verification.

This is tamper-evident, not tamper-proof: an attacker with write access to the
host data directory can rewrite the whole chain.  The host-side log is still
useful because engagement containers never receive it.
"""

from __future__ import annotations

import contextlib
import fcntl
import getpass
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haibox.errors import AuditError
from haibox.utils.redact import redact
from haibox.utils.time import iso_now

GENESIS_HASH = "0" * 64


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _hash_payload(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


@dataclass(frozen=True)
class AuditVerification:
    valid: bool
    entries: int
    last_hash: str
    error: str | None = None


class AuditLog:
    def __init__(self, path: Path, actor: str | None = None) -> None:
        self.path = path
        self.actor = actor or getpass.getuser()

    def _ensure_parent(self) -> None:
        if self.path.parent.is_symlink():
            raise AuditError(
                f"audit directory must not be a symbolic link: {self.path.parent}"
            )
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            self.path.parent.chmod(0o700)

    def _last_entry(self, handle: Any) -> dict[str, Any] | None:
        handle.seek(0)
        lines = [line for line in handle if line.strip()]
        if not lines:
            return None
        try:
            entry = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise AuditError(f"audit log {self.path} is corrupt: {exc}") from exc
        if not isinstance(entry, dict) or "hash" not in entry or "seq" not in entry:
            raise AuditError(f"audit log {self.path} has an invalid trailing entry")
        return entry

    def append(
        self,
        event: str,
        *,
        engagement: str | None = None,
        data: dict[str, Any] | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        if not event.strip():
            raise AuditError("audit event name must not be empty")
        self._ensure_parent()
        flags = os.O_RDWR | os.O_CREAT | os.O_APPEND
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            fd = os.open(self.path, flags, 0o600)
        except OSError as exc:
            raise AuditError(f"cannot open audit log {self.path}: {exc}") from exc
        with os.fdopen(fd, "a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                previous = self._last_entry(handle)
                try:
                    seq = 1 if previous is None else int(previous["seq"]) + 1
                except (TypeError, ValueError) as exc:
                    raise AuditError(f"audit log {self.path} has an invalid sequence") from exc
                prev_hash = GENESIS_HASH if previous is None else str(previous["hash"])
                payload: dict[str, Any] = {
                    "seq": seq,
                    "timestamp": iso_now(),
                    "event": event.strip(),
                    "actor": actor or self.actor,
                    "engagement": engagement,
                    "data": redact(data or {}),
                    "prev_hash": prev_hash,
                }
                payload["hash"] = _hash_payload(payload)
                handle.seek(0, 2)
                handle.write(json.dumps(payload, sort_keys=True, ensure_ascii=False) + "\n")
                handle.flush()
                with contextlib.suppress(OSError):
                    os.fsync(handle.fileno())
                with contextlib.suppress(OSError):
                    self.path.chmod(0o600)
                return payload
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def read(self, limit: int | None = None) -> list[dict[str, Any]]:
        if limit is not None and limit < 0:
            raise AuditError("audit read limit must not be negative")
        if self.path.parent.is_symlink():
            raise AuditError(
                f"audit directory must not be a symbolic link: {self.path.parent}"
            )
        if self.path.is_symlink():
            raise AuditError(f"audit log must not be a symbolic link: {self.path}")
        if not self.path.exists():
            return []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise AuditError(f"cannot read audit log {self.path}: {exc}") from exc
        entries: list[dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError as exc:
                raise AuditError(f"audit log {self.path} is corrupt: {exc}") from exc
            if not isinstance(entry, dict):
                raise AuditError(f"audit log {self.path} contains a non-object entry")
            entries.append(entry)
        if limit is not None:
            return entries[-limit:] if limit else []
        return entries

    def verify(self) -> AuditVerification:
        entries = self.read()
        previous = GENESIS_HASH
        for expected_seq, entry in enumerate(entries, start=1):
            if entry.get("seq") != expected_seq:
                return AuditVerification(
                    valid=False,
                    entries=len(entries),
                    last_hash=previous,
                    error=f"entry {expected_seq} has seq {entry.get('seq')!r}",
                )
            if entry.get("prev_hash") != previous:
                return AuditVerification(
                    valid=False,
                    entries=len(entries),
                    last_hash=previous,
                    error=f"entry {expected_seq} has a broken previous-hash link",
                )
            claimed = entry.get("hash")
            payload = {key: value for key, value in entry.items() if key != "hash"}
            if claimed != _hash_payload(payload):
                return AuditVerification(
                    valid=False,
                    entries=len(entries),
                    last_hash=previous,
                    error=f"entry {expected_seq} has an invalid hash",
                )
            previous = str(claimed)
        return AuditVerification(valid=True, entries=len(entries), last_hash=previous)


def audit_platform(
    paths: Any,
    event: str,
    *,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append to the platform-wide audit log."""

    return AuditLog(paths.logs_dir / "audit.jsonl").append(event, data=data)
