"""Engagement-bound GUI session lifecycle.

The lifecycle is deliberately strict:

* a session may only replace another session after the previous Xpra server is
  confirmed terminated, and an Xpra server on the display that does not belong
  to this engagement is reported and never signalled;
* the credential is rotated on every start, lives in a mode-0600 file on both
  sides, and is removed when the session ends;
* every container command is fixed by the specification; nothing from the
  caller reaches the container runtime.
"""

from __future__ import annotations

import contextlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from haibox.engagement import EngagementManager
from haibox.gui.credentials import (
    ensure_private_directory,
    generate_password,
    remove_credential,
    write_credential,
)
from haibox.gui.errors import GuiError
from haibox.gui.preflight import verify_gui_preflight
from haibox.gui.spec import (
    DENIED_SERVER_FLAGS,
    SUPPORTED_XPRA_VERSIONS,
    GuiLimits,
    GuiSessionSpec,
)
from haibox.models import Engagement
from haibox.paths import Paths, validate_engagement_id
from haibox.runtime.base import ContainerRuntime

AuditHook = Callable[[str, str | None, dict[str, object]], None]

#: Read-only scan of the container process table.  It is rendered from the
#: session specification so the pattern can never drift from the server that
#: was started, and it returns the server command line so the caller can
#: assert the deny-by-default flags.
_SERVER_SCAN = r"""
import json
import os
import re
import sys

root = sys.argv[1] if len(sys.argv) > 1 else "/proc"
display = %s
runtime = %s
runtime_pattern = re.compile(r"(?:^|[=/])" + re.escape(runtime) + r"(?:/|$)")
ours = []
foreign = []
stoppers = []
argv_by_pid = {}
uncertain = False
me = os.getpid()
for entry in os.listdir(root):
    if not entry.isdigit():
        continue
    pid = int(entry)
    if pid == me:
        continue
    try:
        with open(os.path.join(root, entry, "cmdline"), "rb") as handle:
            raw = handle.read()
    except FileNotFoundError:
        continue
    except OSError:
        uncertain = True
        continue
    argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    for index, part in enumerate(argv):
        if part != "xpra" and not part.endswith("/xpra"):
            continue
        if index + 2 >= len(argv):
            break
        if argv[index + 1] == "stop" and argv[index + 2] == display:
            # A stop request that is still waiting for a server to appear.
            # It is only ours when it references this engagement's runtime
            # directory; a stop request for another session is never touched.
            if any(runtime_pattern.search(element) for element in argv):
                stoppers.append(pid)
            else:
                foreign.append(pid)
            break
        if argv[index + 1] != "start" or argv[index + 2] != display:
            continue
        if any(runtime_pattern.search(element) for element in argv):
            ours.append(pid)
            argv_by_pid[str(pid)] = argv
        else:
            foreign.append(pid)
        break
print(json.dumps({
    "ours": sorted(ours),
    "foreign": sorted(foreign),
    "stoppers": sorted(stoppers),
    "argv": argv_by_pid,
    "uncertain": uncertain,
}))
"""


@dataclass(frozen=True)
class ServerReport:
    """What the container reports about the Xpra server on the display."""

    ours: tuple[int, ...]
    foreign: tuple[int, ...]
    stoppers: tuple[int, ...] = ()
    argv: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class GuiSessionStatus:
    """The observable state of a GUI session."""

    engagement: str
    container: str
    display: str
    bind: str
    credential_file: str
    running: bool
    servers: tuple[int, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "engagement": self.engagement,
            "container": self.container,
            "display": self.display,
            "bind": self.bind,
            "credential_file": self.credential_file,
            "running": self.running,
            "servers": list(self.servers),
        }


class GuiSessionManager:
    """Start, verify, and stop engagement-bound GUI sessions."""

    def __init__(
        self,
        runtime: ContainerRuntime,
        paths: Paths,
        *,
        audit: AuditHook | None = None,
        limits: GuiLimits | None = None,
    ) -> None:
        self.runtime = runtime
        self.paths = paths
        self.audit = audit
        self.limits = limits or GuiLimits()

    def _spec(self, engagement: Engagement) -> GuiSessionSpec:
        """Return the session specification for an engagement."""

        return replace(GuiSessionSpec.from_engagement(engagement), limits=self.limits)

    # ------------------------------------------------------------------ paths
    def credential_path(self, engagement_id: str) -> Path:
        """Return the host credential path for an engagement."""

        try:
            valid = validate_engagement_id(engagement_id)
        except Exception as exc:  # noqa: BLE001 - surfaced as a GUI error
            raise GuiError(str(exc)) from exc
        return self.paths.logs_dir / "gui" / f"{valid}.password"

    def _credential_directory(self) -> Path:
        return ensure_private_directory(self.paths.logs_dir / "gui")

    # ---------------------------------------------------------------- helpers
    def _engagement(self, engagement_id: str) -> Engagement:
        try:
            return EngagementManager(self.paths).load(engagement_id)
        except Exception as exc:  # noqa: BLE001 - surfaced as a GUI error
            raise GuiError(f"unknown engagement {engagement_id!r}: {exc}") from exc

    def _record(self, event: str, engagement: str, data: dict[str, object]) -> None:
        if self.audit is not None:
            self.audit(event, engagement, data)

    def _scan_script(self, spec: GuiSessionSpec) -> str:
        return _SERVER_SCAN % (json.dumps(spec.display), json.dumps(spec.runtime_dir))

    def _exec(self, spec: GuiSessionSpec, command: list[str], timeout: int) -> str:
        result = self.runtime.exec_capture(spec.container, command, timeout=timeout)
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()[:400]
            raise GuiError(f"container command failed: {detail}")
        return result.stdout

    def _server_state(self, spec: GuiSessionSpec) -> ServerReport:
        """Return the container's report about the Xpra server on the display."""

        result = self.runtime.exec_capture(
            spec.container,
            ["python3", "-c", self._scan_script(spec), "/proc"],
            timeout=30,
        )
        if not result.ok:
            raise GuiError("cannot inspect the container for the Xpra server")
        lines = [line for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise GuiError("the container reported no Xpra server state")
        try:
            payload = json.loads(lines[-1])
        except json.JSONDecodeError as exc:
            raise GuiError("the container reported unreadable Xpra server state") from exc
        if not isinstance(payload, dict):
            raise GuiError("the container reported unreadable Xpra server state")
        ours = payload.get("ours")
        foreign = payload.get("foreign")
        stoppers = payload.get("stoppers")
        argv = payload.get("argv")
        if (
            not isinstance(ours, list)
            or not isinstance(foreign, list)
            or not isinstance(stoppers, list)
            or not isinstance(argv, dict)
        ):
            raise GuiError("the container reported unreadable Xpra server state")
        if payload.get("uncertain"):
            raise GuiError("a container process could not be inspected")
        return ServerReport(
            ours=tuple(int(pid) for pid in ours),
            foreign=tuple(int(pid) for pid in foreign),
            stoppers=tuple(int(pid) for pid in stoppers),
            argv={str(key): [str(part) for part in value] for key, value in argv.items()},
        )

    def _listener_open(self, spec: GuiSessionSpec) -> bool:
        result = self.runtime.exec_capture(
            spec.container,
            ["sh", "-c", f"timeout 2 socat -u /dev/null TCP:{spec.bind_tcp}"],
            timeout=15,
        )
        if result.ok:
            return True
        detail = (result.stderr or result.stdout).strip()
        if "Connection refused" in detail:
            return False
        raise GuiError(
            f"cannot confirm that the container loopback port {spec.port} is free"
        )

    def _terminate_stoppers(self, spec: GuiSessionSpec, pids: tuple[int, ...]) -> None:
        """Terminate our own lingering stop requests.

        ``xpra stop`` waits for a server socket to appear.  A stop request that
        is still waiting when a new server starts would shut the new server
        down, so a leftover stop request of ours is terminated before the
        runtime is reset.
        """

        if not pids:
            return
        self.runtime.exec_capture(
            spec.container,
            ["sh", "-c", "kill " + " ".join(str(pid) for pid in pids)],
            timeout=30,
        )

    def _stop_previous_server(self, spec: GuiSessionSpec) -> None:
        """Stop the previous server and prove that it terminated.

        The ownership check runs first, so an Xpra server on this display that
        does not belong to this engagement is reported and never signalled.
        The stop request is bounded inside the container as well, because
        ``xpra stop`` waits for a server socket to appear and would otherwise
        outlive the request and shut down the next session.
        """

        state = self._server_state(spec)
        if state.foreign:
            raise GuiError(
                f"another Xpra server owns display {spec.display} (pids {state.foreign}); "
                "refusing to stop a session that this engagement does not own"
            )
        if state.ours:
            self.runtime.exec_capture(
                spec.container,
                [
                    "env",
                    f"XDG_RUNTIME_DIR={spec.runtime_dir}",
                    "HOME=/tmp",
                    "sh",
                    "-c",
                    f"timeout {spec.limits.shutdown_timeout} xpra stop {spec.display}",
                ],
                timeout=spec.limits.shutdown_timeout + 5,
            )
        deadline = time.monotonic() + spec.limits.shutdown_timeout
        while True:
            state = self._server_state(spec)
            if state.foreign:
                raise GuiError(
                    f"another Xpra server owns display {spec.display} (pids {state.foreign}); "
                    "refusing to continue with a display this engagement does not own"
                )
            if state.stoppers:
                # Our own stop request is still waiting for a server to appear.
                self._terminate_stoppers(spec, state.stoppers)
                if time.monotonic() >= deadline:
                    raise GuiError(
                        "a stop request for this engagement is still waiting for "
                        f"a server to appear (pids {state.stoppers})"
                    )
                time.sleep(0.5)
                continue
            if not state.ours:
                break
            if time.monotonic() >= deadline:
                raise GuiError(
                    f"the previous Xpra server on display {spec.display} is still "
                    f"running (pids {state.ours})"
                )
            time.sleep(0.5)
        if self._listener_open(spec):
            raise GuiError(
                f"the container loopback port {spec.port} still accepts connections"
            )

    # ----------------------------------------------------------------- actions
    def prepare(self, engagement_id: str) -> GuiSessionStatus:
        """Start a GUI session for an engagement."""

        engagement = self._engagement(engagement_id)
        spec = self._spec(engagement)
        verify_gui_preflight(
            engagement, self.paths, self.runtime, spec, limits=self.limits
        )
        credential_path = self.credential_path(engagement_id)
        password = generate_password()
        started = False
        try:
            self._check_server_version(spec)
            self._stop_previous_server(spec)
            self._reset_runtime(spec)
            self._credential_directory()
            write_credential(credential_path, password)
            self._write_container_credential(spec, password)
            self._start_server(spec)
            started = True
            self._wait_for_listener(spec)
        except BaseException:
            if started:
                with contextlib.suppress(GuiError):
                    self._stop_previous_server(spec)
            with contextlib.suppress(Exception):
                remove_credential(credential_path)
            raise
        self._record(
            "gui.session_started",
            engagement_id,
            {"container": spec.container, "display": spec.display},
        )
        return self.status(engagement_id)

    def verify(self, engagement_id: str) -> GuiSessionStatus:
        """Check that a GUI session is running with the expected restrictions."""

        engagement = self._engagement(engagement_id)
        spec = self._spec(engagement)
        verify_gui_preflight(
            engagement, self.paths, self.runtime, spec, limits=self.limits
        )
        state = self._server_state(spec)
        servers = state.ours
        if not servers:
            raise GuiError(f"no Xpra server is running for engagement {engagement_id!r}")
        for pid in servers:
            argv = state.argv.get(str(pid))
            if not isinstance(argv, list):
                raise GuiError(f"cannot read the Xpra server command line for pid {pid}")
            joined = " ".join(str(part) for part in argv)
            for flag in DENIED_SERVER_FLAGS:
                if flag not in joined:
                    raise GuiError(f"the Xpra server is missing the deny flag {flag}")
        return GuiSessionStatus(
            engagement=engagement_id,
            container=spec.container,
            display=spec.display,
            bind=spec.bind_tcp,
            credential_file=str(self.credential_path(engagement_id)),
            running=True,
            servers=servers,
        )

    def stop(self, engagement_id: str) -> None:
        """Stop the GUI session and remove both credential copies."""

        engagement = self._engagement(engagement_id)
        spec = self._spec(engagement)
        credential_path = self.credential_path(engagement_id)
        try:
            self._stop_previous_server(spec)
        finally:
            # The host copy always goes: a session that cannot be stopped must
            # not stay attachable from this host.
            with contextlib.suppress(Exception):
                remove_credential(credential_path)
        self._clear_runtime(spec)
        self._record(
            "gui.session_stopped",
            engagement_id,
            {"container": spec.container, "display": spec.display},
        )

    def status(self, engagement_id: str) -> GuiSessionStatus:
        """Return the observable state of a GUI session.

        The eligibility rules still apply: an engagement that is not eligible
        for a GUI session is reported as an error rather than as an idle
        session.
        """

        engagement = self._engagement(engagement_id)
        spec = self._spec(engagement)
        verify_gui_preflight(
            engagement,
            self.paths,
            self.runtime,
            spec,
            require_running=False,
            limits=self.limits,
        )
        servers: tuple[int, ...] = ()
        info = self.runtime.inspect_container_optional(spec.container)
        if info is not None and info.running:
            servers = self._server_state(spec).ours
        return GuiSessionStatus(
            engagement=engagement_id,
            container=spec.container,
            display=spec.display,
            bind=spec.bind_tcp,
            credential_file=str(self.credential_path(engagement_id)),
            running=bool(servers),
            servers=servers,
        )

    # -------------------------------------------------------------- container
    def _check_server_version(self, spec: GuiSessionSpec) -> str:
        """Refuse a container whose Xpra version is not qualified."""

        output = self._exec(spec, ["xpra", "--version"], timeout=30).strip()
        version = output.split()[-1].lstrip("v") if output else ""
        if not version.startswith(SUPPORTED_XPRA_VERSIONS):
            raise GuiError(
                f"the container runs Xpra {version or 'of an unknown version'}; "
                f"supported versions are {', '.join(SUPPORTED_XPRA_VERSIONS)}"
            )
        return version

    def _reset_runtime(self, spec: GuiSessionSpec) -> None:
        self._exec(
            spec,
            [
                "sh",
                "-c",
                f"rm -rf {spec.runtime_dir}; install -d -m 0700 {spec.runtime_dir}; "
                f"rm -f {spec.password_file}",
            ],
            timeout=60,
        )

    def _clear_runtime(self, spec: GuiSessionSpec) -> None:
        self._exec(
            spec,
            [
                "sh",
                "-c",
                f"rm -f {spec.password_file}; rm -rf {spec.runtime_dir}",
            ],
            timeout=60,
        )

    def _write_container_credential(self, spec: GuiSessionSpec, password: str) -> None:
        result = self.runtime.exec_with_input(
            spec.container,
            ["sh", "-c", f"umask 077; set -C; cat > {spec.password_file}"],
            password.encode("utf-8"),
            timeout=60,
        )
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()[:400]
            raise GuiError(f"cannot write the container credential: {detail}")
        self._exec(
            spec,
            [
                "sh",
                "-c",
                f'test -s {spec.password_file} && test "$(stat -c %a {spec.password_file})" = 600',
            ],
            timeout=30,
        )

    def _start_server(self, spec: GuiSessionSpec) -> None:
        command = "exec " + " ".join(spec.server_args()) + f" > {spec.log_file} 2>&1"
        self.runtime.exec_detached(
            spec.container,
            [
                "env",
                f"XDG_RUNTIME_DIR={spec.runtime_dir}",
                "HOME=/tmp",
                "sh",
                "-c",
                command,
            ],
            timeout=60,
        )

    def _wait_for_listener(self, spec: GuiSessionSpec) -> None:
        deadline = time.monotonic() + spec.limits.connect_timeout
        while time.monotonic() < deadline:
            result = self.runtime.exec_capture(
                spec.container,
                ["sh", "-c", f"timeout 2 socat -u /dev/null TCP:{spec.bind_tcp}"],
                timeout=15,
            )
            if result.ok:
                return
            time.sleep(0.5)
        raise GuiError(
            f"the Xpra server did not listen on {spec.bind_tcp} inside the container"
        )
