"""Unit tests for the production GUI runtime.

The tests use the in-memory fake runtime: they never call Docker.  They cover
the eligibility rules, the credential handling, the verified session
replacement, and the relay's local peer authentication.
"""

from __future__ import annotations

import os
import socket
import stat
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from haibox.errors import ValidationError
from haibox.gui import (
    GuiError,
    GuiLimits,
    GuiPreflightError,
    GuiRelay,
    GuiRelayError,
    GuiSessionManager,
    GuiSessionSpec,
)
from haibox.gui.credentials import (
    ensure_private_directory,
    generate_password,
    read_credential,
    remove_credential,
    write_credential,
)
from haibox.models import Engagement, RuntimeSettings, Scope
from haibox.paths import Paths
from haibox.runtime.base import ContainerInfo, ExecResult
from haibox.scope import scope_to_json
from tests.fakes import FakeRuntime

ENGAGEMENT_ID = "gui-a"
IMAGE = "haibox/gui:0.1.0"
NETWORK = "haibox-gui-a-net"
CONTAINER = "haibox-gui-a"


# --------------------------------------------------------------------- fixtures


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    resolved = Paths.resolve(tmp_path / "data", tmp_path / "config")
    resolved.ensure()
    return resolved


def _engagement(
    *,
    image: str = IMAGE,
    network_mode: str = "isolated",
    allowed: list[str] | None = None,
    allowed_ports: list[int] | None = None,
) -> Engagement:
    runtime = RuntimeSettings(
        container_name=CONTAINER,
        network_name=NETWORK,
        network_mode=network_mode,
        uid=1000,
        gid=1000,
        cpus=2.0,
        memory="2g",
        pids_limit=512,
    )
    return Engagement(
        id=ENGAGEMENT_ID,
        name=ENGAGEMENT_ID,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
        updated_at=datetime(2026, 1, 1, tzinfo=UTC),
        owner="tester",
        profile="core",
        image=image,
        runtime=runtime,
        scope=Scope(allowed=allowed or [], allowed_ports=allowed_ports or []),
    )


def _write_scope(paths: Paths, scope: Scope) -> None:
    path = paths.scope_file(ENGAGEMENT_ID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(scope_to_json(scope), encoding="utf-8")


def _runtime_with_container(
    paths: Paths,
    engagement: Engagement,
    *,
    networks: tuple[str, ...] = (NETWORK,),
    network_mode: str = NETWORK,
    managed: bool = True,
    running: bool = True,
) -> FakeRuntime:
    runtime = FakeRuntime()
    runtime.containers[CONTAINER] = ContainerInfo(
        id="fake-0001",
        name=CONTAINER,
        image=engagement.image,
        state="running" if running else "exited",
        status="Up" if running else "Exited",
        labels={
            "haibox.managed": "true" if managed else "false",
            "haibox.engagement": ENGAGEMENT_ID,
        },
        network_mode=network_mode,
        networks=networks,
    )
    _write_scope(paths, engagement.scope)
    return runtime


# ------------------------------------------------------------------ spec


def test_spec_requires_the_approved_image() -> None:
    with pytest.raises(ValidationError, match="approved image"):
        GuiSessionSpec.from_engagement(_engagement(image="haibox/core:0.1.0"))


def test_spec_binds_the_container_to_the_engagement() -> None:
    spec = GuiSessionSpec.from_engagement(_engagement())
    assert spec.container == CONTAINER
    assert spec.display == ":100"
    assert spec.bind_tcp == "127.0.0.1:14500"
    assert "--clipboard=no" in spec.server_args()
    assert "--sharing=no" in spec.server_args()
    assert "--start-new-commands=no" in spec.server_args()


def test_limits_reject_unbounded_values() -> None:
    with pytest.raises(ValidationError):
        GuiLimits(cpus=0)
    with pytest.raises(ValidationError):
        GuiLimits(memory="lots")
    with pytest.raises(ValidationError):
        GuiLimits(pids_limit=4)
    with pytest.raises(ValidationError):
        GuiLimits(max_sessions=99)


# ------------------------------------------------------------- credentials


def test_credential_file_is_private(tmp_path: Path) -> None:
    path = tmp_path / "state" / "gui-a.password"
    write_credential(path, "secret-value")
    assert read_credential(path) == "secret-value"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_credential_rotation_replaces_the_content(tmp_path: Path) -> None:
    path = tmp_path / "state" / "gui-a.password"
    write_credential(path, "first")
    write_credential(path, "second")
    assert read_credential(path) == "second"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_credential_refuses_a_symlink(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir(mode=0o700)
    target = state / "target"
    target.write_text("original", encoding="utf-8")
    link = state / "gui-a.password"
    link.symlink_to(target)
    with pytest.raises(Exception, match="regular file"):
        write_credential(link, "new")
    assert target.read_text(encoding="utf-8") == "original"


def test_credential_removal_is_idempotent(tmp_path: Path) -> None:
    path = tmp_path / "state" / "gui-a.password"
    assert remove_credential(path) is False
    write_credential(path, "secret")
    assert remove_credential(path) is True
    assert not path.exists()


def test_generated_passwords_are_random() -> None:
    assert generate_password() != generate_password()
    assert len(generate_password(32)) >= 32


def test_private_directory_requires_mode_0700(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)
    with pytest.raises(Exception, match="0700"):
        ensure_private_directory(shared)


# -------------------------------------------------------------- preflight


def test_preflight_rejects_a_non_isolated_engagement(paths: Paths) -> None:
    engagement = _engagement(network_mode="scoped")
    runtime = _runtime_with_container(paths, engagement)
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="isolated"):
        manager.status(ENGAGEMENT_ID)


def test_preflight_rejects_external_targets(paths: Paths) -> None:
    engagement = _engagement(allowed=["10.10.20.5"])
    runtime = _runtime_with_container(paths, engagement)
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="external targets"):
        manager.status(ENGAGEMENT_ID)


def test_preflight_rejects_a_scope_file_mismatch(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _runtime_with_container(paths, engagement)
    _write_scope(paths, Scope(notes="different"))
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="does not match"):
        manager.status(ENGAGEMENT_ID)


def test_preflight_rejects_an_extra_network(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _runtime_with_container(
        paths, engagement, networks=(NETWORK, "haibox-extra-net")
    )
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="attached to networks"):
        manager.status(ENGAGEMENT_ID)


def test_preflight_rejects_a_missing_network(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _runtime_with_container(paths, engagement, networks=())
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="attached to networks"):
        manager.status(ENGAGEMENT_ID)


def test_preflight_rejects_an_unmanaged_container(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _runtime_with_container(paths, engagement, managed=False)
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="not HAIBOX-managed"):
        manager.prepare(ENGAGEMENT_ID)


def test_preflight_rejects_a_stopped_container(paths: Paths) -> None:
    engagement = _engagement()
    runtime = _runtime_with_container(paths, engagement, running=False)
    manager = _manager(paths, runtime, engagement)
    with pytest.raises(GuiPreflightError, match="not running"):
        manager.prepare(ENGAGEMENT_ID)


# ---------------------------------------------------------------- session


class GuiFakeRuntime(FakeRuntime):
    """A fake runtime that answers container commands by their shape."""

    def __init__(self) -> None:
        super().__init__()
        self.server_pids: set[int] = set()
        self.foreign_pids: set[int] = set()
        self.listener_open = False
        self.argv: dict[str, list[str]] = {}
        self.scan_calls = 0

    def _scan_payload(self) -> str:
        import json

        self.scan_calls += 1
        return json.dumps(
            {
                "ours": sorted(self.server_pids),
                "foreign": sorted(self.foreign_pids),
                "argv": self.argv,
                "uncertain": False,
            }
        )

    def exec_detached(
        self, name: str, command: list[str], timeout: int | None = None
    ) -> None:
        super().exec_detached(name, command, timeout)
        self.server_pids = {9000}
        self.listener_open = True
        self.argv = {
            "9000": ["xpra", "start", ":100", "--socket-dirs=/tmp/xpra-runtime"]
        }

    def exec_capture(
        self, name: str, command: list[str], timeout: int | None = None
    ) -> ExecResult:
        joined = " ".join(command)
        if "python3" in command and "-c" in command:
            return ExecResult(exit_code=0, stdout=self._scan_payload(), stderr="")
        if "socat" in joined:
            if self.listener_open:
                return ExecResult(exit_code=0, stdout="", stderr="")
            return ExecResult(
                exit_code=1,
                stdout="",
                stderr="socat: connect(4, AF=2 127.0.0.1:14500): Connection refused",
            )
        return ExecResult(exit_code=0, stdout="", stderr="")


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


def test_prepare_rotates_the_credential_and_writes_both_copies(
    paths: Paths,
) -> None:
    engagement = _engagement()
    runtime = GuiFakeRuntime()
    _write_scope(paths, engagement.scope)
    runtime.containers[CONTAINER] = ContainerInfo(
        id="fake-0001",
        name=CONTAINER,
        image=engagement.image,
        state="running",
        status="Up",
        labels={
            "haibox.managed": "true",
            "haibox.engagement": ENGAGEMENT_ID,
        },
        network_mode=NETWORK,
        networks=(NETWORK,),
    )
    manager = _manager(paths, runtime, engagement)

    status = manager.prepare(ENGAGEMENT_ID)

    assert status.running is True
    assert status.servers == (9000,)
    assert runtime.detached_commands
    assert runtime.written_inputs
    credential = manager.credential_path(ENGAGEMENT_ID)
    assert credential.exists()
    assert stat.S_IMODE(credential.stat().st_mode) == 0o600


def test_prepare_refuses_when_a_foreign_server_owns_the_display(paths: Paths) -> None:
    engagement = _engagement()
    runtime = GuiFakeRuntime()
    _write_scope(paths, engagement.scope)
    runtime.foreign_pids = {999}
    runtime.containers[CONTAINER] = ContainerInfo(
        id="fake-0001",
        name=CONTAINER,
        image=engagement.image,
        state="running",
        status="Up",
        labels={
            "haibox.managed": "true",
            "haibox.engagement": ENGAGEMENT_ID,
        },
        network_mode=NETWORK,
        networks=(NETWORK,),
    )
    manager = _manager(paths, runtime, engagement)

    with pytest.raises(GuiError, match="another Xpra server"):
        manager.prepare(ENGAGEMENT_ID)

    assert not runtime.detached_commands
    assert not runtime.written_inputs
    assert not manager.credential_path(ENGAGEMENT_ID).exists()


def test_prepare_refuses_when_the_previous_server_survives(paths: Paths) -> None:
    engagement = _engagement()
    runtime = GuiFakeRuntime()
    _write_scope(paths, engagement.scope)
    runtime.server_pids = {4242}
    runtime.containers[CONTAINER] = ContainerInfo(
        id="fake-0001",
        name=CONTAINER,
        image=engagement.image,
        state="running",
        status="Up",
        labels={
            "haibox.managed": "true",
            "haibox.engagement": ENGAGEMENT_ID,
        },
        network_mode=NETWORK,
        networks=(NETWORK,),
    )
    manager = _manager(
        paths, runtime, engagement, limits=GuiLimits(shutdown_timeout=1)
    )

    with pytest.raises(GuiError, match="still running"):
        manager.prepare(ENGAGEMENT_ID)

    assert not runtime.detached_commands
    assert not runtime.written_inputs


def test_verify_requires_the_denied_flags(paths: Paths) -> None:
    engagement = _engagement()
    runtime = GuiFakeRuntime()
    _write_scope(paths, engagement.scope)
    runtime.server_pids = {7}
    runtime.argv = {"7": ["xpra", "start", ":100", "--clipboard=no"]}
    runtime.containers[CONTAINER] = ContainerInfo(
        id="fake-0001",
        name=CONTAINER,
        image=engagement.image,
        state="running",
        status="Up",
        labels={
            "haibox.managed": "true",
            "haibox.engagement": ENGAGEMENT_ID,
        },
        network_mode=NETWORK,
        networks=(NETWORK,),
    )
    manager = _manager(paths, runtime, engagement)

    with pytest.raises(GuiError, match="deny flag"):
        manager.verify(ENGAGEMENT_ID)


def test_verify_accepts_a_server_with_every_denied_flag(paths: Paths) -> None:
    engagement = _engagement()
    runtime = GuiFakeRuntime()
    _write_scope(paths, engagement.scope)
    spec = GuiSessionSpec.from_engagement(engagement)
    runtime.server_pids = {7}
    runtime.argv = {"7": list(spec.server_args())}
    runtime.containers[CONTAINER] = ContainerInfo(
        id="fake-0001",
        name=CONTAINER,
        image=engagement.image,
        state="running",
        status="Up",
        labels={
            "haibox.managed": "true",
            "haibox.engagement": ENGAGEMENT_ID,
        },
        network_mode=NETWORK,
        networks=(NETWORK,),
    )
    manager = _manager(paths, runtime, engagement)

    status = manager.verify(ENGAGEMENT_ID)

    assert status.running is True
    assert status.servers == (7,)


def _empty_scan() -> dict[str, object]:
    return {"ours": [], "foreign": [], "argv": {}, "uncertain": False}


# ------------------------------------------------------------------ relay


def test_relay_refuses_a_socket_in_a_shared_directory(tmp_path: Path) -> None:
    shared = tmp_path / "shared"
    shared.mkdir()
    shared.chmod(0o755)
    engagement = _engagement()
    runtime = FakeRuntime()
    spec = GuiSessionSpec.from_engagement(engagement)
    relay = GuiRelay(runtime, spec, shared / "gui-a.sock")
    with pytest.raises(GuiRelayError, match="0700"):
        relay._listen()


def test_relay_socket_is_private(tmp_path: Path) -> None:
    private = tmp_path / "runtime"
    private.mkdir(mode=0o700)
    engagement = _engagement()
    runtime = FakeRuntime()
    spec = GuiSessionSpec.from_engagement(engagement)
    socket_path = private / "gui-a.sock"
    relay = GuiRelay(runtime, spec, socket_path)
    listener = relay._listen()
    try:
        assert stat.S_IMODE(socket_path.stat().st_mode) == 0o600
        assert stat.S_IMODE(private.stat().st_mode) == 0o700
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)


def test_relay_rejects_a_foreign_peer(paths: Paths) -> None:
    engagement = _engagement()
    runtime = FakeRuntime()
    spec = GuiSessionSpec.from_engagement(engagement)
    relay = GuiRelay(runtime, spec, paths.logs_dir / "gui-a.sock")
    server, client = socket.socketpair()
    try:
        assert relay.peer_uid(client) == os.getuid()
        server.close()
        server, client = socket.socketpair()
        # A peer that is not the relay's own user is refused.
        relay._authenticate = lambda _client: (_ for _ in ()).throw(
            GuiRelayError("the peer user does not own this session")
        )
        with pytest.raises(GuiRelayError):
            relay._authenticate(client)
    finally:
        server.close()
        client.close()


def test_relay_serves_at_most_one_client(tmp_path: Path) -> None:
    private = tmp_path / "runtime"
    private.mkdir(mode=0o700)
    engagement = _engagement()
    runtime = FakeRuntime()
    spec = GuiSessionSpec.from_engagement(engagement)
    relay = GuiRelay(runtime, spec, private / "gui-a.sock")
    assert relay._active.acquire(blocking=False) is True
    server, client = socket.socketpair()
    try:
        relay.serve_client(client)
    finally:
        server.close()
        client.close()
        relay._active.release()


def test_relay_pump_stops_on_an_idle_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    engagement = _engagement()
    runtime = FakeRuntime()
    spec = GuiSessionSpec.from_engagement(engagement)
    relay = GuiRelay(runtime, spec, Path("/nonexistent/gui-a.sock"))
    source, source_peer = socket.socketpair()
    destination, destination_peer = socket.socketpair()
    try:
        monkeypatch.setattr(
            "haibox.gui.relay.select.select", lambda *_args, **_kwargs: ([], [], [])
        )
        times = iter([0.0, relay.spec.limits.stream_idle_timeout + 1.0])
        monkeypatch.setattr(
            "haibox.gui.relay.time.monotonic", lambda: next(times)
        )
        relay._pump(source, destination, [0.0])
        assert destination_peer.recv(1) == b""
    finally:
        source.close()
        source_peer.close()
        destination.close()
        destination_peer.close()


def test_relay_bridge_command_is_fixed(paths: Paths) -> None:
    engagement = _engagement()
    runtime = FakeRuntime()
    spec = GuiSessionSpec.from_engagement(engagement)
    relay = GuiRelay(runtime, spec, paths.logs_dir / "gui-a.sock")
    assert relay._bridge_command() == ["socat", "-", "TCP:127.0.0.1:14500"]


def test_relay_stop_releases_the_socket(tmp_path: Path) -> None:
    private = tmp_path / "runtime"
    private.mkdir(mode=0o700)
    engagement = _engagement()
    runtime = FakeRuntime()
    spec = GuiSessionSpec.from_engagement(engagement)
    socket_path = private / "gui-a.sock"
    relay = GuiRelay(runtime, spec, socket_path)
    thread = threading.Thread(target=relay.serve_forever, daemon=True)
    thread.start()
    for _ in range(40):
        if socket_path.exists():
            break
        threading.Event().wait(0.05)
    relay.request_stop()
    thread.join(timeout=5)
    assert not socket_path.exists()
