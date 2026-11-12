"""CLI tests for the optional GUI commands.

The commands are prepared but stay disabled while the GUI image is
experimental, so most of these tests assert the refusal path and the gate
itself.  The gate is the catalog status of the GUI image: there is no flag
and no environment variable that can bypass it.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from haibox.cli.gui_cmd import GuiNotEnabled, gui_enabled
from haibox.engagement import EngagementManager
from haibox.gui.errors import GuiPreflightError
from haibox.models import Scope
from haibox.runtime.base import ContainerInfo, ExecResult
from tests.conftest import invoke

CATALOG = Path(__file__).resolve().parents[2] / "images"


@pytest.fixture
def gui_catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Provide an image catalog with a GUI image whose status the test controls."""

    root = tmp_path / "images"
    (root / "gui").mkdir(parents=True)
    (root / "gui" / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
    monkeypatch.setenv("HAIBOX_IMAGES_DIR", str(root))
    return root


def _write_gui_manifest(root: Path, status: str) -> None:
    manifest = {
        "api_version": "haibox/v1",
        "name": "gui",
        "version": "0.1.0",
        "status": status,
        "base": "fedora:46@sha256:" + "0" * 64,
        "tools": [{"name": "xpra", "version": "6.5.6-1.fc46", "verify": "xpra --version"}],
    }
    (root / "gui" / "manifest.yaml").write_text(
        yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8"
    )


def test_gui_commands_refuse_while_the_image_is_experimental(
    cli_runner: CliRunner, paths, cli, gui_catalog: Path
) -> None:
    _write_gui_manifest(gui_catalog, "experimental")
    paths.ensure()

    result = invoke(cli_runner, paths, "gui", "status", "demo")

    assert result.exit_code == 1
    assert isinstance(result.exception, GuiNotEnabled)
    assert "not enabled" in str(result.exception)
    assert result.exception.exit_code == 2


def test_gui_gate_reports_the_reason(
    cli_runner: CliRunner, paths, cli, gui_catalog: Path
) -> None:
    _write_gui_manifest(gui_catalog, "experimental")
    paths.ensure()

    enabled, reason = gui_enabled()

    assert enabled is False
    assert "experimental" in reason


def test_gui_gate_refuses_without_an_image_definition(
    cli_runner: CliRunner, paths, cli, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HAIBOX_IMAGES_DIR", str(tmp_path / "empty"))
    paths.ensure()

    enabled, reason = gui_enabled()

    assert enabled is False
    assert "unavailable" in reason


def test_gui_commands_are_listed(
    cli_runner: CliRunner, paths, cli, gui_catalog: Path
) -> None:
    _write_gui_manifest(gui_catalog, "experimental")
    paths.ensure()

    result = invoke(cli_runner, paths, "gui", "--help")

    assert result.exit_code == 0
    for command in ("start", "attach", "stop", "status"):
        assert command in result.output


def test_gui_start_refuses_and_writes_no_session(
    cli_runner: CliRunner, paths, cli, gui_catalog: Path
) -> None:
    _write_gui_manifest(gui_catalog, "experimental")
    paths.ensure()
    EngagementManager(paths).create(
        "demo", name="Demo", scope=Scope(), uid=1000, gid=1000
    )

    result = invoke(cli_runner, paths, "gui", "start", "demo")

    assert result.exit_code == 1
    assert isinstance(result.exception, GuiNotEnabled)
    assert "not enabled" in str(result.exception)
    assert not (paths.logs_dir / "gui").exists()


def test_doctor_reports_the_gui_state_without_failing(
    cli_runner: CliRunner, paths, cli, gui_catalog: Path
) -> None:
    _write_gui_manifest(gui_catalog, "experimental")
    paths.ensure()

    result = invoke(cli_runner, paths, "doctor", "--json")

    payload = json.loads(result.stdout)
    gui_checks = [check for check in payload["checks"] if check["name"].startswith("gui")]
    assert gui_checks
    assert all(check["ok"] for check in gui_checks)
    assert any("disabled" in check["detail"] for check in gui_checks)


def test_gui_status_works_when_the_image_is_active(
    cli_runner: CliRunner, paths, cli, gui_catalog: Path
) -> None:
    _write_gui_manifest(gui_catalog, "active")
    paths.ensure()
    engagement = EngagementManager(paths).create(
        "demo",
        name="Demo",
        scope=Scope(),
        image="haibox/gui:0.1.0",
        cpus=2.0,
        memory="2g",
        pids_limit=512,
        uid=1000,
        gid=1000,
    )
    cli.containers[engagement.runtime.container_name] = ContainerInfo(
        id="fake-0001",
        name=engagement.runtime.container_name,
        image=engagement.image,
        state="running",
        status="Up",
        labels={
            "haibox.managed": "true",
            "haibox.engagement": engagement.id,
        },
        network_mode=engagement.runtime.network_name,
        networks=(engagement.runtime.network_name,),
    )

    cli.exec_results = [
        ExecResult(
            exit_code=0,
            stdout=json.dumps(
                {"ours": [], "foreign": [], "stoppers": [], "argv": {}, "uncertain": False}
            ),
            stderr="",
        )
    ]

    result = invoke(cli_runner, paths, "--json", "gui", "status", "demo")

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["engagement"] == "demo"
    assert payload["running"] is False


def test_gui_status_refuses_an_engagement_with_external_targets(
    cli_runner: CliRunner, paths, cli, gui_catalog: Path
) -> None:
    _write_gui_manifest(gui_catalog, "active")
    paths.ensure()
    engagement = EngagementManager(paths).create(
        "demo",
        name="Demo",
        scope=Scope(allowed=["10.10.20.5"]),
        image="haibox/gui:0.1.0",
        cpus=2.0,
        memory="2g",
        pids_limit=512,
        uid=1000,
        gid=1000,
    )
    cli.containers[engagement.runtime.container_name] = ContainerInfo(
        id="fake-0001",
        name=engagement.runtime.container_name,
        image=engagement.image,
        state="running",
        status="Up",
        labels={
            "haibox.managed": "true",
            "haibox.engagement": engagement.id,
        },
        network_mode=engagement.runtime.network_name,
        networks=(engagement.runtime.network_name,),
    )

    result = invoke(cli_runner, paths, "gui", "status", "demo")

    assert result.exit_code == 1
    assert isinstance(result.exception, GuiPreflightError)
    assert "external targets" in str(result.exception)
