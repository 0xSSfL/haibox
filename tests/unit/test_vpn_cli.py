"""VPN CLI wiring tests using the fake runtime."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from haibox.paths import Paths
from haibox.runtime.vpn_spec import VPN_GATEWAY_IMAGE
from tests.conftest import invoke
from tests.fakes import FakeRuntime

WIREGUARD = """\
[Interface]
PrivateKey = private-key-placeholder
Address = 10.66.0.2/32

[Peer]
PublicKey = public-key-placeholder
Endpoint = vpn.example.test:51820
AllowedIPs = 0.0.0.0/0
"""


def _source(tmp_path: Path) -> Path:
    path = tmp_path / "wg.conf"
    path.write_text(WIREGUARD, encoding="utf-8")
    return path


def _error(result) -> str:
    if result.exception is not None:
        return str(result.exception)
    return result.output


def _add(
    runner: CliRunner,
    paths: Paths,
    tmp_path: Path,
    *,
    name: str = "lab",
    vpn_type: str = "wireguard",
) -> None:
    result = invoke(
        runner,
        paths,
        "vpn",
        "add",
        name,
        "--type",
        vpn_type,
        "--config",
        str(_source(tmp_path)),
    )
    assert result.exit_code == 0, result.output


def test_vpn_add_list_show_and_remove(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    _add(cli_runner, paths, tmp_path)

    result = invoke(cli_runner, paths, "vpn", "list")
    assert result.exit_code == 0, result.output
    assert "lab" in result.output
    assert "wireguard" in result.output

    result = invoke(cli_runner, paths, "vpn", "show", "lab")
    assert result.exit_code == 0, result.output
    assert "type: wireguard" in result.output
    assert "private-key-placeholder" not in result.output
    assert str(paths.vpn_config_file("lab")) in result.output

    result = invoke(cli_runner, paths, "vpn", "remove", "lab", "--yes")
    assert result.exit_code == 0, result.output
    assert not paths.vpn_profile_dir("lab").exists()


def test_vpn_status_before_and_after_up(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    _add(cli_runner, paths, tmp_path)

    result = invoke(cli_runner, paths, "vpn", "status")
    assert result.exit_code == 0, result.output
    assert "not running" in result.output
    assert "not implemented" in result.output

    result = invoke(cli_runner, paths, "vpn", "up", "lab")
    assert result.exit_code == 0, result.output
    assert "started" in result.output.lower()
    assert "not implemented" in result.output
    assert cli.called("create_vpn_gateway")
    assert cli.containers["haibox-vpn-lab"].running
    assert cli.vpn_networks["haibox-vpn-lab-net"] == "lab"

    result = invoke(cli_runner, paths, "vpn", "status", "lab", "--json")
    assert result.exit_code == 0, result.output
    assert '"routing": "not implemented"' in result.output
    assert '"state": "Up"' in result.output

    result = invoke(cli_runner, paths, "vpn", "down", "lab")
    assert result.exit_code == 0, result.output
    assert "haibox-vpn-lab" not in cli.containers
    assert "haibox-vpn-lab-net" not in cli.vpn_networks


def test_vpn_up_requires_the_gateway_image(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    _add(cli_runner, paths, tmp_path)
    cli.missing_images.add(VPN_GATEWAY_IMAGE)
    result = invoke(cli_runner, paths, "vpn", "up", "lab")
    assert result.exit_code != 0
    assert "not present" in _error(result)


def test_vpn_down_works_after_the_profile_is_damaged(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    _add(cli_runner, paths, tmp_path)
    assert invoke(cli_runner, paths, "vpn", "up", "lab").exit_code == 0
    paths.vpn_config_file("lab").unlink()

    result = invoke(cli_runner, paths, "vpn", "down", "lab")
    assert result.exit_code == 0, result.output
    assert "haibox-vpn-lab" not in cli.containers
    assert "haibox-vpn-lab-net" not in cli.vpn_networks


def test_vpn_down_is_idempotent(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    _add(cli_runner, paths, tmp_path)
    result = invoke(cli_runner, paths, "vpn", "down", "lab")
    assert result.exit_code == 0, result.output


def test_vpn_remove_refuses_while_the_gateway_exists(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    _add(cli_runner, paths, tmp_path)
    assert invoke(cli_runner, paths, "vpn", "up", "lab").exit_code == 0
    result = invoke(cli_runner, paths, "vpn", "remove", "lab", "--yes")
    assert result.exit_code != 0
    assert "vpn down" in _error(result)


def test_vpn_add_rejects_an_unknown_type(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    result = invoke(
        cli_runner,
        paths,
        "vpn",
        "add",
        "lab",
        "--type",
        "ipsec",
        "--config",
        str(_source(tmp_path)),
    )
    assert result.exit_code != 0
    assert "unsupported VPN type" in _error(result)


def test_vpn_add_rejects_a_duplicate(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    _add(cli_runner, paths, tmp_path)
    result = invoke(
        cli_runner,
        paths,
        "vpn",
        "add",
        "lab",
        "--type",
        "wireguard",
        "--config",
        str(_source(tmp_path)),
    )
    assert result.exit_code != 0
    assert "already exists" in _error(result)


def test_vpn_show_unknown_profile(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    result = invoke(cli_runner, paths, "vpn", "show", "missing")
    assert result.exit_code != 0
    assert "not found" in _error(result)


def test_vpn_add_rejects_a_symlink_source(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    source = _source(tmp_path)
    link = tmp_path / "link.conf"
    link.symlink_to(source)
    result = invoke(
        cli_runner,
        paths,
        "vpn",
        "add",
        "lab",
        "--type",
        "wireguard",
        "--config",
        str(link),
    )
    assert result.exit_code != 0
    assert "symbolic link" in _error(result)


@pytest.mark.parametrize("name", ["../escape", "UPPER", "with space", ""])
def test_vpn_add_rejects_invalid_names(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path, name: str
) -> None:
    result = invoke(
        cli_runner,
        paths,
        "vpn",
        "add",
        name,
        "--type",
        "wireguard",
        "--config",
        str(_source(tmp_path)),
    )
    assert result.exit_code != 0
