"""Regression tests for the disposable GUI prototype hardening.

These tests never call Docker. They exercise the prototype's fail-closed
preflight, private file handling, password rotation and cleanup, socket path
rules, and bounded relay teardown with fakes.
"""

from __future__ import annotations

import socket
import stat
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

GUI_RELAY_DIR = Path(__file__).resolve().parents[2] / "docs/superpowers/poc/gui-relay"
sys.path.insert(0, str(GUI_RELAY_DIR))

import relay  # noqa: E402
import security  # noqa: E402
import session  # noqa: E402


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


class FakeDocker:
    """Minimal docker CLI fake for the session helper."""

    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []
        self.fail_start = False
        self.stop_returncode = 0
        self.probe_returncode = 0

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
        if "xpra start" in joined:
            if self.fail_start:
                return subprocess.CompletedProcess(args, 1, b"", b"start failed")
            return subprocess.CompletedProcess(args, 0, b"", b"")
        if "xpra" in args and "stop" in args:
            return subprocess.CompletedProcess(args, self.stop_returncode, b"", b"")
        if "socat" in joined:
            return subprocess.CompletedProcess(args, self.probe_returncode, b"", b"")
        return subprocess.CompletedProcess(args, 0, b"", b"")


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


def test_stop_removes_host_and_container_password_even_if_xpra_stop_fails(
    session_state: Path, fake_session: FakeDocker
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
) -> SimpleNamespace:
    return SimpleNamespace(
        runtime=SimpleNamespace(
            network_mode=network_mode,
            network_name="haibox-gui-a-net",
            container_name="haibox-gui-a",
        ),
        scope=SimpleNamespace(
            allowed=allowed or [],
            allowed_ports=allowed_ports or [],
        ),
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


def test_resolve_engagement_rejects_scope_before_docker_inspect(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement(allowed=["10.10.20.5"])
    paths = SimpleNamespace(workspace_dir=lambda _engagement_id: tmp_path / "workspace")
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
    inspected = False

    def inspect(*_args: object, **_kwargs: object) -> dict[str, object]:
        nonlocal inspected
        inspected = True
        return {}

    monkeypatch.setattr(relay, "_docker_inspect", inspect)

    with pytest.raises(relay.RelayError, match="external targets"):
        relay.resolve_engagement("gui-a")
    assert inspected is False


def test_resolve_engagement_rejects_observed_network_mismatch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement()
    paths = SimpleNamespace(workspace_dir=lambda _engagement_id: tmp_path / "workspace")
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
    monkeypatch.setattr(
        relay,
        "_docker_inspect",
        lambda *_args, **_kwargs: {
            "Config": {
                "Labels": {
                    "haibox.managed": "true",
                    "haibox.engagement": "gui-a",
                }
            },
            "State": {"Status": "running"},
            "HostConfig": {"NetworkMode": "bridge"},
        },
    )

    with pytest.raises(relay.RelayError, match="network 'bridge'"):
        relay.resolve_engagement("gui-a")


def test_resolve_engagement_can_resolve_for_cleanup_without_preflight(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    engagement = _engagement(network_mode="scoped", allowed=["10.10.20.5"])
    paths = SimpleNamespace(workspace_dir=lambda _engagement_id: tmp_path / "workspace")
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
    monkeypatch.setattr(
        relay,
        "_docker_inspect",
        lambda *_args, **_kwargs: {
            "Config": {
                "Labels": {
                    "haibox.managed": "true",
                    "haibox.engagement": "gui-a",
                }
            },
            "State": {"Status": "running"},
            "HostConfig": {"NetworkMode": "bridge"},
        },
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
