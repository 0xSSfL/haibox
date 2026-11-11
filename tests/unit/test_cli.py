"""CLI smoke and wiring tests.

Every runtime call goes through the fake Docker adapter.  These tests check
command registration, option handling, audit side effects, and exit codes, not
the Docker adapter itself (that is covered in ``test_runtime.py``).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from haibox.audit import AuditLog
from haibox.cli.app import main
from haibox.errors import VpnError
from haibox.evidence import EvidenceStore
from haibox.paths import Paths
from haibox.runtime.base import ExecResult
from tests.conftest import invoke
from tests.fakes import FakeRuntime

# Engagement containers refuse UID/GID 0. The CLI defaults to the invoking
# user, so these tests require a normal non-root account.
pytestmark = pytest.mark.skipif(
    os.geteuid() == 0, reason="run the CLI tests as a non-root user"
)


def _init_demo(
    runner: CliRunner,
    paths: Paths,
    *,
    engagement_id: str = "demo",
    extra: tuple[str, ...] = (),
) -> None:
    result = invoke(
        runner,
        paths,
        "engagement",
        "init",
        engagement_id,
        "--name",
        "Demo",
        "--target",
        "10.10.20.5",
        "--allowed-port",
        "443",
        *extra,
    )
    assert result.exit_code == 0, result.output
    assert "created" in result.output.lower()


def test_version(cli_runner: CliRunner, paths: Paths) -> None:
    from haibox.version import __version__

    result = invoke(cli_runner, paths, "version")
    assert result.exit_code == 0
    assert result.output.strip() == __version__


def test_main_turns_expected_errors_into_a_clean_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import importlib

    module = importlib.import_module("haibox.cli.app")

    def fail() -> None:
        raise VpnError("expected failure")

    # ``haibox.cli`` re-exports ``app``, so patching by dotted path would hit
    # the Typer object rather than the module attribute ``main`` reads.
    monkeypatch.setattr(module, "app", fail)
    with pytest.raises(SystemExit) as excinfo:
        main()
    assert excinfo.value.code == 1


def test_init_writes_a_default_config(cli_runner: CliRunner, paths: Paths) -> None:
    result = invoke(cli_runner, paths, "init")
    assert result.exit_code == 0
    assert paths.config_file.is_file()
    payload = yaml.safe_load(paths.config_file.read_text(encoding="utf-8"))
    assert payload["docker"]["context"] == "haibox"
    assert payload["defaults"]["profile"] == "web-security"
    assert payload["network"]["profile"] == "isolated"


def test_config_show_and_path(cli_runner: CliRunner, paths: Paths) -> None:
    result = invoke(cli_runner, paths, "config", "path")
    assert result.exit_code == 0
    assert result.output.strip() == str(paths.config_file)

    result = invoke(cli_runner, paths, "config", "show")
    assert result.exit_code == 0
    payload = yaml.safe_load(result.output)
    assert payload["docker"]["require_dedicated_context"] is True
    assert payload["network"]["profile"] == "isolated"


def test_doctor_succeeds_with_defaults_and_the_fake_runtime(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    result = invoke(cli_runner, paths, "doctor")
    assert result.exit_code == 0, result.output
    assert "docker daemon" in result.output
    assert "ok" in result.output


def test_doctor_json(cli_runner: CliRunner, paths: Paths, cli: FakeRuntime) -> None:
    result = invoke(cli_runner, paths, "doctor", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    checks = {item["name"]: item for item in payload["checks"]}
    assert checks["docker daemon"]["ok"] is True
    assert checks["configuration"]["detail"] == "built-in defaults"


def test_doctor_reports_a_missing_daemon(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    cli.available = False
    result = invoke(cli_runner, paths, "doctor")
    assert result.exit_code == 1
    assert "fail" in result.output


def test_engagement_lifecycle(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    _init_demo(cli_runner, paths)

    result = invoke(cli_runner, paths, "engagement", "list")
    assert result.exit_code == 0
    assert "demo" in result.output
    assert "web-security" in result.output

    result = invoke(cli_runner, paths, "engagement", "show", "demo", "--json")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["id"] == "demo"
    assert payload["runtime"]["uid"] == os.getuid()
    assert payload["runtime"]["network_name"] == "haibox-demo-net"
    assert payload["scope"]["allowed"] == ["10.10.20.5"]

    result = invoke(cli_runner, paths, "engagement", "current")
    assert result.exit_code == 0
    assert result.output.strip() == "demo"

    result = invoke(cli_runner, paths, "engagement", "use", "demo")
    assert result.exit_code == 0

    result = invoke(cli_runner, paths, "engagement", "archive", "demo")
    assert result.exit_code == 0
    assert paths.current_file.exists() is False

    result = invoke(cli_runner, paths, "engagement", "destroy", "demo", "--force", "--yes")
    assert result.exit_code == 0, result.output
    assert not paths.engagement_dir("demo").exists()


def test_engagement_init_requires_a_target(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    result = invoke(cli_runner, paths, "engagement", "init", "demo")
    assert result.exit_code != 0

    result = invoke(
        cli_runner,
        paths,
        "engagement",
        "init",
        "empty",
        "--allow-empty-scope",
    )
    assert result.exit_code == 0, result.output


def test_engagement_destroy_refuses_an_active_engagement_without_force(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    _init_demo(cli_runner, paths)
    result = invoke(cli_runner, paths, "engagement", "destroy", "demo", "--yes")
    assert result.exit_code != 0
    assert paths.engagement_dir("demo").exists()


def test_engagement_init_rejects_an_invalid_id(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    result = invoke(
        cli_runner,
        paths,
        "engagement",
        "init",
        "../escape",
        "--target",
        "10.10.20.5",
    )
    assert result.exit_code != 0
    assert not (paths.data_dir / "escape").exists()


def test_container_lifecycle(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    _init_demo(cli_runner, paths)

    result = invoke(cli_runner, paths, "container", "create", "demo")
    assert result.exit_code == 0, result.output
    assert "haibox-demo" in result.output
    assert cli.called("create_container")

    result = invoke(cli_runner, paths, "container", "start", "demo")
    assert result.exit_code == 0, result.output
    assert cli.containers["haibox-demo"].running

    result = invoke(cli_runner, paths, "container", "stop", "demo")
    assert result.exit_code == 0, result.output
    assert not cli.containers["haibox-demo"].running

    result = invoke(cli_runner, paths, "container", "restart", "demo")
    assert result.exit_code == 0, result.output
    assert cli.containers["haibox-demo"].running

    result = invoke(cli_runner, paths, "container", "ps")
    assert result.exit_code == 0
    assert "haibox-demo" in result.output

    result = invoke(cli_runner, paths, "container", "inspect", "demo")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["name"] == "haibox-demo"

    result = invoke(cli_runner, paths, "container", "logs", "demo", "--tail", "10")
    assert result.exit_code == 0
    assert "fake log line" in result.output

    result = invoke(cli_runner, paths, "container", "rm", "demo", "--yes")
    assert result.exit_code == 0, result.output
    assert "haibox-demo" not in cli.containers


def test_container_create_refuses_a_duplicate(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    _init_demo(cli_runner, paths)
    assert invoke(cli_runner, paths, "container", "create", "demo").exit_code == 0
    result = invoke(cli_runner, paths, "container", "create", "demo")
    assert result.exit_code != 0
    assert "already exists" in result.output.lower() or result.exception is not None


def test_shell_and_run(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    _init_demo(cli_runner, paths)

    cli.exec_results.append(ExecResult(exit_code=0, stdout="hello\n", stderr=""))
    result = invoke(cli_runner, paths, "run", "echo", "hello")
    assert result.exit_code == 0, result.output
    assert "hello" in result.output
    assert cli.called("exec_capture")
    assert cli.called("create_container")
    assert cli.containers["haibox-demo"].running

    cli.exec_results.append(ExecResult(exit_code=3, stdout="", stderr="boom\n"))
    result = invoke(cli_runner, paths, "run", "false")
    assert result.exit_code == 3
    assert "boom" in result.output

    result = invoke(cli_runner, paths, "shell")
    assert result.exit_code == 0, result.output
    assert cli.called("exec_interactive")


def test_scope_show_and_check(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    _init_demo(cli_runner, paths)

    result = invoke(cli_runner, paths, "scope", "show", "demo")
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["allowed"] == ["10.10.20.5"]

    result = invoke(
        cli_runner, paths, "scope", "check", "10.10.20.5", "--port", "443"
    )
    assert result.exit_code == 0, result.output
    assert "allowed" in result.output

    result = invoke(cli_runner, paths, "scope", "check", "10.10.20.6")
    assert result.exit_code == 1
    assert "denied" in result.output

    entries = AuditLog(paths.engagement_audit_file("demo")).read()
    assert any(entry["event"] == "scope.checked" for entry in entries)


def test_evidence_commands(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime, tmp_path: Path
) -> None:
    _init_demo(cli_runner, paths)
    source = tmp_path / "finding.txt"
    source.write_text("proof\n", encoding="utf-8")

    result = invoke(
        cli_runner,
        paths,
        "evidence",
        "add",
        str(source),
        "--note",
        "finding",
        "--tag",
        "xss",
    )
    assert result.exit_code == 0, result.output
    assert "SHA-256" in result.output

    entries = EvidenceStore(paths.evidence_dir("demo")).list()
    assert len(entries) == 1
    evidence_id = entries[0].id

    result = invoke(cli_runner, paths, "evidence", "list")
    assert result.exit_code == 0
    assert "finding.txt" in result.output
    assert evidence_id in result.output

    result = invoke(cli_runner, paths, "evidence", "verify")
    assert result.exit_code == 0, result.output
    assert "valid" in result.output

    result = invoke(cli_runner, paths, "evidence", "rm", evidence_id, "--yes")
    assert result.exit_code == 0, result.output
    assert EvidenceStore(paths.evidence_dir("demo")).list() == []


def test_secret_commands_never_print_the_value(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    _init_demo(cli_runner, paths)

    result = invoke(
        cli_runner,
        paths,
        "secret",
        "set",
        "api_key",
        input_text="s3cret-value\ns3cret-value\n",
    )
    assert result.exit_code == 0, result.output
    assert "s3cret-value" not in result.output
    assert "Stored secret" in result.output

    result = invoke(cli_runner, paths, "secret", "list")
    assert result.exit_code == 0
    assert "api_key" in result.output
    assert "s3cret-value" not in result.output

    audit_text = paths.engagement_audit_file("demo").read_text(encoding="utf-8")
    assert "s3cret-value" not in audit_text

    result = invoke(cli_runner, paths, "secret", "rm", "api_key", "--yes")
    assert result.exit_code == 0, result.output
    assert "api_key" not in invoke(cli_runner, paths, "secret", "list").output


def test_audit_verify_and_tail(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    _init_demo(cli_runner, paths)

    result = invoke(cli_runner, paths, "audit", "verify")
    assert result.exit_code == 0, result.output
    assert "valid" in result.output

    result = invoke(cli_runner, paths, "audit", "verify", "--engagement", "demo")
    assert result.exit_code == 0, result.output

    result = invoke(cli_runner, paths, "audit", "tail", "-n", "5")
    assert result.exit_code == 0
    lines = [line for line in result.output.splitlines() if line.strip()]
    assert lines
    for line in lines:
        json.loads(line)

    result = invoke(cli_runner, paths, "audit", "tail", "-n", "0")
    assert result.exit_code != 0


def test_image_list_and_inspect(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    result = invoke(cli_runner, paths, "image", "list")
    assert result.exit_code == 0, result.output
    assert "web-security" in result.output

    result = invoke(cli_runner, paths, "image", "inspect", "web-security")
    assert result.exit_code == 0
    payload = yaml.safe_load(result.output)
    assert payload["name"] == "web-security"
    assert payload["base"].startswith("debian:13-slim@sha256:")


def test_image_build_verify_and_scan_use_the_runtime(
    cli_runner: CliRunner,
    paths: Paths,
    cli: FakeRuntime,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli.ephemeral_result = ExecResult(exit_code=0, stdout="verified\n", stderr="")

    result = invoke(cli_runner, paths, "image", "build", "web-security")
    assert result.exit_code == 0, result.output
    assert cli.called("build_image")

    result = invoke(cli_runner, paths, "image", "verify", "web-security")
    assert result.exit_code == 0, result.output
    assert "verified" in result.output
    assert cli.called("run_ephemeral")

    class StubScanner:
        def scan(
            self,
            image: str,
            *,
            timeout: int = 1800,
            ignorefile: Path | None = None,
        ):
            del timeout
            assert image == "haibox/web-security:0.1.0"
            assert ignorefile is not None
            assert ignorefile.name == "trivyignore.yaml"
            from haibox.images.scan import ScanResult

            return ScanResult(tool="trivy", exit_code=0, output="clean")

    monkeypatch.setattr("haibox.cli.image_cmd.ImageScanner", StubScanner)

    result = invoke(cli_runner, paths, "image", "scan", "web-security")
    assert result.exit_code == 0, result.output
    assert "clean" in result.output


@pytest.mark.parametrize(
    ("result_kwargs", "expected"),
    [
        (
            {
                "tool": "trivy",
                "exit_code": 1,
                "output": "",
                "covered": False,
            },
            "did not scan OS packages",
        ),
        (
            {
                "tool": "grype",
                "exit_code": 1,
                "output": "",
                "findings": 2,
            },
            "reported 2 HIGH/CRITICAL",
        ),
    ],
)
def test_image_scan_fails_when_the_scan_is_incomplete(
    cli_runner: CliRunner,
    paths: Paths,
    cli: FakeRuntime,
    monkeypatch: pytest.MonkeyPatch,
    result_kwargs,
    expected: str,
) -> None:
    from haibox.images.scan import ScanResult

    class StubScanner:
        def scan(
            self,
            image: str,
            *,
            timeout: int = 1800,
            ignorefile: Path | None = None,
        ):
            del image, timeout, ignorefile
            return ScanResult(**result_kwargs)

    monkeypatch.setattr("haibox.cli.image_cmd.ImageScanner", StubScanner)

    result = invoke(cli_runner, paths, "image", "scan", "web-security")
    assert result.exit_code != 0
    assert result.exception is not None
    assert expected in str(result.exception)


def test_unknown_engagement_is_an_error(
    cli_runner: CliRunner, paths: Paths, cli: FakeRuntime
) -> None:
    result = invoke(cli_runner, paths, "engagement", "show", "missing", "--json")
    assert result.exit_code != 0
    assert result.exception is not None


def test_ui_banner(capsys: pytest.CaptureFixture[str]) -> None:
    from haibox.cli.ui import banner

    banner()
    captured = capsys.readouterr()
    assert "isolation-first pentest platform" in captured.out

