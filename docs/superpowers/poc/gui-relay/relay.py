#!/usr/bin/env python3
"""Engagement-bound local Xpra relay for the HAIBOX GUI prototype.

This is a disposable prototype, not production HAIBOX code. It resolves a
HAIBOX engagement by ID, verifies the managed labels on that engagement's
container, binds a Unix-domain socket in a private directory, authenticates the
local peer with ``SO_PEERCRED``, and bridges the Xpra stream through a fixed
non-TTY ``docker exec`` running ``socat`` to the container loopback listener.

It never accepts a container name, never opens a TCP listener, never publishes a
port, and never forwards a user-selected command to Docker. The Xpra server
still authenticates the session with its own password file; the relay adds the
local-UID check and engagement binding.

Usage (from the repository root, through uv):

    uv run python docs/superpowers/poc/gui-relay/relay.py --engagement gui-a
    xpra attach socket:///run/user/1000/haibox-gui-a.sock --password-file=...

The socket path is printed as a JSON line on startup.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import select
import signal
import socket
import struct
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from haibox.engagement import EngagementManager  # noqa: E402
from haibox.paths import Paths  # noqa: E402

DEFAULT_CONTEXT = os.environ.get("HAIBOX_DOCKER_CONTEXT", "haibox")
XRPA_PORT = 14500
FIXED_EXEC = ("socat", "-", f"TCP:127.0.0.1:{XRPA_PORT}")
SO_PEERCRED = 17  # Linux


class RelayError(RuntimeError):
    """A safe, operator-facing relay failure."""


def _docker_inspect(context: str, name: str) -> dict[str, Any]:
    process = subprocess.run(
        ["docker", "--context", context, "inspect", name],
        text=True,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        detail = process.stderr.strip() or "no output"
        raise RelayError(f"cannot inspect container {name}: {detail}")
    try:
        raw = json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise RelayError(f"cannot parse docker inspect output for {name}") from exc
    if not isinstance(raw, list) or not raw or not isinstance(raw[0], dict):
        raise RelayError(f"unexpected docker inspect output for {name}")
    return raw[0]


def resolve_engagement(
    engagement_id: str,
    *,
    data_dir: str | None = None,
    config_dir: str | None = None,
    context: str = DEFAULT_CONTEXT,
) -> tuple[str, Path]:
    """Resolve one engagement ID to its verified container name and workspace."""

    paths = Paths.resolve(data_dir, config_dir)
    try:
        engagement = EngagementManager(paths).load(engagement_id)
    except Exception as exc:  # noqa: BLE001 - relay must report a clean refusal
        raise RelayError(f"unknown engagement {engagement_id!r}: {exc}") from exc

    expected = engagement.runtime.container_name
    if expected != f"haibox-{engagement_id}":
        raise RelayError(
            f"engagement {engagement_id!r} has an unexpected container name"
        )

    raw = _docker_inspect(context, expected)
    config = raw.get("Config")
    config = config if isinstance(config, dict) else {}
    labels = config.get("Labels")
    labels = labels if isinstance(labels, dict) else {}
    state = raw.get("State")
    state = state if isinstance(state, dict) else {}

    if labels.get("haibox.managed") != "true":
        raise RelayError(f"container {expected} is not HAIBOX-managed")
    if labels.get("haibox.engagement") != engagement_id:
        raise RelayError(
            f"container {expected} does not belong to engagement {engagement_id!r}"
        )
    if str(state.get("Status", "")).lower() != "running":
        raise RelayError(f"container {expected} is not running")

    workspace = paths.workspace_dir(engagement_id).resolve()
    return expected, workspace


def _peer_uid(client: socket.socket) -> int | None:
    try:
        credentials = client.getsockopt(
            socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i")
        )
    except OSError:
        return None
    _pid, uid, _gid = struct.unpack("3i", credentials)
    return uid


class Relay:
    def __init__(
        self,
        *,
        container: str,
        socket_path: Path,
        context: str = DEFAULT_CONTEXT,
        once: bool = False,
    ) -> None:
        self.container = container
        self.socket_path = socket_path
        self.context = context
        self.once = once
        self.stop = threading.Event()
        self.child: subprocess.Popen[bytes] | None = None
        self._active = threading.Lock()

    # ------------------------------------------------------------------ setup
    def _listen(self) -> socket.socket:
        self.socket_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.socket_path.exists():
            raise RelayError(f"relay socket already exists: {self.socket_path}")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(self.socket_path))
        self.socket_path.chmod(0o600)
        listener.listen(4)
        listener.settimeout(0.5)
        return listener

    # ------------------------------------------------------------------ bridge
    def _start_child(self) -> subprocess.Popen[bytes]:
        args = [
            "docker",
            "--context",
            self.context,
            "exec",
            "-i",
            self.container,
            *FIXED_EXEC,
        ]
        return subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )

    def _stop_child(self) -> None:
        child = self.child
        self.child = None
        if child is None:
            return
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream is not None:
                with contextlib.suppress(OSError):
                    stream.close()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait(timeout=5)

    def _pump(self, source: Any, destination: Any) -> None:
        try:
            while not self.stop.is_set():
                chunk = source.read(65536) if hasattr(source, "read") else source.recv(65536)
                if not chunk:
                    break
                if hasattr(destination, "write"):
                    destination.write(chunk)
                else:
                    destination.sendall(chunk)
                if hasattr(destination, "flush"):
                    destination.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            try:
                if hasattr(destination, "shutdown"):
                    destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def serve_client(self, client: socket.socket) -> None:
        uid = _peer_uid(client)
        if uid != os.getuid():
            client.close()
            return
        if not self._active.acquire(blocking=False):
            # One Xpra session per relay. A second local client is refused
            # without touching the active stream.
            client.close()
            return
        try:
            child = self._start_child()
            self.child = child
            assert child.stdin is not None
            assert child.stdout is not None
            assert child.stderr is not None

            to_child = threading.Thread(
                target=self._pump, args=(client, child.stdin), daemon=True
            )
            from_child = threading.Thread(
                target=self._pump, args=(child.stdout, client), daemon=True
            )
            to_child.start()
            from_child.start()

            # Keep the child stderr drained so a noisy Xpra failure cannot
            # block the stream. Never print it: it may contain session data.
            error_thread = threading.Thread(
                target=self._drain, args=(child.stderr,), daemon=True
            )
            error_thread.start()

            to_child.join()
            from_child.join(timeout=2)
            client.close()
        finally:
            self._stop_child()
            self._active.release()

    @staticmethod
    def _drain(stream: Any) -> None:
        try:
            while stream.read(65536):
                pass
        except (BrokenPipeError, OSError):
            pass

    # ------------------------------------------------------------------ run
    def run(self) -> int:
        listener = self._listen()
        print(
            json.dumps(
                {
                    "engagement": self.container.removeprefix("haibox-"),
                    "container": self.container,
                    "socket": str(self.socket_path),
                    "uri": f"socket://{self.socket_path}",
                    "transport": "unix",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        try:
            while not self.stop.is_set():
                try:
                    ready, _, _ = select.select([listener], [], [], 0.5)
                except InterruptedError:
                    continue
                if not ready:
                    continue
                client, _ = listener.accept()
                worker = threading.Thread(
                    target=self.serve_client, args=(client,), daemon=True
                )
                worker.start()
                if self.once:
                    worker.join()
                    break
        finally:
            listener.close()
            self._stop_child()
            with contextlib.suppress(FileNotFoundError):
                self.socket_path.unlink()
        return 0

    def request_stop(self, *_args: object) -> None:
        self.stop.set()
        self._stop_child()


def _socket_path(engagement_id: str, explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    runtime = os.environ.get("XDG_RUNTIME_DIR")
    if runtime:
        return Path(runtime) / f"haibox-{engagement_id}.sock"
    return Path(f"/tmp/haibox-{engagement_id}.sock")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engagement", required=True)
    parser.add_argument("--data-dir")
    parser.add_argument("--config-dir")
    parser.add_argument("--context", default=DEFAULT_CONTEXT)
    parser.add_argument("--socket")
    parser.add_argument(
        "--once",
        action="store_true",
        help="serve one client then exit (used by negative tests)",
    )
    args = parser.parse_args(argv)

    try:
        container, _workspace = resolve_engagement(
            args.engagement,
            data_dir=args.data_dir,
            config_dir=args.config_dir,
            context=args.context,
        )
        relay = Relay(
            container=container,
            socket_path=_socket_path(args.engagement, args.socket),
            context=args.context,
            once=args.once,
        )
    except RelayError as exc:
        print(f"relay: {exc}", file=sys.stderr)
        return 2

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, relay.request_stop)
    try:
        return relay.run()
    except RelayError as exc:
        print(f"relay: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
