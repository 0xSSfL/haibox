"""Regression tests for the disposable GUI prototype hardening.

These tests never call Docker. They exercise the prototype's fail-closed
preflight, private file handling, password rotation and cleanup, socket path
rules, and bounded relay teardown with fakes.
"""

from __future__ import annotations

import json
import socket
import stat
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from haibox.models import Scope
from haibox.scope import scope_to_json

GUI_RELAY_DIR = Path(__file__).resolve().parents[2] / "docs/superpowers/poc/gui-relay"
sys.path.insert(0, str(GUI_RELAY_DIR))

import relay  # noqa: E402
import security  # noqa: E402
import session  # noqa: E402


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


class FakeDocker:
    """Minimal docker CLI fake that models the Xpra server lifecycle."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_start = False
        self.stop_returncode = 0
        self.stop_timeout = False
        self.stop_stops_server = True
        self.server_pids: set[int] = set()
        self.foreign_pids: set[int] = set()
        self.listener_open = False
        self.listener_stays_open = False
        self.probe_error = ""
        self.scan_fails = False
        self.scan_uncertain = False
        self.scan_output: bytes | None = None
        self._next_pid = 4100

    def __call__(
        self,
        context: str,
        args: list[str],
        *,
        input_bytes: bytes | None = None,
        timeout: float = session.DOCKER_TIMEOUT,
    ) -> subprocess.CompletedProcess[bytes]:
        del context
        self.calls.append({"args": args, "input_bytes": input_bytes, "timeout": timeout})
        joined = " ".join(args)
        if "xpra" in args and "--version" in args:
            return subprocess.CompletedProcess(args, 0, b"xpra 6.5.4\n", b"")
        if "python3" in args and "-c" in args:
            return self._scan(args)
        if "xpra start" in joined:
            if self.fail_start:
                return subprocess.CompletedProcess(args, 1, b"", b"start failed")
            self._next_pid += 1
            self.server_pids.add(self._next_pid)
            self.listener_open = True
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if "xpra" in args and "stop" in args:
            if self.stop_timeout:
                # The stop reached the server but the command did not answer
                # in time; the real helper converts that into a SessionError.
                if self.stop_stops_server:
                    self.server_pids.clear()
                    self.listener_open = False
                raise session.SessionError("docker exec timed out after 30s")
            if self.stop_returncode == 0 and self.stop_stops_server:
                # A stop request that reaches the display stops every server
                # on it, including a foreign one.
                self.server_pids.clear()
                self.foreign_pids.clear()
                self.listener_open = False
            detail = b"" if self.stop_returncode == 0 else b"stop failed"
            return subprocess.CompletedProcess(args, self.stop_returncode, b"", detail)
        if "socat" in joined:
            if self.probe_error:
                return subprocess.CompletedProcess(args, 127, b"", self.probe_error.encode())
            if self.listener_open or self.listener_stays_open:
                return subprocess.CompletedProcess(args, 0, b"", b"")
            return subprocess.CompletedProcess(
                args,
                1,
                b"",
                b"socat: connect(4, AF=2 127.0.0.1:14500): Connection refused",
            )
        return subprocess.CompletedProcess(args, 0, b"", b"")

    def _scan(self, args: list[str]) -> subprocess.CompletedProcess[bytes]:
        if self.scan_fails:
            return subprocess.CompletedProcess(args, 1, b"", b"scan failed")
        if self.scan_output is not None:
            return subprocess.CompletedProcess(args, 0, self.scan_output, b"")
        payload = {
            "ours": sorted(self.server_pids),
            "foreign": sorted(self.foreign_pids),
            "uncertain": self.scan_uncertain,
        }
        return subprocess.CompletedProcess(args, 0, json.dumps(payload).encode(), b"")


@pytest.fixture
def fast_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the bounded verification loops short in unit tests."""

    monkeypatch.setattr(session, "STOP_VERIFY_TIMEOUT", 0.2)
    monkeypatch.setattr(session, "STOP_POLL_INTERVAL", 0.01)


@pytest.fixture
def session_state(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    return state


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> FakeDocker:
    docker = FakeDocker()

    def resolve(*_args: object, **_kwargs: object) -> tuple[str, Path]:
        return "haibox-gui-a", tmp_path / "workspace"

    monkeypatch.setattr(session, "resolve_engagement", resolve)
    monkeypatch.setattr(session, "_docker", docker)
    return docker


def _container_passwords(docker: FakeDocker) -> list[bytes]:
    return [
        call["input_bytes"]
        for call in docker.calls
        if isinstance(call["input_bytes"], bytes)
    ]


# --------------------------------------------------------------------- files


def test_password_file_is_private_and_rotation_replaces_content(session_state: Path) -> None:
    path = session_state / "gui-a.password"

    security.write_password_file(path, "first-password")
    assert path.read_text(encoding="utf-8") == "first-password"
    assert _mode(path) == 0o600

    security.write_password_file(path, "second-password")
    assert path.read_text(encoding="utf-8") == "second-password"
    assert _mode(path) == 0o600


def test_password_file_refuses_symlink_without_touching_target(session_state: Path) -> None:
    target = session_state / "target"
    target.write_text("original", encoding="utf-8")
    target.chmod(0o600)
    link = session_state / "gui-a.password"
    link.symlink_to(target)

    with pytest.raises(security.SecurityError, match="symlink"):
        security.write_password_file(link, "new-password")
    assert target.read_text(encoding="utf-8") == "original"

    assert security.remove_password_file(link) is True
    assert not link.is_symlink()
    assert target.read_text(encoding="utf-8") == "original"


def test_password_file_requires_private_parent(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)

    with pytest.raises(security.SecurityError, match="0700"):
        security.write_password_file(shared / "gui-a.password", "secret")
    assert not (shared / "gui-a.password").exists()


def test_private_directory_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real"
    target.mkdir()
    target.chmod(0o700)
    link = tmp_path / "link"
    link.symlink_to(target)

    with pytest.raises(security.SecurityError, match="symlink"):
        security.ensure_private_directory(link)


def test_remove_password_file_is_idempotent(tmp_path: Path) -> None:
    assert security.remove_password_file(tmp_path / "missing") is False


# ------------------------------------------------------------------- session


def test_prepare_creates_private_host_file_and_rotates_secrets(
    session_state: Path, fake_session: FakeDocker
) -> None:
    first = session.prepare(
        "gui-a",
        state_dir=session_state,
        data_dir=None,
        config_dir=None,
        context="haibox",
    )
    first_path = Path(str(first["password_file"]))
    first_password = first_path.read_text(encoding="utf-8")
    assert first_path.parent == session_state
    assert _mode(first_path) == 0o600
    assert first_password

    second = session.prepare(
        "gui-a",
        state_dir=session_state,
        data_dir=None,
        config_dir=None,
        context="haibox",
    )
    second_path = Path(str(second["password_file"]))
    second_password = second_path.read_text(encoding="utf-8")

    assert second_path == first_path
    assert second_password != first_password
    container_passwords = _container_passwords(fake_session)
    assert len(container_passwords) == 2
    assert container_passwords[0].decode() == first_password
    assert container_passwords[1].decode() == second_password
    assert all(call["timeout"] and call["timeout"] > 0 for call in fake_session.calls)

    for call in fake_session.calls:
        args = call["args"]
        assert isinstance(args, list)
        assert first_password not in " ".join(args)
        assert second_password not in " ".join(args)


def test_prepare_writes_container_password_in_private_runtime(
    session_state: Path, fake_session: FakeDocker
) -> None:
    session.prepare(
        "gui-a",
        state_dir=session_state,
        data_dir=None,
        config_dir=None,
        context="haibox",
    )

    write_calls = [
        call
        for call in fake_session.calls
        if isinstance(call["input_bytes"], bytes)
    ]
    assert len(write_calls) == 1
    command = " ".join(write_calls[0]["args"])
    assert command.count("umask 077") == 1
    assert "set -C" in command
    assert session.PASSWORD_FILE.startswith(f"{session.RUNTIME_DIR}/")
    assert "stat -c %a" in " ".join(
        str(call["args"]) for call in fake_session.calls if "stat -c %a" in str(call["args"])
    )


def test_prepare_stops_existing_server_before_resetting_runtime(
    session_state: Path, fake_session: FakeDocker
) -> None:
    session.prepare(
        "gui-a",
        state_dir=session_state,
        data_dir=None,
        config_dir=None,
        context="haibox",
    )

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    stop_index = next(index for index, command in enumerate(commands) if "xpra stop" in command)
    reset_index = next(index for index, command in enumerate(commands) if "rm -rf" in command)
    assert stop_index < reset_index
    assert sum("xpra start" in command for command in commands) == 1


def test_stop_server_confirms_termination_when_the_server_stops(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.server_pids = {4242}
    fake_session.listener_open = True

    session._stop_server("haibox", "haibox-gui-a")

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    stop_index = next(index for index, command in enumerate(commands) if "xpra stop" in command)
    scans = [index for index, command in enumerate(commands) if "python3" in command]
    # The ownership check runs before the stop, and the termination proof runs
    # after it.
    assert scans[0] < stop_index < scans[-1]
    assert fake_session.server_pids == set()
    assert fake_session.listener_open is False


def test_stop_server_fails_when_the_stop_command_fails_and_the_server_survives(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.server_pids = {4242}
    fake_session.listener_open = True
    fake_session.stop_returncode = 1
    fake_session.stop_stops_server = False

    with pytest.raises(session.SessionError, match="still running"):
        session._stop_server("haibox", "haibox-gui-a")


def test_stop_server_accepts_a_stop_command_timeout_when_termination_is_confirmed(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.server_pids = {4242}
    fake_session.listener_open = True
    fake_session.stop_timeout = True

    session._stop_server("haibox", "haibox-gui-a")

    assert fake_session.server_pids == set()
    assert fake_session.listener_open is False


def test_stop_server_fails_when_a_stop_command_timeout_leaves_the_server_running(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.server_pids = {4242}
    fake_session.listener_open = True
    fake_session.stop_timeout = True
    fake_session.stop_stops_server = False

    with pytest.raises(session.SessionError, match="still running"):
        session._stop_server("haibox", "haibox-gui-a")


def test_stop_server_fails_when_the_server_survives_a_successful_stop(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.server_pids = {4242}
    fake_session.listener_open = True
    fake_session.stop_returncode = 0
    fake_session.stop_stops_server = False

    with pytest.raises(session.SessionError, match="still running"):
        session._stop_server("haibox", "haibox-gui-a")


def test_stop_server_is_safe_when_no_server_exists(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.server_pids = set()
    fake_session.listener_open = False

    session._stop_server("haibox", "haibox-gui-a")

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    assert any("xpra stop" in command for command in commands)
    assert not any("xpra start" in command for command in commands)


def test_stop_server_fails_closed_when_the_state_is_ambiguous(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.scan_output = b"not-json"

    with pytest.raises(session.SessionError, match="cannot confirm"):
        session._stop_server("haibox", "haibox-gui-a")


def test_stop_server_fails_closed_when_the_container_cannot_be_inspected(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.scan_fails = True

    with pytest.raises(session.SessionError, match="cannot confirm"):
        session._stop_server("haibox", "haibox-gui-a")


def test_stop_server_refuses_to_stop_a_foreign_xpra_server(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.foreign_pids = {4343}

    with pytest.raises(session.SessionError, match="another Xpra server owns display"):
        session._stop_server("haibox", "haibox-gui-a")

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    # The ownership check runs first, so no stop request is ever sent and the
    # foreign server is never signalled.
    assert not any("xpra stop" in command for command in commands)
    assert fake_session.foreign_pids == {4343}


def test_stop_server_refuses_to_stop_the_display_that_holds_a_foreign_server(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.server_pids = {4242}
    fake_session.foreign_pids = {4343}

    with pytest.raises(session.SessionError, match="another Xpra server owns display"):
        session._stop_server("haibox", "haibox-gui-a")

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    # A stop request for the display could reach the foreign server too, so
    # neither server is signalled.
    assert not any("xpra stop" in command for command in commands)
    assert fake_session.foreign_pids == {4343}
    assert fake_session.server_pids == {4242}


def test_stop_server_fails_closed_when_the_container_state_is_uncertain(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.scan_uncertain = True

    with pytest.raises(session.SessionError, match="cannot confirm"):
        session._stop_server("haibox", "haibox-gui-a")

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    assert not any("xpra stop" in command for command in commands)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"not-json",
        b"[]",
        b'{"ours": "4242", "foreign": []}',
        b'{"ours": [], "foreign": null}',
    ],
)
def test_stop_server_fails_closed_on_unreadable_container_state(
    fake_session: FakeDocker, fast_lifecycle: None, payload: bytes
) -> None:
    fake_session.scan_output = payload

    with pytest.raises(session.SessionError, match="cannot confirm"):
        session._stop_server("haibox", "haibox-gui-a")

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    assert not any("xpra stop" in command for command in commands)


def test_cleanup_leaves_the_container_runtime_when_the_server_survives(
    session_state: Path, fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.server_pids = {4242}
    fake_session.listener_open = True
    fake_session.stop_stops_server = False

    with pytest.raises(session.SessionError, match="left in place"):
        session._cleanup_container("haibox", "haibox-gui-a", stop_server=True)

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    assert not any("rm -rf" in command for command in commands)
    assert not any("rm -f" in command for command in commands)
    assert fake_session.server_pids == {4242}


def test_stop_server_fails_closed_when_the_loopback_port_cannot_be_probed(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.probe_error = "socat: command not found"

    with pytest.raises(session.SessionError, match="cannot confirm"):
        session._stop_server("haibox", "haibox-gui-a")


def test_stop_server_fails_closed_when_the_loopback_port_stays_open(
    fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    fake_session.listener_open = True
    fake_session.listener_stays_open = True

    with pytest.raises(session.SessionError, match="still accepts connections"):
        session._stop_server("haibox", "haibox-gui-a")


def _write_cmdline(root: Path, pid: int, argv: list[str]) -> None:
    directory = root / str(pid)
    directory.mkdir(parents=True)
    (directory / "cmdline").write_bytes(b"\0".join(part.encode() for part in argv) + b"\0")


def test_server_scan_script_classifies_our_and_foreign_servers(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    root.mkdir()
    _write_cmdline(
        root,
        100,
        [
            "/usr/bin/python3",
            "-sP",
            "/usr/sbin/xpra",
            "start",
            session.DISPLAY,
            f"--socket-dirs={session.RUNTIME_DIR}",
        ],
    )
    _write_cmdline(
        root,
        200,
        [
            "/usr/bin/python3",
            "-sP",
            "/usr/sbin/xpra",
            "start",
            session.DISPLAY,
            "--socket-dirs=/tmp/somebody-else",
        ],
    )
    _write_cmdline(root, 300, ["/usr/bin/xterm", "-e", "sh"])
    _write_cmdline(root, 400, ["/usr/sbin/xpra", "stop", session.DISPLAY])
    # A server rooted at a similar but different directory is not ours.
    _write_cmdline(
        root,
        500,
        [
            "/usr/bin/python3",
            "-sP",
            "/usr/sbin/xpra",
            "start",
            session.DISPLAY,
            f"--socket-dirs={session.RUNTIME_DIR}2",
        ],
    )

    result = subprocess.run(
        [sys.executable, "-c", session._server_scan_script(), str(root)],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["ours"] == [100]
    assert payload["foreign"] == [200, 500]
    assert payload["uncertain"] is False


def test_server_scan_script_reports_uncertain_processes(tmp_path: Path) -> None:
    root = tmp_path / "proc"
    root.mkdir()
    # A cmdline that cannot be read must not be treated as "no server".
    (root / "500" / "cmdline").mkdir(parents=True)

    result = subprocess.run(
        [sys.executable, "-c", session._server_scan_script(), str(root)],
        capture_output=True,
        text=True,
        check=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])

    assert payload["ours"] == []
    assert payload["foreign"] == []
    assert payload["uncertain"] is True


def test_server_scan_script_uses_the_current_display_and_runtime() -> None:
    script = session._server_scan_script()

    assert json.dumps(session.DISPLAY) in script
    assert json.dumps(session.RUNTIME_DIR) in script


def test_prepare_refuses_to_reset_or_rotate_when_the_old_server_survives(
    session_state: Path, fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    password_path = session_state / "gui-a.password"
    security.write_password_file(password_path, "stale-password")
    fake_session.server_pids = {4242}
    fake_session.listener_open = True
    fake_session.stop_stops_server = False

    with pytest.raises(session.SessionError, match="still running"):
        session.prepare(
            "gui-a",
            state_dir=session_state,
            data_dir=None,
            config_dir=None,
            context="haibox",
        )

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    assert not any("rm -rf" in command for command in commands)
    assert not any("xpra start" in command for command in commands)
    assert not _container_passwords(fake_session)
    assert password_path.read_text(encoding="utf-8") == "stale-password"


def test_second_prepare_rotates_credentials_and_keeps_one_server(
    session_state: Path, fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    first = session.prepare(
        "gui-a",
        state_dir=session_state,
        data_dir=None,
        config_dir=None,
        context="haibox",
    )
    first_password = Path(str(first["password_file"])).read_text(encoding="utf-8")

    second = session.prepare(
        "gui-a",
        state_dir=session_state,
        data_dir=None,
        config_dir=None,
        context="haibox",
    )
    second_password = Path(str(second["password_file"])).read_text(encoding="utf-8")

    assert second_password != first_password
    assert len(_container_passwords(fake_session)) == 2
    assert len(fake_session.server_pids) == 1

    commands = [" ".join(call["args"]) for call in fake_session.calls]
    starts = [index for index, command in enumerate(commands) if "xpra start" in command]
    stops = [index for index, command in enumerate(commands) if "xpra stop" in command]
    scans = [index for index, command in enumerate(commands) if "python3" in command]
    resets = [index for index, command in enumerate(commands) if "rm -rf" in command]
    assert len(starts) == 2
    assert len(stops) == 2
    assert len(resets) == 2
    assert stops[1] < resets[1] < starts[1]
    assert scans[1] < resets[1]


def test_prepare_failure_removes_stale_host_and_container_password(
    session_state: Path, fake_session: FakeDocker
) -> None:
    password_path = session_state / "gui-a.password"
    security.write_password_file(password_path, "stale-password")
    fake_session.fail_start = True

    with pytest.raises(session.SessionError, match="start failed"):
        session.prepare(
            "gui-a",
            state_dir=session_state,
            data_dir=None,
            config_dir=None,
            context="haibox",
        )

    assert not password_path.exists()
    cleanup = [
        " ".join(call["args"])
        for call in fake_session.calls
        if "rm -f" in " ".join(call["args"])
    ]
    assert cleanup
    assert any(session.PASSWORD_FILE in command for command in cleanup)


def test_stop_removes_both_password_files_when_the_stop_command_fails(
    session_state: Path, fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    password_path = session_state / "gui-a.password"
    security.write_password_file(password_path, "session-password")
    fake_session.stop_returncode = 1

    session.stop(
        "gui-a",
        state_dir=session_state,
        data_dir=None,
        config_dir=None,
        context="haibox",
    )

    assert not password_path.exists()
    commands = [" ".join(call["args"]) for call in fake_session.calls]
    assert any("xpra stop" in command for command in commands)
    assert any(
        "rm -f" in command and session.PASSWORD_FILE in command
        for command in commands
    )


def test_stop_keeps_the_container_runtime_when_the_server_survives(
    session_state: Path, fake_session: FakeDocker, fast_lifecycle: None
) -> None:
    password_path = session_state / "gui-a.password"
    security.write_password_file(password_path, "session-password")
    fake_session.server_pids = {4242}
    fake_session.listener_open = True
    fake_session.stop_stops_server = False

    with pytest.raises(session.SessionError, match="left in place"):
        session.stop(
            "gui-a",
            state_dir=session_state,
            data_dir=None,
            config_dir=None,
            context="haibox",
        )

    # The host copy is always removed so the session cannot be re-attached,
    # but the live server keeps its container runtime and its credential.
    assert not password_path.exists()
    commands = [" ".join(call["args"]) for call in fake_session.calls]
    assert not any("rm -rf" in command for command in commands)
    assert not any(
        "rm -f" in command and session.PASSWORD_FILE in command
        for command in commands
    )
    assert fake_session.server_pids == {4242}


def test_stop_rejects_unsafe_engagement_id_before_removing_anything(
    session_state: Path, fake_session: FakeDocker
) -> None:
    outside = session_state.parent / "escape.password"
    outside.write_text("keep", encoding="utf-8")

    with pytest.raises(session.SessionError, match="engagement id"):
        session.stop(
            "../escape",
            state_dir=session_state,
            data_dir=None,
            config_dir=None,
            context="haibox",
        )

    assert outside.read_text(encoding="utf-8") == "keep"
    assert fake_session.calls == []


def test_prepare_refuses_non_private_state_directory(
    session_state: Path, fake_session: FakeDocker
) -> None:
    session_state.chmod(0o755)

    with pytest.raises(security.SecurityError, match="0700"):
        session.prepare(
            "gui-a",
            state_dir=session_state,
            data_dir=None,
            config_dir=None,
            context="haibox",
        )
    assert not (session_state / "gui-a.password").exists()
    assert fake_session.calls == []


def test_session_docker_timeout_is_reported(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("docker", 10)

    monkeypatch.setattr(session.subprocess, "run", timeout)

    with pytest.raises(session.SessionError, match="timed out"):
        session._docker("haibox", ["exec", "haibox-gui-a", "xpra", "--version"])


# --------------------------------------------------------------------- relay


def _engagement(
    *,
    network_mode: str = "isolated",
    allowed: list[str] | None = None,
    allowed_ports: list[int] | None = None,
    notes: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        runtime=SimpleNamespace(
            network_mode=network_mode,
            network_name="haibox-gui-a-net",
            container_name="haibox-gui-a",
        ),
        scope=Scope(
            allowed=allowed or [],
            allowed_ports=allowed_ports or [],
            notes=notes,
        ),
    )


def _paths(tmp_path: Path, scope: Scope) -> SimpleNamespace:
    scope_file = tmp_path / "scope.json"
    scope_file.write_text(scope_to_json(scope), encoding="utf-8")
    return SimpleNamespace(
        workspace_dir=lambda _engagement_id: tmp_path / "workspace",
        scope_file=lambda _engagement_id: scope_file,
    )


def _install_loaded_engagement(
    monkeypatch: pytest.MonkeyPatch,
    engagement: SimpleNamespace,
    paths: SimpleNamespace,
) -> None:
    monkeypatch.setattr(
        relay,
        "Paths",
        SimpleNamespace(resolve=lambda *_args, **_kwargs: paths),
    )
    monkeypatch.setattr(
        relay,
        "EngagementManager",
        lambda _paths: SimpleNamespace(load=lambda _engagement_id: engagement),
    )


def test_relay_preflight_accepts_isolated_empty_scope() -> None:
    relay._preflight_engagement(_engagement(), "gui-a")


@pytest.mark.parametrize("network_mode", ["scoped", "internal", "bridge", "none"])
def test_relay_preflight_rejects_non_isolated_network(network_mode: str) -> None:
    with pytest.raises(relay.RelayError, match="isolated"):
        relay._preflight_engagement(_engagement(network_mode=network_mode), "gui-a")


@pytest.mark.parametrize(
    "kwargs",
    [
        {"allowed": ["10.10.20.5"]},
        {"allowed_ports": [443]},
    ],
)
def test_relay_preflight_rejects_external_scope(kwargs: dict[str, object]) -> None:
    with pytest.raises(relay.RelayError, match="external targets"):
        relay._preflight_engagement(_engagement(**kwargs), "gui-a")


def _inspect_raw(
    engagement: SimpleNamespace,
    *,
    host_network: str | None = None,
    networks: list[str] | None = None,
) -> dict[str, object]:
    expected = engagement.runtime.network_name
    memberships = [expected] if networks is None else networks
    return {
        "Config": {
            "Labels": {
                "haibox.managed": "true",
                "haibox.engagement": "gui-a",
            }
        },
        "State": {"Status": "running"},
        "HostConfig": {"NetworkMode": host_network or expected},
        "NetworkSettings": {"Networks": {name: {} for name in memberships}},
    }


def _assert_inspect_not_called(monkeypatch: pytest.MonkeyPatch) -> list[bool]:
    inspected: list[bool] = []
    monkeypatch.setattr(
        relay,
        "_docker_inspect",
        lambda *_args, **_kwargs: inspected.append(True) or {},
    )
    return inspected


def test_resolve_engagement_rejects_scope_before_docker_inspect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement(allowed=["10.10.20.5"])
    _install_loaded_engagement(monkeypatch, engagement, _paths(tmp_path, engagement.scope))
    inspected = _assert_inspect_not_called(monkeypatch)

    with pytest.raises(relay.RelayError, match="external targets"):
        relay.resolve_engagement("gui-a")
    assert inspected == []


def test_resolve_engagement_rejects_metadata_scope_mismatch_before_inspect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement(notes="metadata copy")
    canonical = Scope(notes="mounted file copy")
    _install_loaded_engagement(monkeypatch, engagement, _paths(tmp_path, canonical))
    inspected = _assert_inspect_not_called(monkeypatch)

    with pytest.raises(relay.RelayError, match="scope metadata does not match"):
        relay.resolve_engagement("gui-a")
    assert inspected == []


def test_resolve_engagement_rejects_non_empty_canonical_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement()
    canonical = Scope(allowed=["10.10.20.5"])
    _install_loaded_engagement(monkeypatch, engagement, _paths(tmp_path, canonical))
    inspected = _assert_inspect_not_called(monkeypatch)

    with pytest.raises(relay.RelayError, match="scope metadata does not match"):
        relay.resolve_engagement("gui-a")
    assert inspected == []


@pytest.mark.parametrize("content", ["{not-json", ""])
def test_resolve_engagement_rejects_unreadable_scope_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, content: str
) -> None:
    engagement = _engagement()
    scope_file = tmp_path / "scope.json"
    scope_file.write_text(content, encoding="utf-8")
    paths = SimpleNamespace(
        workspace_dir=lambda _engagement_id: tmp_path / "workspace",
        scope_file=lambda _engagement_id: scope_file,
    )
    _install_loaded_engagement(monkeypatch, engagement, paths)
    inspected = _assert_inspect_not_called(monkeypatch)

    with pytest.raises(relay.RelayError, match="cannot read canonical scope file"):
        relay.resolve_engagement("gui-a")
    assert inspected == []


def test_resolve_engagement_rejects_observed_network_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement()
    _install_loaded_engagement(monkeypatch, engagement, _paths(tmp_path, engagement.scope))
    monkeypatch.setattr(
        relay,
        "_docker_inspect",
        lambda *_args, **_kwargs: _inspect_raw(engagement, host_network="bridge"),
    )

    with pytest.raises(relay.RelayError, match="network 'bridge'"):
        relay.resolve_engagement("gui-a")


def test_resolve_engagement_rejects_additional_network_membership(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement()
    _install_loaded_engagement(monkeypatch, engagement, _paths(tmp_path, engagement.scope))
    expected = engagement.runtime.network_name
    monkeypatch.setattr(
        relay,
        "_docker_inspect",
        lambda *_args, **_kwargs: _inspect_raw(
            engagement, networks=[expected, "haibox-extra-net"]
        ),
    )

    with pytest.raises(relay.RelayError, match="attached to networks"):
        relay.resolve_engagement("gui-a")


def test_resolve_engagement_rejects_missing_network_membership(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement()
    _install_loaded_engagement(monkeypatch, engagement, _paths(tmp_path, engagement.scope))
    monkeypatch.setattr(
        relay,
        "_docker_inspect",
        lambda *_args, **_kwargs: _inspect_raw(engagement, networks=[]),
    )

    with pytest.raises(relay.RelayError, match="expected only"):
        relay.resolve_engagement("gui-a")


def test_resolve_engagement_accepts_one_expected_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement()
    _install_loaded_engagement(monkeypatch, engagement, _paths(tmp_path, engagement.scope))
    monkeypatch.setattr(
        relay,
        "_docker_inspect",
        lambda *_args, **_kwargs: _inspect_raw(engagement),
    )

    container, workspace = relay.resolve_engagement("gui-a")

    assert container == "haibox-gui-a"
    assert workspace == (tmp_path / "workspace").resolve()


def test_resolve_engagement_can_resolve_for_cleanup_without_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement(network_mode="scoped", allowed=["10.10.20.5"])
    _install_loaded_engagement(monkeypatch, engagement, _paths(tmp_path, engagement.scope))
    monkeypatch.setattr(
        relay,
        "_docker_inspect",
        lambda *_args, **_kwargs: _inspect_raw(
            engagement, host_network="bridge", networks=[]
        ),
    )

    container, workspace = relay.resolve_engagement(
        "gui-a", require_gui_preflight=False
    )

    assert container == "haibox-gui-a"
    assert workspace == (tmp_path / "workspace").resolve()


def test_docker_inspect_timeout_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    def timeout(*_args: object, **_kwargs: object) -> None:
        raise subprocess.TimeoutExpired("docker", relay.INSPECT_TIMEOUT)

    monkeypatch.setattr(relay.subprocess, "run", timeout)

    with pytest.raises(relay.RelayError, match="timed out"):
        relay._docker_inspect("haibox", "haibox-gui-a")


def test_socket_path_requires_xdg_runtime_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("XDG_RUNTIME_DIR", raising=False)

    with pytest.raises(relay.RelayError, match="XDG_RUNTIME_DIR"):
        relay._socket_path("gui-a", None)


def test_socket_path_rejects_shared_parent(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)

    with pytest.raises(security.SecurityError, match="0700"):
        relay._socket_path("gui-a", str(shared / "gui-a.sock"))


def test_socket_path_accepts_private_parent(tmp_path: Path) -> None:
    private = tmp_path / "runtime"
    private.mkdir()
    private.chmod(0o700)

    assert relay._socket_path("gui-a", str(private / "gui-a.sock")) == private / "gui-a.sock"


def test_relay_refuses_existing_socket_path(tmp_path: Path) -> None:
    private = tmp_path / "runtime"
    private.mkdir()
    private.chmod(0o700)
    socket_path = private / "gui-a.sock"
    socket_path.write_text("occupied", encoding="utf-8")
    instance = relay.Relay(container="haibox-gui-a", socket_path=socket_path)

    with pytest.raises(relay.RelayError, match="already exists"):
        instance._listen()


def test_relay_pump_idle_timeout_marks_stream_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source, source_peer = socket.socketpair()
    destination, destination_peer = socket.socketpair()
    try:
        monkeypatch.setattr(relay.select, "select", lambda *_args, **_kwargs: ([], [], []))
        times = iter([0.0, relay.Relay.STREAM_IDLE_TIMEOUT + 1.0])
        monkeypatch.setattr(relay.time, "monotonic", lambda: next(times))
        done = threading.Event()
        instance = relay.Relay(
            container="haibox-gui-a", socket_path=Path("/nonexistent/gui-a.sock")
        )

        instance._pump(source, destination, [0.0], done)

        assert done.is_set()
        assert destination_peer.recv(1) == b""
    finally:
        source.close()
        source_peer.close()
        destination.close()
        destination_peer.close()


def test_relay_pump_eof_marks_stream_done() -> None:
    source, source_peer = socket.socketpair()
    destination, destination_peer = socket.socketpair()
    source_peer.close()
    try:
        done = threading.Event()
        instance = relay.Relay(
            container="haibox-gui-a", socket_path=Path("/nonexistent/gui-a.sock")
        )

        instance._pump(source, destination, [0.0], done)

        assert done.is_set()
        assert destination_peer.recv(1) == b""
    finally:
        source.close()
        destination.close()
        destination_peer.close()


class _FakeStream:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _FakeChild:
    def __init__(self) -> None:
        self.stdin = _FakeStream()
        self.stdout = _FakeStream()
        self.stderr = _FakeStream()
        self.waits: list[float | None] = []
        self.terminated = 0
        self.killed = 0

    def wait(self, timeout: float | None = None) -> int:
        self.waits.append(timeout)
        if len(self.waits) < 3:
            raise subprocess.TimeoutExpired("docker", timeout)
        return 0

    def terminate(self) -> None:
        self.terminated += 1

    def kill(self) -> None:
        self.killed += 1


def test_relay_blocked_write_times_out(monkeypatch: pytest.MonkeyPatch) -> None:
    source, source_peer = socket.socketpair()
    destination, destination_peer = socket.socketpair()
    destination.setblocking(False)
    try:
        while True:
            try:
                destination.send(b"x" * 65536)
            except BlockingIOError:
                break
        monkeypatch.setattr(relay.select, "select", lambda *_args, **_kwargs: ([], [], []))
        times = iter([0.0, 9.0, 10.0])
        monkeypatch.setattr(relay.time, "monotonic", lambda: next(times))
        instance = relay.Relay(
            container="haibox-gui-a", socket_path=Path("/nonexistent/gui-a.sock")
        )

        with pytest.raises(TimeoutError, match="write timed out"):
            instance._write_chunk(destination, b"blocked")
    finally:
        source.close()
        source_peer.close()
        destination.close()
        destination_peer.close()


def test_relay_child_cleanup_is_bounded() -> None:
    child = _FakeChild()
    instance = relay.Relay(
        container="haibox-gui-a", socket_path=Path("/nonexistent/gui-a.sock")
    )
    instance.child = child  # type: ignore[assignment]

    instance._stop_child()

    assert child.waits == [
        relay.Relay.CHILD_WAIT_TIMEOUT,
        relay.Relay.CHILD_TERMINATE_TIMEOUT,
        relay.Relay.CHILD_KILL_TIMEOUT,
    ]
    assert child.terminated == 1
    assert child.killed == 1
    assert child.stdin.closed and child.stdout.closed and child.stderr.closed
