#!/usr/bin/env python3
"""Start and verify the disposable Xpra server for the GUI prototype.

This is prototype tooling, not production HAIBOX code. It resolves a HAIBOX
engagement, injects a per-session password over stdin, and starts Xpra inside
the engagement container with a fixed command line. Every forwarding feature is
explicitly disabled; the server listens only on container loopback and has no
published port.

Usage:
    uv run python .../session.py prepare --engagement gui-a --state-dir ...
    uv run python .../session.py verify --engagement gui-a --state-dir ...
    uv run python .../session.py stop --engagement gui-a
"""

from __future__ import annotations

import argparse
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from relay import DEFAULT_CONTEXT, RelayError, resolve_engagement  # noqa: E402

DISPLAY = ":100"
PORT = 14500
PASSWORD_FILE = "/tmp/xpra-auth"
LOG_FILE = "/tmp/xpra.log"
RUNTIME_DIR = "/tmp/xpra-runtime"

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


class SessionError(RuntimeError):
    """A safe, operator-facing session failure."""


def _docker(
    context: str, args: list[str], *, input_bytes: bytes | None = None, timeout: int = 60
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["docker", "--context", context, *args],
        input=input_bytes,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def _must(
    context: str, args: list[str], *, input_bytes: bytes | None = None, timeout: int = 60
) -> bytes:
    result = _docker(context, args, input_bytes=input_bytes, timeout=timeout)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise SessionError(f"docker {' '.join(args[:3])} failed: {detail}")
    return result.stdout


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
    state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    password = secrets.token_urlsafe(18)
    password_path = state_dir / f"{engagement}.password"
    password_path.write_text(password, encoding="utf-8")
    password_path.chmod(0o600)

    version = _must(context, ["exec", container, "xpra", "--version"]).decode().strip()
    if "6.5.4" not in version:
        raise SessionError(f"unexpected Xpra version: {version}")

    # Fresh runtime directory and password file inside the container.
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
    )
    _must(
        context,
        ["exec", "-i", container, "sh", "-c", f"umask 077; cat > {PASSWORD_FILE}"],
        input_bytes=password.encode(),
    )

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
    )

    deadline = time.monotonic() + 30
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
            timeout=10,
        )
        if probe.returncode == 0:
            break
        time.sleep(0.5)
    else:
        log = _docker(context, ["exec", container, "tail", "-40", LOG_FILE])
        raise SessionError(
            "Xpra did not listen on container loopback: "
            + log.stdout.decode("utf-8", "replace")
        )

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
    data_dir: str | None,
    config_dir: str | None,
    context: str,
) -> None:
    container, _workspace = resolve_engagement(
        engagement, data_dir=data_dir, config_dir=config_dir, context=context
    )
    _docker(
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
        timeout=30,
    )
    _docker(context, ["exec", container, "sh", "-c", f"rm -f {PASSWORD_FILE}"], timeout=30)


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
                data_dir=args.data_dir,
                config_dir=args.config_dir,
                context=args.context,
            )
            result = {"stopped": args.engagement}
    except (RelayError, SessionError) as exc:
        print(f"session: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
