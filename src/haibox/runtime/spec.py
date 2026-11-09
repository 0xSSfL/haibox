"""The deny-by-default container specification.

There is deliberately no pass-through of arbitrary Docker flags.  Every option
that reaches the daemon is constructed here and covered by validation.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from haibox.errors import ValidationError
from haibox.models import ALLOWED_CAPABILITIES, FORBIDDEN_ENV_KEYS, Engagement
from haibox.paths import Paths
from haibox.runtime.base import labels_for

_NAME_RE = re.compile(r"^haibox-[a-z0-9][a-z0-9-]{0,61}$")
_NETWORK_RE = re.compile(r"^(haibox-[a-z0-9][a-z0-9-]{0,61}|none)$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MEMORY_RE = re.compile(r"^[1-9][0-9]*[bkmg]?$", re.IGNORECASE)
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]*$")


@dataclass(frozen=True)
class ContainerSpec:
    image: str
    name: str
    network: str
    workspace: Path
    scope_file: Path
    uid: int
    gid: int
    cpus: float
    memory: str
    pids_limit: int
    capabilities: list[str] = field(default_factory=list)
    environment: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)
    hostname: str = ""
    sleep_command: tuple[str, ...] = ("/bin/sh", "-c", "exec sleep infinity")

    def __post_init__(self) -> None:
        if not _IMAGE_RE.fullmatch(self.image) or self.image.startswith("-"):
            raise ValidationError(f"invalid image reference: {self.image!r}")
        if not _NAME_RE.fullmatch(self.name):
            raise ValidationError(f"invalid container name: {self.name!r}")
        if not _NETWORK_RE.fullmatch(self.network):
            raise ValidationError(f"invalid network name: {self.network!r}")
        if self.uid <= 0 or self.gid <= 0:
            raise ValidationError("container UID and GID must be non-root")
        if not 0 < self.cpus <= 64:
            raise ValidationError("cpus must be between 0 and 64")
        if not _MEMORY_RE.fullmatch(self.memory):
            raise ValidationError("memory must look like '512m' or '4g'")
        if not 16 <= self.pids_limit <= 4096:
            raise ValidationError("pids_limit must be between 16 and 4096")
        unknown = sorted(set(self.capabilities) - ALLOWED_CAPABILITIES)
        if unknown:
            raise ValidationError(f"capabilities not allowed: {', '.join(unknown)}")
        for key in self.environment:
            if not _ENV_KEY_RE.fullmatch(key):
                raise ValidationError(f"invalid environment variable name: {key!r}")
            if key in FORBIDDEN_ENV_KEYS:
                raise ValidationError(f"environment variable is not allowed: {key}")
        if self.labels.get("haibox.managed") != "true":
            raise ValidationError("container must carry the haibox.managed=true label")
        if not self.workspace.is_absolute() or not self.scope_file.is_absolute():
            raise ValidationError("workspace and scope paths must be absolute")
        for label, path in (("workspace", self.workspace), ("scope", self.scope_file)):
            if "," in str(path):
                raise ValidationError(
                    f"{label} path must not contain a comma (Docker --mount syntax)"
                )
            if path.is_symlink():
                raise ValidationError(f"{label} path must not be a symbolic link")
        if not self.workspace.is_dir():
            raise ValidationError(f"workspace does not exist: {self.workspace}")
        if not self.scope_file.is_file():
            raise ValidationError(f"scope file does not exist: {self.scope_file}")
        hostname = self.hostname or self.name
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", hostname):
            raise ValidationError(f"invalid hostname: {hostname!r}")
        object.__setattr__(self, "hostname", hostname)
        object.__setattr__(self, "capabilities", sorted(set(self.capabilities)))

    @classmethod
    def from_engagement(cls, engagement: Engagement, paths: Paths) -> ContainerSpec:
        runtime = engagement.runtime
        network = "none" if runtime.network_mode == "none" else runtime.network_name
        return cls(
            image=engagement.image,
            name=runtime.container_name,
            network=network,
            workspace=paths.workspace_dir(engagement.id),
            scope_file=paths.scope_file(engagement.id),
            uid=runtime.uid,
            gid=runtime.gid,
            cpus=runtime.cpus,
            memory=runtime.memory,
            pids_limit=runtime.pids_limit,
            capabilities=list(runtime.capabilities),
            environment=dict(runtime.environment),
            labels=labels_for(engagement.id, engagement.profile, engagement.image),
        )

    def to_create_args(self) -> list[str]:
        """Return ``docker create`` arguments, including the image and command."""

        args: list[str] = [
            "create",
            "--name",
            self.name,
            "--hostname",
            self.hostname,
            "--network",
            self.network,
            "--user",
            f"{self.uid}:{self.gid}",
            "--workdir",
            "/workspace",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=1g",
            "--tmpfs",
            "/run:rw,nosuid,nodev,noexec,size=64m",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--init",
            "--ipc",
            "private",
            "--restart",
            "no",
            "--stop-timeout",
            "10",
            "--ulimit",
            "nofile=1024:4096",
            "--log-driver",
            "local",
            "--log-opt",
            "max-size=10m",
            "--log-opt",
            "max-file=3",
            "--cpus",
            f"{self.cpus:g}",
            "--memory",
            self.memory,
            "--pids-limit",
            str(self.pids_limit),
        ]
        for capability in self.capabilities:
            args.extend(["--cap-add", capability])
        for key in sorted(self.labels):
            args.extend(["--label", f"{key}={self.labels[key]}"])
        for key in sorted(self.environment):
            args.extend(["--env", f"{key}={self.environment[key]}"])
        args.extend(
            [
                "--mount",
                f"type=bind,source={self.workspace},target=/workspace",
                "--mount",
                f"type=bind,source={self.scope_file},"
                "target=/etc/haibox/scope.json,readonly",
                "--entrypoint",
                self.sleep_command[0],
                self.image,
                *self.sleep_command[1:],
            ]
        )
        return args

    def describe(self) -> dict[str, object]:
        return {
            "image": self.image,
            "name": self.name,
            "network": self.network,
            "workspace": str(self.workspace),
            "scope_file": str(self.scope_file),
            "uid": self.uid,
            "gid": self.gid,
            "cpus": self.cpus,
            "memory": self.memory,
            "pids_limit": self.pids_limit,
            "capabilities": self.capabilities,
            "environment_keys": sorted(self.environment),
            "labels": self.labels,
            "read_only": True,
            "cap_drop": ["ALL"],
            "no_new_privileges": True,
        }


def ensure_workspace_ownership(path: Path, uid: int, gid: int) -> None:
    """Best-effort check that a custom UID can write the workspace.

    We do not chown automatically: changing ownership of a host directory is a
    privileged operation and should be an explicit operator decision.
    """

    if not path.is_dir():
        raise ValidationError(f"workspace does not exist: {path}")
    candidates = [path]
    home = path / ".home"
    if home.is_dir():
        candidates.append(home)
    for candidate in candidates:
        stat = candidate.stat()
        if stat.st_uid != uid or stat.st_gid != gid:
            raise ValidationError(
                f"{candidate} is owned by {stat.st_uid}:{stat.st_gid}, "
                f"but the container runs as {uid}:{gid}; "
                "create the engagement with matching --uid/--gid or adjust ownership explicitly"
            )
        if not os.access(candidate, os.W_OK):
            raise ValidationError(f"workspace path is not writable: {candidate}")
