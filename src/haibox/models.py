"""Validated data models shared by the CLI and the services."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_CONTAINER_NAME_RE = re.compile(r"^haibox-[a-z0-9][a-z0-9-]{0,61}$")
_NETWORK_NAME_RE = re.compile(r"^(haibox-[a-z0-9][a-z0-9-]{0,61}|none)$")
_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MEMORY_RE = re.compile(r"^[1-9][0-9]*[bkmg]?$", re.IGNORECASE)
_HOSTNAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")

# Capabilities that a profile may request. Everything else is refused even if
# a future profile or user configuration asks for it.
ALLOWED_CAPABILITIES = frozenset({"NET_RAW", "NET_BIND_SERVICE"})

# Environment variables that must never be injected into an engagement
# container. They either change Docker client behaviour or preload host code.
FORBIDDEN_ENV_KEYS = frozenset(
    {
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
        "DOCKER_CONFIG",
        "LD_PRELOAD",
        "LD_LIBRARY_PATH",
    }
)


def _current_uid() -> int:
    return os.getuid() if hasattr(os, "getuid") else 1000


def _current_gid() -> int:
    return os.getgid() if hasattr(os, "getgid") else 1000


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Scope(StrictModel):
    """Authorized targets for one engagement.

    Entries are hostnames, URLs, IP addresses, or CIDRs. Exclusions always win.
    An empty ``allowed`` list denies everything.
    """

    allowed: list[str] = Field(default_factory=list)
    excluded: list[str] = Field(default_factory=list)
    allowed_ports: list[int] = Field(default_factory=list)
    notes: str = ""

    @field_validator("allowed", "excluded")
    @classmethod
    def _clean_entries(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            value = value.strip()
            if not value:
                raise ValueError("scope entries must not be empty")
            cleaned.append(value)
        return cleaned

    @field_validator("allowed_ports")
    @classmethod
    def _valid_ports(cls, values: list[int]) -> list[int]:
        for value in values:
            if not 1 <= value <= 65535:
                raise ValueError(f"invalid port: {value}")
        return sorted(set(values))


class ResourceLimits(StrictModel):
    cpus: float = 2.0
    memory: str = "4g"
    pids_limit: int = 512

    @field_validator("cpus")
    @classmethod
    def _valid_cpus(cls, value: float) -> float:
        if not 0 < value <= 64:
            raise ValueError("cpus must be between 0 and 64")
        return value

    @field_validator("memory")
    @classmethod
    def _valid_memory(cls, value: str) -> str:
        value = value.strip().lower()
        if not _MEMORY_RE.fullmatch(value):
            raise ValueError("memory must look like '512m' or '4g'")
        return value

    @field_validator("pids_limit")
    @classmethod
    def _valid_pids(cls, value: int) -> int:
        if not 16 <= value <= 4096:
            raise ValueError("pids_limit must be between 16 and 4096")
        return value


class RuntimeSettings(StrictModel):
    """Security-relevant container shape frozen at engagement creation.

    A later profile edit must not silently widen an existing engagement, so
    capabilities and environment are copied into the engagement metadata.
    """

    container_name: str
    network_name: str
    cpus: float
    memory: str
    pids_limit: int
    uid: int
    gid: int
    network_mode: Literal["isolated", "none"] = "isolated"
    capabilities: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)

    @field_validator("container_name")
    @classmethod
    def _valid_container_name(cls, value: str) -> str:
        if not _CONTAINER_NAME_RE.fullmatch(value):
            raise ValueError("container_name must match haibox-<id>")
        return value

    @field_validator("network_name")
    @classmethod
    def _valid_network_name(cls, value: str) -> str:
        if not _NETWORK_NAME_RE.fullmatch(value):
            raise ValueError("network_name must be a haibox-<id> network or 'none'")
        return value

    @field_validator("uid", "gid")
    @classmethod
    def _non_root(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("engagement containers must run as a non-root UID/GID")
        return value

    @field_validator("capabilities")
    @classmethod
    def _allowed_capabilities(cls, values: list[str]) -> list[str]:
        unknown = sorted(set(values) - ALLOWED_CAPABILITIES)
        if unknown:
            raise ValueError(f"capabilities not allowed: {', '.join(unknown)}")
        return sorted(set(values))

    @field_validator("environment")
    @classmethod
    def _safe_environment(cls, values: dict[str, str]) -> dict[str, str]:
        for key in values:
            if not _ENV_KEY_RE.fullmatch(key):
                raise ValueError(f"invalid environment variable name: {key!r}")
            if key in FORBIDDEN_ENV_KEYS:
                raise ValueError(f"environment variable is not allowed: {key}")
        return values

    @model_validator(mode="after")
    def _network_consistency(self) -> RuntimeSettings:
        if self.network_mode == "none" and self.network_name != "none":
            raise ValueError("network_mode 'none' requires network_name 'none'")
        if self.network_mode == "isolated" and self.network_name == "none":
            raise ValueError("network_mode 'isolated' requires a haibox network")
        return self


class Engagement(StrictModel):
    api_version: Literal["haibox/v1"] = "haibox/v1"
    kind: Literal["Engagement"] = "Engagement"
    id: str
    name: str
    created_at: datetime
    updated_at: datetime
    owner: str
    profile: str
    image: str
    scope: Scope
    runtime: RuntimeSettings
    vpn_provider: str = "local"
    status: Literal["active", "archived"] = "active"
    notes: str = ""

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not _ID_RE.fullmatch(value):
            raise ValueError(
                "engagement id must be 1-40 lowercase letters, digits, or hyphens, "
                "and must start with a letter or digit"
            )
        return value

    @field_validator("name")
    @classmethod
    def _non_empty_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("engagement name must not be empty")
        return value

    @field_validator("profile")
    @classmethod
    def _valid_profile_name(cls, value: str) -> str:
        if not _NAME_RE.fullmatch(value):
            raise ValueError("invalid profile name")
        return value

    @field_validator("image")
    @classmethod
    def _valid_image(cls, value: str) -> str:
        value = value.strip()
        if not value or value.startswith("-") or any(ch.isspace() for ch in value):
            raise ValueError("invalid image reference")
        return value

    @field_validator("vpn_provider")
    @classmethod
    def _valid_vpn_provider(cls, value: str) -> str:
        if not _NAME_RE.fullmatch(value):
            raise ValueError("invalid VPN provider name")
        return value


class VpnProfile(StrictModel):
    """Host-only VPN profile metadata.

    The configuration file itself is stored next to this metadata under the
    HAIBOX data directory. It is never embedded in YAML and never mounted into
    an engagement runner.
    """

    api_version: Literal["haibox/v1"] = "haibox/v1"
    kind: Literal["VpnProfile"] = "VpnProfile"
    name: str
    type: Literal["wireguard", "openvpn"]
    description: str = ""
    config_file: str = "vpn.conf"
    created_at: datetime
    updated_at: datetime

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_RE.fullmatch(value):
            raise ValueError("invalid VPN profile name")
        return value

    @field_validator("config_file")
    @classmethod
    def _fixed_config_file(cls, value: str) -> str:
        if value != "vpn.conf":
            raise ValueError("VPN config_file must be 'vpn.conf'")
        return value

    @field_validator("description")
    @classmethod
    def _clean_description(cls, value: str) -> str:
        return value.strip()


class Profile(StrictModel):
    api_version: Literal["haibox/v1"] = "haibox/v1"
    name: str
    description: str = ""
    image: str
    status: Literal["active", "experimental", "planned"] = "active"
    network: Literal["isolated", "none"] = "isolated"
    resources: ResourceLimits = Field(default_factory=ResourceLimits)
    capabilities: list[str] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_RE.fullmatch(value):
            raise ValueError("invalid profile name")
        return value

    @field_validator("image")
    @classmethod
    def _valid_image(cls, value: str) -> str:
        value = value.strip()
        if not value or value.startswith("-") or any(ch.isspace() for ch in value):
            raise ValueError("invalid image reference")
        return value

    @field_validator("capabilities")
    @classmethod
    def _allowed_capabilities(cls, values: list[str]) -> list[str]:
        unknown = sorted(set(values) - ALLOWED_CAPABILITIES)
        if unknown:
            raise ValueError(f"capabilities not allowed: {', '.join(unknown)}")
        return sorted(set(values))

    @field_validator("environment")
    @classmethod
    def _safe_environment(cls, values: dict[str, str]) -> dict[str, str]:
        for key in values:
            if not _ENV_KEY_RE.fullmatch(key):
                raise ValueError(f"invalid environment variable name: {key!r}")
            if key in FORBIDDEN_ENV_KEYS:
                raise ValueError(f"environment variable is not allowed: {key}")
        return values


class ImageTool(StrictModel):
    name: str
    version: str
    verify: str

    @field_validator("name", "version", "verify")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("image tool fields must not be empty")
        return value


class ImageManifest(StrictModel):
    api_version: Literal["haibox/v1"] = "haibox/v1"
    name: str
    version: str
    status: Literal["active", "experimental", "planned"] = "active"
    description: str = ""
    base: str
    dockerfile: str = "Dockerfile"
    context: str = "."
    platforms: list[str] = Field(default_factory=lambda: ["linux/amd64"])
    depends_on: list[str] = Field(default_factory=list)
    tools: list[ImageTool] = Field(default_factory=list)
    build_args: dict[str, str] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _valid_name(cls, value: str) -> str:
        if not _NAME_RE.fullmatch(value):
            raise ValueError("invalid image name")
        return value

    @field_validator("version")
    @classmethod
    def _valid_version(cls, value: str) -> str:
        value = value.strip()
        if not value or any(ch.isspace() for ch in value):
            raise ValueError("invalid image version")
        return value

    @field_validator("base")
    @classmethod
    def _valid_base(cls, value: str) -> str:
        value = value.strip()
        if not value or value.startswith("-") or any(ch.isspace() for ch in value):
            raise ValueError("invalid base image reference")
        return value

    @field_validator("dockerfile", "context")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        value = value.strip()
        if not value or value.startswith("/"):
            raise ValueError("image paths must be relative")
        if ".." in Path(value).parts:
            raise ValueError("image paths must not escape the image directory")
        return value

    @field_validator("depends_on")
    @classmethod
    def _valid_dependencies(cls, values: list[str]) -> list[str]:
        for value in values:
            if not _NAME_RE.fullmatch(value):
                raise ValueError(f"invalid image dependency name: {value!r}")
        if len(values) != len(set(values)):
            raise ValueError("image dependencies must be unique")
        return values

    @field_validator("build_args")
    @classmethod
    def _safe_build_args(cls, values: dict[str, str]) -> dict[str, str]:
        for key, value in values.items():
            if not _ENV_KEY_RE.fullmatch(key):
                raise ValueError(f"invalid build argument name: {key!r}")
            if "\n" in value or "\r" in value:
                raise ValueError("build argument values must be single-line")
        return values

    @model_validator(mode="after")
    def _unique_tools(self) -> ImageManifest:
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("image tool names must be unique")
        if self.name in self.depends_on:
            raise ValueError("an image must not depend on itself")
        return self

    @property
    def image_ref(self) -> str:
        return f"haibox/{self.name}:{self.version}"


class DockerSettings(StrictModel):
    context: str | None = "haibox"
    host: str | None = None
    require_dedicated_context: bool = True
    timeout_seconds: int = 120

    @field_validator("timeout_seconds")
    @classmethod
    def _valid_timeout(cls, value: int) -> int:
        if not 5 <= value <= 3600:
            raise ValueError("timeout_seconds must be between 5 and 3600")
        return value

    @field_validator("host")
    @classmethod
    def _valid_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value or value.startswith("-") or any(ch.isspace() for ch in value):
            raise ValueError("invalid Docker host")
        return value

    @model_validator(mode="after")
    def _endpoint(self) -> DockerSettings:
        if self.context and self.host:
            raise ValueError("set only one of docker.context or docker.host")
        if (
            self.require_dedicated_context
            and not self.host
            and (not self.context or self.context == "default")
        ):
            raise ValueError(
                "docker.context must name a dedicated context (not 'default'), "
                "or set docker.host"
            )
        return self


class DefaultSettings(StrictModel):
    profile: str = "web-security"
    cpus: float = 2.0
    memory: str = "4g"
    pids_limit: int = 512
    uid: int = Field(default_factory=_current_uid)
    gid: int = Field(default_factory=_current_gid)

    @field_validator("profile")
    @classmethod
    def _valid_profile(cls, value: str) -> str:
        if not _NAME_RE.fullmatch(value):
            raise ValueError("invalid default profile name")
        return value


class AuditSettings(StrictModel):
    enabled: bool = True
    hash_chain: bool = True


NetworkProfile = Literal["isolated"]


class NetworkSettings(StrictModel):
    """Engagement network profile.

    ``isolated`` creates an internal bridge with Docker's ``isolated`` gateway
    mode, so the host has no address on the engagement bridge. The legacy
    ``internal`` profile was removed because it left the host gateway, and
    therefore Fedora host SSH, reachable from runners.
    """

    profile: NetworkProfile = "isolated"


class HAIBOXConfig(StrictModel):
    api_version: Literal["haibox/v1"] = "haibox/v1"
    docker: DockerSettings = Field(default_factory=DockerSettings)
    network: NetworkSettings = Field(default_factory=NetworkSettings)
    defaults: DefaultSettings = Field(default_factory=DefaultSettings)
    audit: AuditSettings = Field(default_factory=AuditSettings)
