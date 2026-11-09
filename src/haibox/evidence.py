"""Host-side evidence store with SHA-256 manifests.

Evidence is copied out of the engagement workspace into a host-only directory,
made read-only, and recorded in a manifest.  The evidence directory is never
mounted into a container.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from secrets import token_hex
from typing import Any

from haibox.errors import EvidenceError
from haibox.utils.time import iso_now

_API_VERSION = "haibox/v1"
_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
_ID_RE = re.compile(r"^ev-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}-[0-9a-f]{6}$")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass
class EvidenceEntry:
    id: str
    original_name: str
    stored_name: str
    sha256: str
    size: int
    added_at: str
    note: str = ""
    tags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "original_name": self.original_name,
            "stored_name": self.stored_name,
            "sha256": self.sha256,
            "size": self.size,
            "added_at": self.added_at,
            "note": self.note,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> EvidenceEntry:
        raw_tags = raw.get("tags", [])
        if not isinstance(raw_tags, list):
            raise EvidenceError("invalid evidence tags")
        try:
            return cls(
                id=str(raw["id"]),
                original_name=str(raw["original_name"]),
                stored_name=str(raw["stored_name"]),
                sha256=str(raw["sha256"]),
                size=int(raw["size"]),
                added_at=str(raw["added_at"]),
                note=str(raw.get("note", "")),
                tags=[str(tag) for tag in raw_tags],
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise EvidenceError("invalid evidence manifest entry") from exc


@dataclass(frozen=True)
class EvidenceVerification:
    valid: bool
    entries: int
    errors: list[str]


class EvidenceStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.manifest_path = root / "manifest.json"

    def _ensure_root(self) -> None:
        if self.root.is_symlink():
            raise EvidenceError(f"evidence directory must not be a symbolic link: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with contextlib.suppress(OSError):
            self.root.chmod(0o700)

    def _load(self) -> dict[str, Any]:
        if self.root.is_symlink():
            raise EvidenceError(f"evidence directory must not be a symbolic link: {self.root}")
        if self.manifest_path.is_symlink():
            raise EvidenceError("evidence manifest must not be a symbolic link")
        if not self.manifest_path.exists():
            return {"api_version": _API_VERSION, "entries": []}
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise EvidenceError(f"cannot read evidence manifest: {exc}") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("entries"), list):
            raise EvidenceError("invalid evidence manifest")
        return raw

    def _write(self, payload: dict[str, Any]) -> None:
        self._ensure_root()
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        fd, temp_name = tempfile.mkstemp(
            prefix=".manifest-", suffix=".tmp", dir=str(self.root)
        )
        temp = Path(temp_name)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            temp.replace(self.manifest_path)
            self.manifest_path.chmod(0o600)
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise EvidenceError(f"cannot write evidence manifest: {exc}") from exc

    def _entries(self) -> list[EvidenceEntry]:
        payload = self._load()
        entries: list[EvidenceEntry] = []
        for item in payload["entries"]:
            if not isinstance(item, dict):
                raise EvidenceError("invalid evidence manifest entry")
            entries.append(EvidenceEntry.from_dict(item))
        return entries

    def add(
        self,
        source: Path,
        *,
        note: str = "",
        tags: list[str] | None = None,
    ) -> EvidenceEntry:
        self._ensure_root()
        source = source.expanduser()
        if source.is_symlink():
            raise EvidenceError("evidence source must not be a symbolic link")
        try:
            resolved = source.resolve(strict=True)
            # Lexical normalisation is intentional: resolving would follow the
            # symlinks this comparison is meant to detect.
            absolute = Path(os.path.abspath(source))  # noqa: PTH100
        except OSError as exc:
            raise EvidenceError(f"cannot read evidence source {source}: {exc}") from exc
        if resolved != absolute:
            raise EvidenceError("evidence source path must not contain a symbolic link")
        if not resolved.is_file():
            raise EvidenceError(f"evidence source is not a regular file: {source}")
        try:
            resolved.relative_to(self.root.resolve())
        except ValueError:
            pass
        else:
            raise EvidenceError("source is already inside the evidence store")

        # Copy into a fresh temporary file first.  The hash, size, and final
        # name all describe the bytes that are actually stored, not a source
        # file that could change between hashing and copying.  ``os.replace``
        # also cannot be tricked into following a destination symlink.
        temp: Path | None = None
        try:
            with resolved.open("rb") as handle:
                fd, temp_name = tempfile.mkstemp(
                    prefix=".evidence-", suffix=".tmp", dir=str(self.root)
                )
                temp = Path(temp_name)
                with os.fdopen(fd, "wb") as destination_handle:
                    shutil.copyfileobj(handle, destination_handle)
                    destination_handle.flush()
                    os.fsync(destination_handle.fileno())
            temp.chmod(0o400)
            digest = sha256_file(temp)
            size = temp.stat().st_size
        except OSError as exc:
            if temp is not None:
                temp.unlink(missing_ok=True)
            raise EvidenceError(f"cannot copy evidence: {exc}") from exc
        if temp is None:
            raise EvidenceError("cannot copy evidence")

        stamp = iso_now().replace("-", "").replace(":", "").replace(".", "")
        stamp = stamp[:15] + "Z"
        safe_name = _SAFE_NAME_RE.sub("_", resolved.name)[:80] or "evidence"
        evidence_id = ""
        stored_name = ""
        destination: Path | None = None
        for _ in range(5):
            evidence_id = f"ev-{stamp}-{digest[:8]}-{token_hex(3)}"
            stored_name = f"{evidence_id}-{safe_name}"
            candidate = self.root / stored_name
            if not candidate.exists() and not candidate.is_symlink():
                destination = candidate
                break
        if destination is None:
            temp.unlink(missing_ok=True)
            raise EvidenceError("could not allocate a unique evidence id")

        try:
            temp.replace(destination)
        except OSError as exc:
            temp.unlink(missing_ok=True)
            raise EvidenceError(f"cannot store evidence: {exc}") from exc

        entry = EvidenceEntry(
            id=evidence_id,
            original_name=resolved.name,
            stored_name=stored_name,
            sha256=digest,
            size=size,
            added_at=iso_now(),
            note=note,
            tags=sorted(set(tags or [])),
        )
        payload = self._load()
        payload["entries"].append(entry.to_dict())
        try:
            self._write(payload)
        except EvidenceError:
            destination.unlink(missing_ok=True)
            raise
        return entry

    def list(self) -> list[EvidenceEntry]:
        return self._entries()

    def get(self, evidence_id: str) -> EvidenceEntry:
        for entry in self._entries():
            if entry.id == evidence_id:
                return entry
        raise EvidenceError(f"evidence not found: {evidence_id}")

    def path_for(self, entry: EvidenceEntry) -> Path:
        if self.root.is_symlink():
            raise EvidenceError(f"evidence directory must not be a symbolic link: {self.root}")
        stored = Path(entry.stored_name)
        if (
            not entry.stored_name
            or stored.is_absolute()
            or stored.name != entry.stored_name
            or ".." in stored.parts
        ):
            raise EvidenceError(f"invalid stored evidence name: {entry.stored_name!r}")
        return self.root / stored

    def verify(self) -> EvidenceVerification:
        errors: list[str] = []
        entries = self._entries()
        for entry in entries:
            if not _ID_RE.fullmatch(entry.id):
                errors.append(f"{entry.id}: invalid id")
            path = self.path_for(entry)
            if path.is_symlink():
                errors.append(f"{entry.id}: file is a symbolic link")
                continue
            if not path.exists():
                errors.append(f"{entry.id}: file is missing")
                continue
            try:
                mode = path.stat().st_mode & 0o777
                if mode & 0o222:
                    errors.append(f"{entry.id}: file is writable (mode {mode:o})")
                actual_size = path.stat().st_size
                if actual_size != entry.size:
                    errors.append(
                        f"{entry.id}: size mismatch ({actual_size} != {entry.size})"
                    )
                actual_hash = sha256_file(path)
                if actual_hash != entry.sha256:
                    errors.append(f"{entry.id}: SHA-256 mismatch")
            except OSError as exc:
                errors.append(f"{entry.id}: {exc}")
        return EvidenceVerification(valid=not errors, entries=len(entries), errors=errors)

    def remove(self, evidence_id: str) -> None:
        entry = self.get(evidence_id)
        path = self.path_for(entry)
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise EvidenceError(f"cannot remove evidence file: {exc}") from exc
        payload = self._load()
        payload["entries"] = [
            item for item in payload["entries"] if item.get("id") != evidence_id
        ]
        self._write(payload)
