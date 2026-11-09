"""Filesystem layout for the platform and its engagements."""

from __future__ import annotations

import contextlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

from haibox.errors import EngagementError, VpnError

_ENGAGEMENT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_VPN_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _env_path(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


def validate_engagement_id(value: str) -> str:
    """Reject identifiers that could escape the engagement directory.

    Every path helper goes through this check so a tampered current-pointer or
    a bad command-line value can never address ``../`` outside the data dir.
    """

    if not _ENGAGEMENT_ID_RE.fullmatch(value):
        raise EngagementError(
            "engagement id must be 1-40 lowercase letters, digits, or hyphens, "
            "and must start with a letter or digit"
        )
    return value


def validate_vpn_name(value: str) -> str:
    """Reject VPN names that could escape the profile directory."""

    if not _VPN_NAME_RE.fullmatch(value):
        raise VpnError(
            "VPN profile name must be 1-40 lowercase letters, digits, or hyphens, "
            "and must start with a letter or digit"
        )
    return value


@dataclass(frozen=True)
class Paths:
    """Resolved XDG-style paths.

    ``data_dir`` contains engagements, archives, and the platform audit log.
    ``config_dir`` contains the user configuration and optional user profiles.
    """

    data_dir: Path
    config_dir: Path

    @classmethod
    def resolve(
        cls,
        data_dir: str | Path | None = None,
        config_dir: str | Path | None = None,
    ) -> Paths:
        xdg_data = _env_path("XDG_DATA_HOME", Path.home() / ".local" / "share")
        xdg_config = _env_path("XDG_CONFIG_HOME", Path.home() / ".config")
        data = Path(data_dir).expanduser() if data_dir else _env_path(
            "HAIBOX_DATA_DIR", xdg_data / "haibox"
        )
        config = Path(config_dir).expanduser() if config_dir else _env_path(
            "HAIBOX_CONFIG_DIR", xdg_config / "haibox"
        )
        return cls(data_dir=data.resolve(), config_dir=config.resolve())

    @property
    def config_file(self) -> Path:
        return self.config_dir / "config.yaml"

    @property
    def engagements_dir(self) -> Path:
        return self.data_dir / "engagements"

    @property
    def archives_dir(self) -> Path:
        return self.data_dir / "archives"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def current_file(self) -> Path:
        return self.data_dir / "current"

    @property
    def profiles_dir(self) -> Path:
        return self.config_dir / "profiles"

    @property
    def vpn_dir(self) -> Path:
        return self.data_dir / "vpn"

    def vpn_profile_dir(self, name: str) -> Path:
        return self.vpn_dir / validate_vpn_name(name)

    def vpn_profile_file(self, name: str) -> Path:
        return self.vpn_profile_dir(name) / "profile.yaml"

    def vpn_config_file(self, name: str) -> Path:
        return self.vpn_profile_dir(name) / "vpn.conf"

    def engagement_dir(self, engagement_id: str) -> Path:
        return self.engagements_dir / validate_engagement_id(engagement_id)

    def engagement_file(self, engagement_id: str) -> Path:
        return self.engagement_dir(engagement_id) / "engagement.yaml"

    def workspace_dir(self, engagement_id: str) -> Path:
        return self.engagement_dir(engagement_id) / "workspace"

    def evidence_dir(self, engagement_id: str) -> Path:
        return self.engagement_dir(engagement_id) / "evidence"

    def reports_dir(self, engagement_id: str) -> Path:
        return self.engagement_dir(engagement_id) / "reports"

    def secrets_file(self, engagement_id: str) -> Path:
        return self.engagement_dir(engagement_id) / "secrets.json"

    def scope_file(self, engagement_id: str) -> Path:
        return self.engagement_dir(engagement_id) / "scope.json"

    def engagement_audit_file(self, engagement_id: str) -> Path:
        return self.engagement_dir(engagement_id) / "audit.jsonl"

    def ensure(self) -> None:
        """Create the platform directories with restrictive permissions."""

        for path in (
            self.data_dir,
            self.config_dir,
            self.engagements_dir,
            self.archives_dir,
            self.logs_dir,
            self.profiles_dir,
            self.vpn_dir,
        ):
            path.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Best effort on filesystems that do not support chmod.
            with contextlib.suppress(OSError):
                path.chmod(0o700)
