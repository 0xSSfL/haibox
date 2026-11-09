"""Host-only VPN profile storage and validation.

VPN configuration files contain credentials and private keys. They live under
the HAIBOX data directory with mode 0600, are never embedded in YAML, and are
never mounted into an engagement runner. Only the trusted gateway container
receives the configuration file, read-only.
"""

from __future__ import annotations

import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import ValidationError as PydanticValidationError

from haibox.errors import VpnError
from haibox.models import VpnProfile
from haibox.paths import Paths, validate_vpn_name
from haibox.runtime.vpn_spec import VpnGatewaySpec
from haibox.utils.time import utc_now

VpnType = Literal["wireguard", "openvpn"]

_MAX_CONFIG_BYTES = 1024 * 1024
_WIREGUARD_FORBIDDEN = frozenset(
    {"postup", "postdown", "preup", "predown", "saveconfig"}
)
_OPENVPN_FORBIDDEN = frozenset(
    {
        "askpass",
        "auth-user-pass-verify",
        "client-connect",
        "client-disconnect",
        "config",
        "down",
        "ipchange",
        "learn-address",
        "management",
        "management-client",
        "management-query-passwords",
        "plugin",
        "route-up",
        "script-security",
        "tls-verify",
        "up",
    }
)


def _read_source(path: Path) -> str:
    """Read a regular file without following symlinks."""

    if path.is_symlink():
        raise VpnError(f"VPN config must not be a symbolic link: {path}")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except OSError as exc:
        raise VpnError(f"cannot read VPN config {path}: {exc}") from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            raise VpnError(f"VPN config is not a regular file: {path}")
        if info.st_size > _MAX_CONFIG_BYTES:
            raise VpnError(f"VPN config is larger than {_MAX_CONFIG_BYTES} bytes")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            data = handle.read(_MAX_CONFIG_BYTES + 1)
    finally:
        os.close(descriptor)
    if len(data) > _MAX_CONFIG_BYTES:
        raise VpnError(f"VPN config is larger than {_MAX_CONFIG_BYTES} bytes")
    if b"\x00" in data:
        raise VpnError("VPN config must be a text file")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise VpnError("VPN config must be UTF-8 text") from exc


def _lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _validate_wireguard(text: str) -> None:
    sections: set[str] = set()
    keys: set[str] = set()
    for line in _lines(text):
        if line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            sections.add(line[1:-1].strip().lower())
            continue
        key, separator, _value = line.partition("=")
        if not separator:
            raise VpnError(f"invalid WireGuard line: {line!r}")
        key = key.strip().lower()
        if key in _WIREGUARD_FORBIDDEN:
            raise VpnError(f"WireGuard directive is not allowed: {key}")
        keys.add(key)
    if "interface" not in sections:
        raise VpnError("WireGuard config must contain an [Interface] section")
    if "peer" not in sections:
        raise VpnError("WireGuard config must contain a [Peer] section")
    for required in ("privatekey", "publickey", "endpoint"):
        if required not in keys:
            raise VpnError(f"WireGuard config is missing {required}")


def _validate_openvpn(text: str) -> None:
    has_client = False
    has_remote = False
    for line in _lines(text):
        if line.startswith("#") or line.startswith(";"):
            continue
        if line.startswith("<") and line.endswith(">"):
            continue
        parts = line.split(None, 1)
        directive = parts[0].lower()
        if directive in _OPENVPN_FORBIDDEN:
            raise VpnError(f"OpenVPN directive is not allowed: {directive}")
        if directive == "client":
            has_client = True
        if directive == "remote":
            if len(parts) < 2 or not parts[1].strip():
                raise VpnError("OpenVPN remote directive requires a host")
            has_remote = True
    if not has_remote:
        raise VpnError("OpenVPN config must contain a remote directive")
    if not has_client:
        raise VpnError("OpenVPN config must contain the client directive")


def validate_vpn_config(vpn_type: VpnType, text: str) -> None:
    if not text.strip():
        raise VpnError("VPN config is empty")
    if vpn_type == "wireguard":
        _validate_wireguard(text)
    elif vpn_type == "openvpn":
        _validate_openvpn(text)
    else:
        raise VpnError(f"unsupported VPN type: {vpn_type}")


def _atomic_write(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".tmp", dir=str(path.parent)
    )
    temp = Path(temp_name)
    try:
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
        path.chmod(mode)
    except OSError:
        temp.unlink(missing_ok=True)
        raise


def _check_private(path: Path) -> None:
    mode = path.stat().st_mode & 0o777
    if mode & 0o077:
        raise VpnError(f"{path} must not be group- or world-accessible")


class VpnStore:
    """Host-only VPN profile store."""

    def __init__(self, paths: Paths) -> None:
        self.paths = paths

    def add(
        self,
        name: str,
        vpn_type: VpnType,
        source: Path,
        *,
        description: str = "",
        force: bool = False,
    ) -> VpnProfile:
        validate_vpn_name(name)
        if vpn_type not in ("wireguard", "openvpn"):
            raise VpnError(f"unsupported VPN type: {vpn_type}")
        self.paths.ensure()
        root = self.paths.vpn_profile_dir(name)
        if root.is_symlink():
            raise VpnError(f"VPN profile directory must not be a symbolic link: {root}")
        if root.exists() and not root.is_dir():
            raise VpnError(f"VPN profile path is not a directory: {root}")
        if root.exists() and not force:
            raise VpnError(f"VPN profile already exists: {name}")

        text = _read_source(source)
        validate_vpn_config(vpn_type, text)

        now = utc_now()
        created_at = now
        if root.exists():
            created_at = self.load(name).created_at
        profile = VpnProfile(
            name=name,
            type=vpn_type,
            description=description,
            created_at=created_at,
            updated_at=now,
        )

        temp_dir = Path(
            tempfile.mkdtemp(prefix=f".{name}-", dir=str(self.paths.vpn_dir))
        )
        try:
            temp_dir.chmod(0o700)
            _atomic_write(temp_dir / "vpn.conf", text.encode("utf-8"), 0o600)
            _atomic_write(
                temp_dir / "profile.yaml",
                yaml.safe_dump(
                    profile.model_dump(mode="json"),
                    sort_keys=False,
                    allow_unicode=True,
                ).encode("utf-8"),
                0o600,
            )
            if root.exists():
                shutil.rmtree(root)
            temp_dir.replace(root)
        except Exception:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise
        return profile

    def load(self, name: str) -> VpnProfile:
        validate_vpn_name(name)
        profile_path = self.paths.vpn_profile_file(name)
        if profile_path.is_symlink():
            raise VpnError(f"VPN profile file must not be a symbolic link: {profile_path}")
        if not profile_path.is_file():
            raise VpnError(f"VPN profile not found: {name}")
        try:
            raw: Any = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise VpnError(f"cannot read VPN profile {name}: {exc}") from exc
        if not isinstance(raw, dict):
            raise VpnError(f"VPN profile is not a mapping: {profile_path}")
        try:
            profile = VpnProfile.model_validate(raw)
        except PydanticValidationError as exc:
            raise VpnError(f"invalid VPN profile {name}: {exc}") from exc
        if profile.name != name:
            raise VpnError(f"VPN profile name mismatch in {profile_path}")
        config_path = self.paths.vpn_config_file(name)
        if config_path.is_symlink():
            raise VpnError(f"VPN config must not be a symbolic link: {config_path}")
        if not config_path.is_file():
            raise VpnError(f"VPN config not found: {config_path}")
        _check_private(profile_path)
        _check_private(config_path)
        return profile

    def list(self) -> list[VpnProfile]:
        if not self.paths.vpn_dir.is_dir():
            return []
        profiles: list[VpnProfile] = []
        for path in sorted(self.paths.vpn_dir.iterdir()):
            if path.is_symlink():
                raise VpnError(f"VPN profile directory must not be a symbolic link: {path}")
            if path.is_dir() and (path / "profile.yaml").is_file():
                profiles.append(self.load(path.name))
        return profiles

    def config_path(self, name: str) -> Path:
        self.load(name)
        return self.paths.vpn_config_file(name)

    def gateway_spec(self, name: str) -> VpnGatewaySpec:
        profile = self.load(name)
        return VpnGatewaySpec(
            profile_name=profile.name,
            vpn_type=profile.type,
            config_file=self.config_path(name),
        )

    def remove(self, name: str) -> None:
        self.load(name)
        root = self.paths.vpn_profile_dir(name)
        if root.is_symlink():
            raise VpnError(f"VPN profile directory must not be a symbolic link: {root}")
        shutil.rmtree(root)
