"""Engagement lifecycle and on-disk layout."""

from __future__ import annotations

import contextlib
import getpass
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from haibox.audit import AuditLog
from haibox.errors import EngagementError
from haibox.models import Engagement, Profile, ResourceLimits, RuntimeSettings, Scope
from haibox.paths import Paths
from haibox.profiles import load_profile
from haibox.scope import load_scope, scope_to_json
from haibox.utils.time import utc_now


def _atomic_write(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}-", suffix=".tmp", dir=str(path.parent))
    temp = Path(temp_name)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
        path.chmod(mode)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


class EngagementManager:
    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    # ------------------------------------------------------------------ create
    def create(
        self,
        engagement_id: str,
        *,
        name: str | None = None,
        profile_name: str | None = None,
        scope: Scope | None = None,
        image: str | None = None,
        cpus: float | None = None,
        memory: str | None = None,
        pids_limit: int | None = None,
        uid: int | None = None,
        gid: int | None = None,
        vpn_provider: str = "local",
        notes: str = "",
        set_current: bool = True,
    ) -> Engagement:
        self.paths.ensure()
        profile = load_profile(profile_name or "web-security", self.paths)
        if profile.status == "planned":
            raise EngagementError(
                f"profile {profile.name!r} is planned but not implemented yet"
            )
        root = self.paths.engagement_dir(engagement_id)
        if root.exists():
            raise EngagementError(f"engagement already exists: {engagement_id}")

        resources = ResourceLimits(
            cpus=profile.resources.cpus if cpus is None else cpus,
            memory=profile.resources.memory if memory is None else memory,
            pids_limit=profile.resources.pids_limit if pids_limit is None else pids_limit,
        )
        runtime_uid = os.getuid() if uid is None else uid
        runtime_gid = os.getgid() if gid is None else gid
        network_name = (
            "none" if profile.network == "none" else f"haibox-{engagement_id}-net"
        )
        environment = dict(profile.environment)
        environment.update(
            {
                "HOME": "/workspace/.home",
                "XDG_CONFIG_HOME": "/workspace/.home/.config",
                "XDG_CACHE_HOME": "/workspace/.home/.cache",
                "TMPDIR": "/tmp",
                "HAIBOX_ENGAGEMENT": engagement_id,
                "HAIBOX_PROFILE": profile.name,
                "HAIBOX_SCOPE_FILE": "/etc/haibox/scope.json",
            }
        )
        now = utc_now()
        engagement = Engagement(
            id=engagement_id,
            name=(name or engagement_id).strip(),
            created_at=now,
            updated_at=now,
            owner=getpass.getuser(),
            profile=profile.name,
            image=image or profile.image,
            scope=scope or Scope(),
            runtime=RuntimeSettings(
                container_name=f"haibox-{engagement_id}",
                network_name=network_name,
                cpus=resources.cpus,
                memory=resources.memory,
                pids_limit=resources.pids_limit,
                uid=runtime_uid,
                gid=runtime_gid,
                network_mode=profile.network,
                capabilities=profile.capabilities,
                environment=environment,
            ),
            vpn_provider=vpn_provider,
            notes=notes,
        )

        try:
            self._create_layout(engagement, profile)
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise

        try:
            self._audit(
                engagement.id,
                "engagement.created",
                {
                    "name": engagement.name,
                    "profile": engagement.profile,
                    "image": engagement.image,
                    "scope": engagement.scope.model_dump(mode="json"),
                    "network": engagement.runtime.network_mode,
                },
            )
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise

        if set_current:
            self.set_current(engagement.id)
        return engagement

    def _create_layout(self, engagement: Engagement, profile: Profile) -> None:
        root = self.paths.engagement_dir(engagement.id)
        root.mkdir(parents=True, exist_ok=False, mode=0o700)
        with contextlib.suppress(OSError):
            root.chmod(0o700)
        workspace = self.paths.workspace_dir(engagement.id)
        for path in (
            workspace,
            workspace / "notes",
            workspace / "scans",
            workspace / "loot",
            workspace / ".home",
            workspace / ".home" / ".config",
            workspace / ".home" / ".cache",
            self.paths.evidence_dir(engagement.id),
            self.paths.reports_dir(engagement.id),
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            with contextlib.suppress(OSError):
                path.chmod(0o700)
        _atomic_write(
            self.paths.scope_file(engagement.id),
            scope_to_json(engagement.scope),
            0o600,
        )
        _atomic_write(
            self.paths.engagement_file(engagement.id),
            yaml.safe_dump(
                engagement.model_dump(mode="json"), sort_keys=False, allow_unicode=True
            ),
            0o600,
        )

    # -------------------------------------------------------------------- read
    def load(self, engagement_id: str) -> Engagement:
        path = self.paths.engagement_file(engagement_id)
        if path.is_symlink():
            raise EngagementError(f"engagement file must not be a symbolic link: {path}")
        if not path.is_file():
            raise EngagementError(f"engagement not found: {engagement_id}")
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise EngagementError(f"cannot read engagement {engagement_id}: {exc}") from exc
        if not isinstance(raw, dict):
            raise EngagementError(f"engagement file is not a mapping: {path}")
        try:
            return Engagement.model_validate(raw)
        except PydanticValidationError as exc:
            raise EngagementError(f"invalid engagement {engagement_id}: {exc}") from exc

    def scope(self, engagement_id: str) -> Scope:
        return load_scope(self.paths.scope_file(engagement_id))

    def list(self) -> list[Engagement]:
        if not self.paths.engagements_dir.is_dir():
            return []
        engagements: list[Engagement] = []
        for path in sorted(self.paths.engagements_dir.iterdir()):
            if path.is_dir() and (path / "engagement.yaml").is_file():
                engagements.append(self.load(path.name))
        return engagements

    def current(self) -> Engagement | None:
        path = self.paths.current_file
        if path.is_symlink():
            raise EngagementError(f"current engagement pointer must not be a symbolic link: {path}")
        if not path.is_file():
            return None
        try:
            engagement_id = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise EngagementError(f"cannot read current engagement pointer: {exc}") from exc
        if not engagement_id:
            return None
        return self.load(engagement_id)

    def resolve(self, engagement_id: str | None = None) -> Engagement:
        if engagement_id:
            return self.load(engagement_id)
        current = self.current()
        if current is not None:
            return current
        engagements = self.list()
        if len(engagements) == 1:
            return engagements[0]
        if not engagements:
            raise EngagementError("no engagement exists; create one with 'haibox engagement init'")
        raise EngagementError("no current engagement; use 'haibox engagement use <id>'")

    def set_current(self, engagement_id: str) -> None:
        self.load(engagement_id)
        _atomic_write(self.paths.current_file, f"{engagement_id}\n", 0o600)

    def clear_current(self, engagement_id: str) -> None:
        path = self.paths.current_file
        if not path.is_file():
            return
        try:
            current_id = path.read_text(encoding="utf-8").strip()
        except OSError:
            return
        if current_id == engagement_id:
            path.unlink(missing_ok=True)

    # ------------------------------------------------------------------- write
    def save(self, engagement: Engagement, *, touch: bool = True) -> None:
        if touch:
            engagement.updated_at = utc_now()
        _atomic_write(
            self.paths.engagement_file(engagement.id),
            yaml.safe_dump(
                engagement.model_dump(mode="json"), sort_keys=False, allow_unicode=True
            ),
            0o600,
        )

    def set_scope(self, engagement_id: str, scope: Scope) -> Engagement:
        engagement = self.load(engagement_id)
        engagement.scope = scope
        self.save(engagement)
        _atomic_write(self.paths.scope_file(engagement_id), scope_to_json(scope), 0o600)
        self._audit(
            engagement_id,
            "engagement.scope_changed",
            {"scope": scope.model_dump(mode="json")},
        )
        return engagement

    def archive(self, engagement_id: str) -> Engagement:
        engagement = self.load(engagement_id)
        if engagement.status == "archived":
            return engagement
        engagement.status = "archived"
        self.save(engagement)
        self.clear_current(engagement_id)
        self._audit(engagement_id, "engagement.archived", {"name": engagement.name})
        return engagement

    def destroy(self, engagement_id: str, *, force: bool = False) -> None:
        engagement = self.load(engagement_id)
        if engagement.status != "archived" and not force:
            raise EngagementError(
                "engagement is active; archive it first or pass --force to destroy it"
            )
        root = self.paths.engagement_dir(engagement_id)
        AuditLog(self.paths.logs_dir / "audit.jsonl").append(
            "engagement.destroyed",
            engagement=engagement_id,
            data={"name": engagement.name, "forced": force},
        )
        shutil.rmtree(root)
        self.clear_current(engagement_id)

    # ------------------------------------------------------------------- audit
    def _audit(self, engagement_id: str, event: str, data: dict[str, Any]) -> None:
        AuditLog(self.paths.engagement_audit_file(engagement_id)).append(
            event, engagement=engagement_id, data=data
        )
        AuditLog(self.paths.logs_dir / "audit.jsonl").append(
            event, engagement=engagement_id, data=data
        )
