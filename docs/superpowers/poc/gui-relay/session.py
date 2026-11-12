#!/usr/bin/env python3
"""Start and verify the disposable Xpra server for the GUI prototype.

This is prototype tooling, not production HAIBOX code. It resolves a HAIBOX
engagement, injects a per-session password over stdin, and starts Xpra inside
the engagement container with a fixed command line. Every forwarding feature is
explicitly disabled; the server listens only on container loopback and has no
published port.

Session preflight is the same as the relay: the engagement must use the
``isolated`` network profile and must not have external targets. Host password
files are created with mode 0600 in an owner-controlled 0700 directory, and
both host and container copies are removed on stop or failed prepare.

Usage:
    uv run python .../session.py prepare --engagement gui-a --state-dir ...
    uv run python .../session.py verify --engagement gui-a
    uv run python .../session.py stop --engagement gui-a --state-dir ...
"""

from __future__ import annotations

import argparse
import contextlib
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from relay import DEFAULT_CONTEXT, resolve_engagement  # noqa: E402
from security import (  # noqa: E402
    SecurityError,
    ensure_private_directory,
    remove_password_file,
    write_password_file,
)

from haibox.errors import EngagementError  # noqa: E402
from haibox.paths import validate_engagement_id  # noqa: E402

DISPLAY = ":100"
PORT = 14500
RUNTIME_DIR = "/tmp/xpra-runtime"
PASSWORD_FILE = f"{RUNTIME_DIR}/xpra-auth"
LOG_FILE = "/tmp/xpra.log"

DOCKER_TIMEOUT = 60.0
PROBE_TIMEOUT = 10.0
STOP_TIMEOUT = 30.0
STOP_VERIFY_TIMEOUT = 20.0
STOP_POLL_INTERVAL = 0.5
CLEANUP_TIMEOUT = 30.0
PREPARE_WAIT = 30.0
PASSWORD_BYTES = 24

# Deny-by-default. Changing this list is a security decision, not a convenience.
DISABLED_FLAGS = (
    "--clipboard=no",
    "--file-transfer=no",
    "--printing=no",
    "--speaker=disabled",
    "--microphone=disabled",
    "--webcam=no",
    "--notifications=no",
    "--system-tray=no",
    "--dbus=no",
    "--dbus-control=no",
    "--start-new-commands=no",
    "--sharing=no",
    "--html=no",
    "--mdns=no",
)

SERVER_ARGS = (
    "xpra",
    "start",
    DISPLAY,
    "--daemon=no",
    f"--socket-dirs={RUNTIME_DIR}",
    f"--bind-tcp=127.0.0.1:{PORT},auth=file:filename={PASSWORD_FILE}",
    "--start=xterm",
    *DISABLED_FLAGS,
)


class SessionError(SecurityError):
    """A safe, operator-facing session failure."""


# Read-only process scan used to prove that the previous Xpra server is gone.
# It matches the argv of an Xpra *server* for this display, so it never
# matches the scanning process itself and never matches an unrelated tool.
# A server is "ours" when its argv references this engagement's runtime
# directory; any other Xpra server on the same display is reported as foreign
# and is never stopped by this prototype.
_SERVER_SCAN = r"""
import json
import os

display = ":100"
runtime = "/tmp/xpra-runtime"
ours = []
foreign = []
me = os.getpid()
for entry in os.listdir("/proc"):
    if not entry.isdigit():
        continue
    pid = int(entry)
    if pid == me:
        continue
    try:
        with open("/proc/" + str(pid) + "/cmdline", "rb") as handle:
            raw = handle.read()
    except OSError:
        continue
    argv = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    for index, part in enumerate(argv):
        if part != "xpra" and not part.endswith("/xpra"):
            continue
        if index + 2 >= len(argv):
            break
        if argv[index + 1] != "start" or argv[index + 2] != display:
            continue
        if any(runtime in element for element in argv):
            ours.append(pid)
        else:
            foreign.append(pid)
        break
print(json.dumps({"ours": sorted(ours), "foreign": sorted(foreign)}))
"""


def _docker(
    context: str,
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: float = DOCKER_TIMEOUT,
) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(
            ["docker", "--context", context, *args],
            input=input_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise SessionError(
            f"docker {' '.join(args[:3])} timed out after {timeout:g}s"
        ) from exc
    except OSError as exc:
        raise SessionError(f"cannot run docker: {exc}") from exc


def _must(
    context: str,
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: float = DOCKER_TIMEOUT,
) -> bytes:
    result = _docker(context, args, input_bytes=input_bytes, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise SessionError(f"docker {' '.join(args[:3])} failed: {detail[:2000]}")
    return result.stdout


def _password_path(state_dir: Path, engagement: str) -> Path:
    """Build the host password path only from a validated engagement ID."""

    try:
        valid = validate_engagement_id(engagement)
    except EngagementError as exc:
        raise SessionError(str(exc)) from exc
    return Path(state_dir).expanduser().absolute() / f"{valid}.password"


def _server_state(context: str, container: str) -> tuple[str, dict[str, object]]:
    """Report the Xpra server state for this display inside the container.

    Returns ``stopped``, ``running`` (this engagement's server), ``foreign``
    (another Xpra server on the same display), or ``ambiguous`` when the state
    cannot be determined. An ambiguous state is never treated as stopped.
    """

    try:
        result = _docker(
            context,
            ["exec", container, "python3", "-c", _SERVER_SCAN],
            timeout=PROBE_TIMEOUT,
        )
    except SessionError:
        return "ambiguous", {"reason": "the container could not be inspected"}
    if result.returncode != 0:
        return "ambiguous", {"reason": "the container could not be inspected"}
    lines = [
        line for line in result.stdout.decode("utf-8", "replace").splitlines() if line.strip()
    ]
    if not lines:
        return "ambiguous", {"reason": "the container reported no server state"}
    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return "ambiguous", {"reason": "the container reported unreadable server state"}
    if not isinstance(payload, dict):
        return "ambiguous", {"reason": "the container reported unreadable server state"}
    ours = payload.get("ours")
    foreign = payload.get("foreign")
    if not isinstance(ours, list) or not isinstance(foreign, list):
        return "ambiguous", {"reason": "the container reported unreadable server state"}
    if ours:
        return "running", {"pids": ours}
    if foreign:
        return "foreign", {"pids": foreign}
    return "stopped", {}


def _listener_state(context: str, container: str) -> str:
    """Report whether the container loopback port still accepts connections."""

    try:
        result = _docker(
            context,
            [
                "exec",
                container,
                "sh",
                "-c",
                f"timeout 2 socat -u /dev/null TCP:127.0.0.1:{PORT}",
            ],
            timeout=PROBE_TIMEOUT,
        )
    except SessionError:
        return "ambiguous"
    if result.returncode == 0:
        return "open"
    detail = (result.stderr or b"").decode("utf-8", "replace")
    if "Connection refused" in detail:
        return "closed"
    return "ambiguous"


def _verify_server_stopped(
    context: str,
    container: str,
    *,
    timeout: float | None = None,
    poll: float | None = None,
) -> None:
    """Fail closed unless the previous Xpra server is confirmed terminated.

    The check is bounded by ``timeout``. A live server, a foreign server, or
    an unreadable state all raise ``SessionError`` instead of returning.
    """

    limit = STOP_VERIFY_TIMEOUT if timeout is None else timeout
    interval = STOP_POLL_INTERVAL if poll is None else poll
    deadline = time.monotonic() + limit
    while True:
        state, details = _server_state(context, container)
        if state == "ambiguous":
            raise SessionError(
                "cannot confirm that the previous Xpra server stopped: "
                f"{details.get('reason', 'unknown reason')}"
            )
        if state == "foreign":
            raise SessionError(
                f"another Xpra server owns display {DISPLAY} "
                f"(pids {details.get('pids', [])}); refusing to stop a session "
                "that this engagement does not own"
            )
        if state == "running":
            if time.monotonic() >= deadline:
                raise SessionError(
                    f"the previous Xpra server on display {DISPLAY} is still "
                    f"running (pids {details.get('pids', [])})"
                )
            time.sleep(interval)
            continue
        listener = _listener_state(context, container)
        if listener == "ambiguous":
            raise SessionError(
                "cannot confirm that the previous Xpra server released the "
                f"container loopback port {PORT}"
            )
        if listener == "open":
            if time.monotonic() >= deadline:
                raise SessionError(
                    f"the container loopback port {PORT} still accepts "
                    "connections"
                )
            time.sleep(interval)
            continue
        return


def _stop_server(
    context: str,
    container: str,
    *,
    verify: bool = True,
    timeout: float | None = None,
    poll: float | None = None,
) -> None:
    """Stop the previous Xpra server and prove that it terminated.

    The ``xpra stop`` exit code is never trusted on its own: the server is
    confirmed gone by inspecting the container for a live Xpra server process
    on this display and for a listener on the container loopback port. The stop
    command only targets the display of this engagement's container, and a
    foreign Xpra server is never stopped.
    """

    outcome = "xpra stop reported success"
    try:
        result = _docker(
            context,
            [
                "exec",
                container,
                "env",
                f"XDG_RUNTIME_DIR={RUNTIME_DIR}",
                "HOME=/tmp",
                "xpra",
                "stop",
                DISPLAY,
            ],
            timeout=STOP_TIMEOUT,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
            outcome = f"xpra stop exited {result.returncode}: {detail[:200]}"
    except SessionError as exc:
        outcome = str(exc)
    if not verify:
        return
    try:
        _verify_server_stopped(context, container, timeout=timeout, poll=poll)
    except SessionError as exc:
        raise SessionError(f"{exc} ({outcome})") from exc


def _reset_container_runtime(context: str, container: str) -> None:
    """Recreate the container runtime directory.

    The caller must have confirmed that no Xpra server is running for this
    display; deleting the runtime of a live server would break its session.
    """

    _must(
        context,
        [
            "exec",
            container,
            "sh",
            "-c",
            f"rm -rf {RUNTIME_DIR}; install -d -m 0700 {RUNTIME_DIR}; "
            f"rm -f {PASSWORD_FILE}",
        ],
        timeout=DOCKER_TIMEOUT,
    )


def _write_container_password(context: str, container: str, password: str) -> None:
    """Write the container password without argv exposure or symlink clobbering."""

    _must(
        context,
        [
            "exec",
            "-i",
            container,
            "sh",
            "-c",
            f"umask 077; set -C; cat > {PASSWORD_FILE}",
        ],
        input_bytes=password.encode("utf-8"),
        timeout=DOCKER_TIMEOUT,
    )
    _must(
        context,
        [
            "exec",
            container,
            "sh",
            "-c",
            f'test -s {PASSWORD_FILE} && test "$(stat -c %a {PASSWORD_FILE})" = 600',
        ],
        timeout=DOCKER_TIMEOUT,
    )


def _cleanup_container(
    context: str, container: str, *, stop_server: bool
) -> None:
    """Remove the server, runtime directory, and password.

    The server is only removed when its termination can be confirmed. When it
    cannot, the credential is still revoked, but the rest of the runtime state
    is left alone so a live server is not left with deleted state, and the
    failure is reported to the caller.
    """

    stopped = True
    try:
        if stop_server:
            _stop_server(context, container)
        else:
            _verify_server_stopped(context, container)
    except SessionError:
        stopped = False
    if stopped:
        with contextlib.suppress(SecurityError):
            _docker(
                context,
                [
                    "exec",
                    container,
                    "sh",
                    "-c",
                    f"rm -f {PASSWORD_FILE}; rm -rf {RUNTIME_DIR}",
                ],
                timeout=CLEANUP_TIMEOUT,
            )
        return
    with contextlib.suppress(SecurityError):
        _docker(
            context,
            ["exec", container, "sh", "-c", f"rm -f {PASSWORD_FILE}"],
            timeout=CLEANUP_TIMEOUT,
        )
    raise SessionError(
        "the Xpra server could not be confirmed stopped; the credential was "
        "removed but the container runtime was left in place"
    )


def _wait_for_listener(context: str, container: str) -> None:
    deadline = time.monotonic() + PREPARE_WAIT
    while time.monotonic() < deadline:
        probe = _docker(
            context,
            [
                "exec",
                container,
                "sh",
                "-c",
                f"timeout 2 socat -u /dev/null TCP:127.0.0.1:{PORT}",
            ],
            timeout=PROBE_TIMEOUT,
        )
        if probe.returncode == 0:
            return
        time.sleep(0.5)
    log = _docker(
        context,
        ["exec", container, "tail", "-40", LOG_FILE],
        timeout=PROBE_TIMEOUT,
    )
    raise SessionError(
        "Xpra did not listen on container loopback: "
        + log.stdout.decode("utf-8", "replace")[:4000]
    )


def prepare(
    engagement: str,
    *,
    state_dir: Path,
    data_dir: str | None,
    config_dir: str | None,
    context: str,
) -> dict[str, object]:
    container, _workspace = resolve_engagement(
        engagement, data_dir=data_dir, config_dir=config_dir, context=context
    )
    password_path = _password_path(state_dir, engagement)

    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    ensure_private_directory(state_dir, create=False)

    version = _must(context, ["exec", container, "xpra", "--version"]).decode().strip()
    if "6.5.4" not in version:
        raise SessionError(f"unexpected Xpra version: {version}")

    # Fail closed unless the previous server for this display is gone. This
    # happens before any credential is written or replaced and before the
    # container runtime is touched, so a live server keeps its session and its
    # credential and no second server can be started beside it.
    _stop_server(context, container)

    # Safe now that no Xpra server can be using the old runtime or password.
    _reset_container_runtime(context, container)

    password = secrets.token_urlsafe(PASSWORD_BYTES)
    write_password_file(password_path, password)

    server_started = False
    try:
        _write_container_password(context, container, password)

        script = "exec " + " ".join(SERVER_ARGS) + f" > {LOG_FILE} 2>&1"
        _must(
            context,
            [
                "exec",
                "-d",
                container,
                "env",
                f"XDG_RUNTIME_DIR={RUNTIME_DIR}",
                "HOME=/tmp",
                "sh",
                "-c",
                script,
            ],
            timeout=DOCKER_TIMEOUT,
        )
        server_started = True
        _wait_for_listener(context, container)
    except BaseException as exc:
        try:
            _cleanup_container(context, container, stop_server=server_started)
        except SessionError as cleanup_error:
            exc.add_note(f"cleanup warning: {cleanup_error}")
        finally:
            with contextlib.suppress(OSError, SecurityError):
                remove_password_file(password_path)
        raise

    return {
        "engagement": engagement,
        "container": container,
        "display": DISPLAY,
        "bind": f"127.0.0.1:{PORT}",
        "password_file": str(password_path),
        "xpra_version": version,
        "disabled": list(DISABLED_FLAGS),
    }


def _info(container: str, context: str) -> dict[str, str]:
    output = _must(
        context,
        [
            "exec",
            container,
            "env",
            f"XDG_RUNTIME_DIR={RUNTIME_DIR}",
            "HOME=/tmp",
            "xpra",
            "info",
            DISPLAY,
        ],
    ).decode("utf-8", "replace")
    info: dict[str, str] = {}
    for line in output.splitlines():
        if "=" in line and not line.startswith(" "):
            key, _, value = line.partition("=")
            info[key] = value
    return info


def _process_argv(container: str, context: str) -> str:
    """Return the full Xpra server argv from /proc, not the truncated info view."""

    return _must(
        context,
        [
            "exec",
            container,
            "sh",
            "-c",
            "p=$(pgrep -f '/usr/sbin/xpra start :100' | head -1); "
            "tr '\\0' '\\n' < /proc/$p/cmdline",
        ],
    ).decode("utf-8", "replace")


def verify(
    engagement: str,
    *,
    data_dir: str | None,
    config_dir: str | None,
    context: str,
) -> dict[str, object]:
    container, _workspace = resolve_engagement(
        engagement, data_dir=data_dir, config_dir=config_dir, context=context
    )
    info = _info(container, context)
    failures: list[str] = []

    command = info.get("command.0.pidfile", "")
    if "xterm" not in command:
        failures.append("the fixed xterm start command is not running")
    if info.get("sharing", "").lower() != "false":
        failures.append("session sharing is not disabled")
    server_subsystems = info.get("subsystems", "")
    for forbidden in ("clipboard", "file-transfer", "printing", "webcam"):
        if forbidden in server_subsystems:
            failures.append(f"server subsystem {forbidden} is enabled")

    client_subsystems = ""
    for key, value in info.items():
        if key.endswith(".subsystems") and key.startswith("client."):
            client_subsystems += value
    for forbidden in (
        "Clipboard",
        "FileTransfer",
        "Printing",
        "Audio",
        "Webcam",
        "Notifications",
        "Tray",
    ):
        if forbidden in client_subsystems:
            failures.append(f"client subsystem {forbidden} is enabled")

    argv = _process_argv(container, context)
    for flag in DISABLED_FLAGS:
        if flag not in argv:
            failures.append(f"missing deny-by-default flag {flag}")

    if failures:
        raise SessionError("; ".join(failures))
    return {
        "engagement": engagement,
        "container": container,
        "sharing": info.get("sharing"),
        "client_subsystems": client_subsystems,
        "disabled_flags": len(DISABLED_FLAGS),
    }


def stop(
    engagement: str,
    *,
    state_dir: Path,
    data_dir: str | None,
    config_dir: str | None,
    context: str,
) -> None:
    """Stop Xpra and remove both password files, even when stop fails."""

    password_path = _password_path(state_dir, engagement)
    try:
        container, _workspace = resolve_engagement(
            engagement,
            data_dir=data_dir,
            config_dir=config_dir,
            context=context,
            require_gui_preflight=False,
        )
        _cleanup_container(context, container, stop_server=True)
    finally:
        with contextlib.suppress(OSError, SecurityError):
            remove_password_file(password_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", "stop"))
    parser.add_argument("--engagement", required=True)
    parser.add_argument("--state-dir", default="/tmp/opencode/gui-readiness")
    parser.add_argument("--data-dir")
    parser.add_argument("--config-dir")
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    args = parser.parse_args(argv)

    try:
        if args.action == "prepare":
            result = prepare(
                args.engagement,
                state_dir=Path(args.state_dir),
                data_dir=args.data_dir,
                config_dir=args.config_dir,
                context=args.context,
            )
        elif args.action == "verify":
            result = verify(
                args.engagement,
                data_dir=args.data_dir,
                config_dir=args.config_dir,
                context=args.context,
            )
        else:
            stop(
                args.engagement,
                state_dir=Path(args.state_dir),
                data_dir=args.data_dir,
                config_dir=args.config_dir,
                context=args.context,
            )
            result = {"stopped": args.engagement}
    except SecurityError as exc:
        print(f"session: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
