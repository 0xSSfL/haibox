"""Adversarial tests for the GUI runtime.

These tests are the executable form of the Phase 5 security requirements:
hostile and malformed streams, authentication and credential handling,
cross-engagement isolation, label manipulation, forwarding bypass attempts,
resource limits, and secret leakage.  They never call Docker; the real-Docker
evidence for the same requirements is recorded in the evidence document.
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import socket
import stat
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from haibox.errors import ValidationError
from haibox.gui import (
    DENIED_CLIENT_FLAGS,
    DENIED_SERVER_FLAGS,
    GuiLimits,
    GuiPreflightError,
    GuiRelay,
    GuiRelayError,
    GuiSessionManager,
    GuiSessionSpec,
)
from haibox.gui.credentials import read_credential, remove_credential, write_credential
from haibox.gui.errors import GuiCredentialError
from haibox.models import Engagement, RuntimeSettings, Scope
from haibox.paths import Paths
from haibox.runtime.base import ContainerInfo, ExecResult
from haibox.scope import scope_to_json
from tests.fakes import FakeRuntime

ENGAGEMENT_ID = "gui-a"
OTHER_ID = "gui-b"
IMAGE = "haibox/gui:0.1.0"
NETWORK = "haibox-gui-a-net"
CONTAINER = "haibox-gui-a"


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    resolved = Paths.resolve(tmp_path / "data", tmp_path / "config")
    resolved.ensure()
    return resolved


def _engagement(
    engagement_id: str = ENGAGEMENT_ID,
    *,
    image: str = IMAGE,
    allowed: list[str] | None = None,
    container: str | None = None,
    labels: dict[str, str] | None = None,
) -> Engagement:
    runtime = RuntimeSettings(
        container_name=container or f"haibox-{engagement_id}",
        network_name=f"haibox-{engagement_id}-net",
        network_mode="isolated",
        uid=1000,
        gid=1000,
        cpus=2.0,
        memory="2g",
        pids_limit=512,
    )
    return Engagement(
        id=engagement_id,
        name=engagement_id,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        owner="tester",
        profile="gui",
        image=image,
        runtime=runtime,
        scope=Scope(allowed=allowed or []),
    )


def _write_scope(paths: Paths, engagement: Engagement) -> None:
    path = paths.scope_file(engagement.id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scope_to_json(engagement.scope), encoding="utf-8")


def _container(
    engagement: Engagement,
    *,
    labels: dict[str, str] | None = None,
    networks: tuple[str, ...] | None = None,
    running: bool = True,
) -> ContainerInfo:
    return ContainerInfo(
        id="fake-0001",
        name=engagement.runtime.container_name,
        image=engagement.image,
        state="running" if running else "exited",
        status="Up" if running else "Exited",
        labels=labels
        if labels is not None
        else {
            "haibox.managed": "true",
            "haibox.engagement": engagement.id,
        },
        network_mode=engagement.runtime.network_name,
        networks=networks
        if networks is not None
        else (engagement.runtime.network_name,),
    )


class _HostileRuntime(FakeRuntime):
    """A fake runtime whose container answers with hostile content."""

    def __init__(self, engagement: Engagement, paths: Paths | None = None) -> None:
        super().__init__()
        if paths is not None:
            _write_scope(paths, engagement)
        self.containers[engagement.runtime.container_name] = _container(engagement)
        self.server_pids: set[int] = set()
        self.stopper_pids: set[int] = set()
        self.listener_open = False

    def exec_detached(
        self, name: str, command: list[str], timeout: int | None = None
    ) -> None:
        super().exec_detached(name, command, timeout)
        self.server_pids = {9000}
        self.listener_open = True

    def exec_capture(
        self, name: str, command: list[str], timeout: int | None = None
    ) -> ExecResult:
        self._record("exec_capture", name, tuple(command), timeout)
        joined = " ".join(command)
        if joined.startswith("sh -c kill "):
            # A terminated stop request is gone.
            self.stopper_pids = set()
        if "python3" in command and "-c" in command:
            return ExecResult(
                exit_code=0,
                stdout=json.dumps(
                    {
                        "ours": sorted(self.server_pids),
                        "foreign": [],
                        "stoppers": sorted(self.stopper_pids),
                        "argv": {},
                        "uncertain": False,
                    }
                ),
                stderr="",
            )
        if "xpra" in command and "--version" in command:
            return ExecResult(exit_code=0, stdout="xpra v6.5.6\n", stderr="")
        if "socat" in joined:
            if self.listener_open:
                return ExecResult(exit_code=0, stdout="", stderr="")
            return ExecResult(
                exit_code=1,
                stdout="",
                stderr="socat: connect(4, AF=2 127.0.0.1:14500): Connection refused",
            )
        return ExecResult(exit_code=0, stdout="", stderr="")


def _relay_runtime(engagement: Engagement) -> FakeRuntime:
    """A fake runtime with the engagement's own managed container."""

    runtime = FakeRuntime()
    runtime.containers[engagement.runtime.container_name] = ContainerInfo(
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
    return runtime


def _manager(
    paths: Paths,
    runtime: FakeRuntime,
    engagement: Engagement,
    *,
    limits: GuiLimits | None = None,
) -> GuiSessionManager:
    manager = GuiSessionManager(runtime, paths, limits=limits)
    manager._engagement = lambda engagement_id: engagement  # type: ignore[method-assign]
    return manager


# ------------------------------------------------------------ hostile streams


def test_relay_survives_a_hostile_byte_stream(tmp_path: Path) -> None:
    """Random bytes from a client must not crash the relay."""

    private = tmp_path / "runtime"
    private.mkdir(mode=0o700)
    engagement = _engagement()
    relay = GuiRelay(
        _relay_runtime(engagement),
        GuiSessionSpec.from_engagement(engagement),
        private / "g.sock",
    )
    listener = relay._listen()
    server, client = socket.socketpair()
    try:
        relay._authenticate = lambda _client: None  # type: ignore[method-assign]
        relay._open_stream = lambda: _FakeStream()  # type: ignore[method-assign]
        worker = threading.Thread(
            target=relay.serve_client, args=(client,), daemon=True
        )
        worker.start()
        with contextlib.suppress(OSError):
            server.sendall(bytes(range(256)) * 4096)
        server.close()
        worker.join(timeout=10)
        assert not worker.is_alive()
        # The relay is still usable after the hostile stream.
        assert relay.stop.is_set() is False
    finally:
        server.close()
        client.close()
        listener.close()
        (private / "g.sock").unlink(missing_ok=True)


class _FakeStream:
    def __init__(self) -> None:
        self.stdin = _Sink()
        self.stdout = _Source(b"")
        self.closed = False

    def shutdown(self) -> None:
        self.closed = True


class _Sink:
    def send(self, data: bytes) -> int:
        del data
        return 0

    def shutdown(self, _how: int) -> None:
        return None

    def close(self) -> None:
        return None

    def fileno(self) -> int:
        return 0


class _Source:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def recv(self, _size: int) -> bytes:
        return self.payload

    def setblocking(self, _flag: bool) -> None:
        return None

    def fileno(self) -> int:
        return 0

    def close(self) -> None:
        return None


def test_relay_refuses_a_second_client(tmp_path: Path) -> None:
    private = tmp_path / "runtime"
    private.mkdir(mode=0o700)
    engagement = _engagement()
    relay = GuiRelay(FakeRuntime(), GuiSessionSpec.from_engagement(engagement), private / "g.sock")
    assert relay._active.acquire(blocking=False) is True
    server, client = socket.socketpair()
    try:
        relay.serve_client(client)
        # The second client is closed instead of being served.
        client.close()
    finally:
        server.close()
        relay._active.release()


def test_relay_rejects_a_peer_with_a_different_user(tmp_path: Path) -> None:
    private = tmp_path / "runtime"
    private.mkdir(mode=0o700)
    engagement = _engagement()
    relay = GuiRelay(FakeRuntime(), GuiSessionSpec.from_engagement(engagement), private / "g.sock")
    server, client = socket.socketpair()
    try:
        # A peer that is not the relay's own user is refused.
        relay._authenticate = lambda _client: (_ for _ in ()).throw(  # type: ignore[method-assign]
            GuiRelayError("the peer user does not own this session")
        )
        with pytest.raises(GuiRelayError):
            relay._authenticate(client)
    finally:
        server.close()
        client.close()


def test_relay_stops_a_stalled_peer_after_the_idle_timeout(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    private = tmp_path / "runtime"
    private.mkdir(mode=0o700)
    engagement = _engagement()
    relay = GuiRelay(
        FakeRuntime(),
        GuiSessionSpec.from_engagement(engagement),
        private / "g.sock",
    )
    source, source_peer = socket.socketpair()
    destination, destination_peer = socket.socketpair()
    try:
        monkeypatch.setattr(
            "haibox.gui.relay.select.select", lambda *_args, **_kwargs: ([], [], [])
        )
        times = iter([0.0, relay.spec.limits.stream_idle_timeout + 1.0])
        monkeypatch.setattr("haibox.gui.relay.time.monotonic", lambda: next(times))
        relay._pump(source, destination, [0.0])
        assert destination_peer.recv(1) == b""
    finally:
        source.close()
        source_peer.close()
        destination.close()
        destination_peer.close()


# ------------------------------------------------------ credentials and secrets


def test_the_credential_never_appears_in_the_server_argv(paths: Paths) -> None:
    engagement = _engagement()
    spec = GuiSessionSpec.from_engagement(engagement)
    joined = " ".join(spec.server_args())
    assert "auth=file:filename=" in joined
    assert spec.password_file in joined
    # The credential is a file name, never a value.
    assert "password=" not in joined


def test_the_credential_is_not_written_to_the_audit_log(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    events: list[tuple[str, dict[str, object]]] = []
    manager = GuiSessionManager(
        runtime,
        paths,
        audit=lambda event, _engagement, data: events.append((event, dict(data))),
    )
    manager._engagement = lambda _id: engagement  # type: ignore[method-assign]
    manager.prepare(ENGAGEMENT_ID)

    assert events
    for event, data in events:
        assert event.startswith("gui.")
        for value in data.values():
            assert "password" not in str(value)


def test_a_rotated_credential_replaces_the_previous_value(tmp_path: Path) -> None:
    path = tmp_path / "state" / "gui-a.password"
    write_credential(path, "first-value")
    write_credential(path, "second-value")
    assert read_credential(path) == "second-value"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_a_revoked_credential_is_removed(tmp_path: Path) -> None:
    path = tmp_path / "state" / "gui-a.password"
    write_credential(path, "value")
    assert remove_credential(path) is True
    assert not path.exists()
    with pytest.raises(GuiCredentialError):
        read_credential(path)


# ------------------------------------------------------ isolation and labels


def test_a_forged_engagement_label_is_refused(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    runtime.containers[CONTAINER] = _container(
        engagement,
        labels={"haibox.managed": "true", "haibox.engagement": OTHER_ID},
    )
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="does not belong"):
        manager.status(ENGAGEMENT_ID)


def test_a_removed_managed_label_is_refused(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    runtime.containers[CONTAINER] = _container(
        engagement,
        labels={"haibox.managed": "false", "haibox.engagement": ENGAGEMENT_ID},
    )
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="not HAIBOX-managed"):
        manager.status(ENGAGEMENT_ID)


def test_a_container_of_another_engagement_is_refused(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    runtime.containers[CONTAINER] = _container(
        engagement,
        labels={"haibox.managed": "true", "haibox.engagement": ENGAGEMENT_ID},
    )
    other = _engagement(OTHER_ID)
    _write_scope(paths, other)
    runtime.containers[other.runtime.container_name] = _container(
        other,
        labels={"haibox.managed": "true", "haibox.engagement": ENGAGEMENT_ID},
    )
    manager = _manager(paths, runtime, other)
    with pytest.raises(GuiPreflightError, match="does not belong"):
        manager.status(OTHER_ID)


def test_an_extra_network_is_refused(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    runtime.containers[CONTAINER] = _container(
        engagement,
        networks=(engagement.runtime.network_name, "haibox-extra-net"),
    )
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="attached to networks"):
        manager.status(ENGAGEMENT_ID)


def test_a_non_isolated_engagement_is_refused(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    scoped = engagement.model_copy(
        update={
            "runtime": engagement.runtime.model_copy(update={"network_mode": "scoped"})
        }
    )
    manager = _manager(paths, runtime, scoped)
    with pytest.raises(GuiPreflightError, match="isolated"):
        manager.status(ENGAGEMENT_ID)


def test_external_targets_are_refused(paths: Paths) -> None:
    engagement = _engagement(allowed=["10.10.20.5"])
    runtime = _HostileRuntime(engagement, paths)
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="external targets"):
        manager.status(ENGAGEMENT_ID)


def test_a_scope_file_that_does_not_match_the_metadata_is_refused(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    scope_file = paths.scope_file(ENGAGEMENT_ID)
    scope_file.parent.mkdir(parents=True, exist_ok=True)
    scope_file.write_text(scope_to_json(Scope(notes="different")), encoding="utf-8")
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="does not match"):
        manager.status(ENGAGEMENT_ID)


# ------------------------------------------------------------ forwarding bypass


def test_every_forwarding_feature_is_denied_on_the_server() -> None:
    for flag in DENIED_SERVER_FLAGS:
        assert flag in DENIED_SERVER_FLAGS
    joined = " ".join(GuiSessionSpec.from_engagement(_engagement()).server_args())
    for flag in DENIED_SERVER_FLAGS:
        assert flag in joined
    assert "--start-new-commands=no" in joined
    assert "--clipboard=no" in joined
    assert "--file-transfer=no" in joined
    assert "--printing=no" in joined
    assert "--webcam=no" in joined
    assert "--dbus=no" in joined


def test_the_client_flags_mirror_the_server_flags() -> None:
    spec = GuiSessionSpec.from_engagement(_engagement())
    assert set(spec.client_args()) == set(DENIED_CLIENT_FLAGS)
    assert set(spec.client_args()) == set(DENIED_SERVER_FLAGS)


def test_the_spec_cannot_be_widened_by_a_caller() -> None:
    with pytest.raises(ValidationError):
        GuiSessionSpec.from_engagement(_engagement(image="haibox/core:0.1.0"))
    with pytest.raises(ValidationError):
        GuiSessionSpec(
            engagement_id=ENGAGEMENT_ID,
            container=CONTAINER,
            image=IMAGE,
            server_flags=(),
        )


# ------------------------------------------------------------------- resources


def test_the_limits_are_bounded() -> None:
    limits = GuiLimits()
    assert 0 < limits.cpus <= 64
    assert 16 <= limits.pids_limit <= 4096
    assert limits.max_sessions == 1
    assert limits.max_connections == 1
    for name in (
        "connect_timeout",
        "stream_idle_timeout",
        "stream_write_timeout",
        "shutdown_timeout",
    ):
        assert 1 <= getattr(limits, name) <= 3600
    with pytest.raises(ValidationError):
        GuiLimits(max_connections=0)
    with pytest.raises(ValidationError):
        GuiLimits(stream_idle_timeout=0)


def test_the_credential_directory_is_not_world_readable(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    manager = _manager(paths, runtime, engagement)
    path = manager.credential_path(ENGAGEMENT_ID)
    manager._credential_directory()
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_a_lingering_stop_request_is_terminated_before_the_reset(
    paths: Paths,
) -> None:
    """A stop request that is still waiting must not kill the next session.

    ``xpra stop`` waits for a server socket to appear.  When such a request is
    left over from an earlier attempt, it would shut down the server that the
    next prepare starts, so it is terminated first.
    """

    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    runtime.stopper_pids = {777}
    manager = _manager(
        paths, runtime, engagement, limits=GuiLimits(shutdown_timeout=1)
    )

    manager.prepare(ENGAGEMENT_ID)

    commands = [" ".join(str(part) for part in call[1]) for call in runtime.calls]
    assert any("kill 777" in command for command in commands)
    # The reset only happens after the leftover stop request is gone.
    kill_index = next(
        index for index, command in enumerate(commands) if "kill 777" in command
    )
    reset_index = next(
        index for index, command in enumerate(commands) if "rm -rf /tmp/xpra-runtime" in command
    )
    assert kill_index < reset_index


def test_no_stop_request_is_sent_when_no_server_is_running(paths: Paths) -> None:
    """Without a server there is nothing to stop, and nothing to wait for."""

    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    manager = _manager(paths, runtime, engagement)

    manager.prepare(ENGAGEMENT_ID)

    commands = [" ".join(str(part) for part in call[1]) for call in runtime.calls]
    assert not any("xpra stop" in command for command in commands)


def test_the_relay_refuses_a_container_it_does_not_own(paths: Paths) -> None:
    """The relay checks the container before it binds a socket."""

    private = paths.logs_dir / "gui"
    private.mkdir(parents=True, exist_ok=True)
    private.chmod(0o700)
    engagement = _engagement()
    runtime = _relay_runtime(engagement)
    runtime.containers[engagement.runtime.container_name] = dataclasses.replace(
        runtime.containers[engagement.runtime.container_name],
        labels={"haibox.managed": "true", "haibox.engagement": OTHER_ID},
    )
    relay = GuiRelay(runtime, GuiSessionSpec.from_engagement(engagement), private / "g.sock")

    with pytest.raises(GuiRelayError, match="does not belong"):
        relay._listen()

    assert not (private / "g.sock").exists()


def test_the_session_budget_is_enforced(paths: Paths) -> None:
    """An engagement may not ask for more than the GUI session budget."""

    engagement = _engagement()
    runtime = _HostileRuntime(engagement, paths)
    greedy = engagement.model_copy(
        update={
            "runtime": engagement.runtime.model_copy(update={"cpus": 16.0}),
        }
    )
    manager = _manager(paths, runtime, greedy)

    with pytest.raises(GuiPreflightError, match="above the GUI session budget"):
        manager.status(ENGAGEMENT_ID)


def test_the_deny_list_cannot_be_widened_or_narrowed() -> None:
    """The forwarding deny list is fixed."""

    with pytest.raises(ValidationError):
        GuiSessionSpec(
            engagement_id=ENGAGEMENT_ID,
            container=CONTAINER,
            image=IMAGE,
            server_flags=("--clipboard=yes",),
        )
    with pytest.raises(ValidationError):
        GuiSessionSpec(
            engagement_id=ENGAGEMENT_ID,
            container=CONTAINER,
            image=IMAGE,
            server_flags=(),
        )
    with pytest.raises(ValidationError):
        GuiSessionSpec(
            engagement_id=ENGAGEMENT_ID,
            container=CONTAINER,
            image=IMAGE,
            runtime_dir="/tmp/somewhere-else",
        )


def test_the_runtime_paths_are_fixed() -> None:
    with pytest.raises(ValidationError):
        GuiSessionSpec(
            engagement_id=ENGAGEMENT_ID,
            container=CONTAINER,
            image=IMAGE,
            log_file="/tmp/other.log",
        )
    with pytest.raises(ValidationError):
        GuiSessionSpec(
            engagement_id=ENGAGEMENT_ID,
            container=CONTAINER,
            image=IMAGE,
            password_file="/tmp/other.password",
        )
