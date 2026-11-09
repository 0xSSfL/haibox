"""VPN profile store and gateway specification tests."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from haibox.errors import ValidationError, VpnError
from haibox.paths import Paths
from haibox.runtime.vpn_spec import VPN_GATEWAY_IMAGE, VpnGatewaySpec
from haibox.vpn import VpnStore

WIREGUARD = """\
[Interface]
PrivateKey = private-key-placeholder
Address = 10.66.0.2/32
DNS = 10.66.0.1

[Peer]
PublicKey = public-key-placeholder
Endpoint = vpn.example.test:51820
AllowedIPs = 0.0.0.0/0
PersistentKeepalive = 25
"""

OPENVPN = """\
client
dev tun
proto udp
remote vpn.example.test 1194
resolv-retry infinite
nobind
persist-key
persist-tun
remote-cert-tls server
"""


@pytest.fixture
def store(paths: Paths) -> VpnStore:
    paths.ensure()
    return VpnStore(paths)


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_add_list_show_and_remove_wireguard(store: VpnStore, tmp_path: Path) -> None:
    source = _write(tmp_path, "wg.conf", WIREGUARD)
    profile = store.add("lab", "wireguard", source, description="Lab tunnel")

    assert profile.name == "lab"
    assert profile.type == "wireguard"
    assert profile.description == "Lab tunnel"
    assert [item.name for item in store.list()] == ["lab"]
    assert store.load("lab").name == "lab"

    config = store.config_path("lab")
    assert config.is_file()
    assert config.stat().st_mode & 0o777 == 0o600
    assert store.paths.vpn_profile_file("lab").stat().st_mode & 0o777 == 0o600
    assert store.paths.vpn_profile_dir("lab").stat().st_mode & 0o777 == 0o700

    metadata = store.paths.vpn_profile_file("lab").read_text(encoding="utf-8")
    assert "private-key-placeholder" not in metadata
    assert "public-key-placeholder" not in metadata

    store.remove("lab")
    assert store.list() == []


def test_add_openvpn(store: VpnStore, tmp_path: Path) -> None:
    profile = store.add("client", "openvpn", _write(tmp_path, "client.ovpn", OPENVPN))
    assert profile.type == "openvpn"
    assert store.gateway_spec("client").vpn_type == "openvpn"


def test_duplicate_requires_force(store: VpnStore, tmp_path: Path) -> None:
    source = _write(tmp_path, "wg.conf", WIREGUARD)
    store.add("lab", "wireguard", source)
    with pytest.raises(VpnError, match="already exists"):
        store.add("lab", "wireguard", source)
    replaced = store.add("lab", "wireguard", source, force=True)
    assert replaced.name == "lab"


def test_rejects_path_traversal(store: VpnStore, tmp_path: Path) -> None:
    source = _write(tmp_path, "wg.conf", WIREGUARD)
    with pytest.raises(VpnError, match="profile name"):
        store.add("../escape", "wireguard", source)


def test_rejects_symlink_source(store: VpnStore, tmp_path: Path) -> None:
    source = _write(tmp_path, "wg.conf", WIREGUARD)
    link = tmp_path / "link.conf"
    link.symlink_to(source)
    with pytest.raises(VpnError, match="symbolic link"):
        store.add("lab", "wireguard", link)


def test_rejects_wireguard_hooks(store: VpnStore, tmp_path: Path) -> None:
    source = _write(
        tmp_path,
        "wg.conf",
        WIREGUARD.replace("[Interface]", "[Interface]\nPostUp = touch /tmp/owned"),
    )
    with pytest.raises(VpnError, match="not allowed"):
        store.add("lab", "wireguard", source)


def test_rejects_openvpn_script_directives(store: VpnStore, tmp_path: Path) -> None:
    source = _write(
        tmp_path,
        "client.ovpn",
        OPENVPN + "script-security 2\nup /tmp/owned\n",
    )
    with pytest.raises(VpnError, match="not allowed"):
        store.add("client", "openvpn", source)


def test_rejects_openvpn_without_remote(store: VpnStore, tmp_path: Path) -> None:
    source = _write(tmp_path, "client.ovpn", "client\ndev tun\n")
    with pytest.raises(VpnError, match="remote"):
        store.add("client", "openvpn", source)


def test_rejects_world_readable_config(store: VpnStore, tmp_path: Path) -> None:
    store.add("lab", "wireguard", _write(tmp_path, "wg.conf", WIREGUARD))
    store.config_path("lab").chmod(0o644)
    with pytest.raises(VpnError, match="world-accessible"):
        store.load("lab")


def test_gateway_spec_is_separately_privileged(
    store: VpnStore, tmp_path: Path
) -> None:
    store.add("lab", "wireguard", _write(tmp_path, "wg.conf", WIREGUARD))
    spec = store.gateway_spec("lab")
    args = spec.to_create_args()

    assert spec.image == VPN_GATEWAY_IMAGE
    assert spec.name == "haibox-vpn-lab"
    assert spec.network == "haibox-vpn-lab-net"
    assert args[args.index("--cap-add") + 1] == "NET_ADMIN"
    assert args[args.index("--device") + 1] == "/dev/net/tun:/dev/net/tun"
    assert args[args.index("--user") + 1] == "0:0"
    assert "--read-only" in args
    assert "--privileged" not in args
    assert "--publish" not in args
    assert "-p" not in args
    assert args[args.index("--network") + 1] == "haibox-vpn-lab-net"
    mounts = [args[index + 1] for index, value in enumerate(args) if value == "--mount"]
    assert len(mounts) == 1
    assert f"source={spec.config_file},target=/config/vpn.conf,readonly" in mounts[0]
    described = spec.describe()
    assert described["cap_add"] == ["NET_ADMIN"]
    assert "private-key-placeholder" not in str(described)


def test_gateway_spec_rejects_a_symlink_config(tmp_path: Path) -> None:
    source = _write(tmp_path, "wg.conf", WIREGUARD)
    link = tmp_path / "link.conf"
    link.symlink_to(source)
    with pytest.raises(ValidationError, match="symbolic link"):
        VpnGatewaySpec(profile_name="lab", vpn_type="wireguard", config_file=link)


def test_gateway_spec_rejects_an_unexpected_type(tmp_path: Path) -> None:
    source = _write(tmp_path, "wg.conf", WIREGUARD)
    with pytest.raises(ValidationError):
        VpnGatewaySpec(profile_name="lab", vpn_type="ipsec", config_file=source)


def test_gateway_spec_is_frozen(store: VpnStore, tmp_path: Path) -> None:
    store.add("lab", "wireguard", _write(tmp_path, "wg.conf", WIREGUARD))
    spec = store.gateway_spec("lab")
    with pytest.raises(dataclasses.FrozenInstanceError):
        spec.profile_name = "other"
