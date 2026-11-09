"""The separate, explicitly privileged VPN gateway specification.

A VPN gateway needs ``NET_ADMIN`` and ``/dev/net/tun`` to create a tunnel. The
engagement runner never receives either. This spec is intentionally separate
from :class:`haibox.runtime.spec.ContainerSpec` so a normal engagement profile
cannot request these privileges.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from haibox.errors import ValidationError

_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
_IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]*$")
_MEMORY_RE = re.compile(r"^[1-9][0-9]*[bkmg]?$", re.IGNORECASE)

VPN_GATEWAY_IMAGE = "haibox/vpn-gateway:0.1.0"


@dataclass(frozen=True)
class VpnGatewaySpec:
    profile_name: str
    vpn_type: Literal["wireguard", "openvpn"]
    config_file: Path
    image: str = VPN_GATEWAY_IMAGE
    cpus: float = 1.0
    memory: str = "512m"
    pids_limit: int = 128

    def __post_init__(self) -> None:
        if not _NAME_RE.fullmatch(self.profile_name):
            raise ValidationError(f"invalid VPN profile name: {self.profile_name!r}")
        if self.vpn_type not in ("wireguard", "openvpn"):
            raise ValidationError(f"unsupported VPN type: {self.vpn_type!r}")
        if not _IMAGE_RE.fullmatch(self.image) or self.image.startswith("-"):
            raise ValidationError(f"invalid gateway image reference: {self.image!r}")
        if not 0 < self.cpus <= 8:
            raise ValidationError("gateway cpus must be between 0 and 8")
        if not _MEMORY_RE.fullmatch(self.memory):
            raise ValidationError("gateway memory must look like '512m'")
        if not 16 <= self.pids_limit <= 512:
            raise ValidationError("gateway pids_limit must be between 16 and 512")
        if not self.config_file.is_absolute():
            raise ValidationError("VPN config path must be absolute")
        if "," in str(self.config_file):
            raise ValidationError("VPN config path must not contain a comma")
        if self.config_file.is_symlink():
            raise ValidationError("VPN config path must not be a symbolic link")
        if not self.config_file.is_file():
            raise ValidationError(f"VPN config does not exist: {self.config_file}")

    @property
    def name(self) -> str:
        return f"haibox-vpn-{self.profile_name}"

    @property
    def network(self) -> str:
        return f"haibox-vpn-{self.profile_name}-net"

    @property
    def command(self) -> str:
        if self.vpn_type == "wireguard":
            return "wg-quick up /config/vpn.conf && exec sleep infinity"
        return "exec openvpn --config /config/vpn.conf --auth-nocache"

    def to_create_args(self) -> list[str]:
        args: list[str] = [
            "create",
            "--name",
            self.name,
            "--hostname",
            self.name,
            "--network",
            self.network,
            "--user",
            "0:0",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--tmpfs",
            "/run:rw,nosuid,nodev,noexec,size=32m",
            "--cap-drop",
            "ALL",
            "--cap-add",
            "NET_ADMIN",
            "--security-opt",
            "no-new-privileges:true",
            "--device",
            "/dev/net/tun:/dev/net/tun",
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
            "--label",
            "haibox.managed=true",
            "--label",
            "haibox.kind=vpn-gateway",
            "--label",
            f"haibox.vpn={self.profile_name}",
            "--label",
            f"haibox.image={self.image}",
            "--label",
            "haibox.created-by=haibox-platform",
            "--mount",
            f"type=bind,source={self.config_file},target=/config/vpn.conf,readonly",
            "--entrypoint",
            "/bin/sh",
            self.image,
            "-c",
            self.command,
        ]
        return args

    def describe(self) -> dict[str, object]:
        return {
            "profile": self.profile_name,
            "type": self.vpn_type,
            "name": self.name,
            "network": self.network,
            "image": self.image,
            "config_file": str(self.config_file),
            "cap_add": ["NET_ADMIN"],
            "devices": ["/dev/net/tun"],
            "read_only": True,
            "no_new_privileges": True,
        }
