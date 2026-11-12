#!/usr/bin/env python3
"""Engagement-bound local Xpra relay for the HAIBOX GUI prototype.

This is a disposable prototype, not production HAIBOX code. It resolves a
HAIBOX engagement by ID, verifies the managed labels and isolated network before
binding a Unix-domain socket in a private directory, authenticates the local
peer with ``SO_PEERCRED``, and bridges the Xpra stream through a fixed non-TTY
``docker exec`` running ``socat`` to the container loopback listener.

It never accepts a container name, never opens a TCP listener, never publishes a
port, and never forwards a user-selected command to Docker. The Xpra server
still authenticates the session with its own password file; the relay adds the
local-UID check and engagement binding.

Usage (from the repository root, through uv):

    uv run python docs/superpowers/poc/gui-relay/relay.py --engagement gui-a
    xpra attach socket:///run/user/1000/haibox-gui-a.sock --password-file=...

The socket path must be inside an owner-controlled 0700 directory. If
``--socket`` is omitted, ``XDG_RUNTIME_DIR`` must be set; there is no world-
writable ``/tmp`` fallback.
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
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO_ROOT / "src"))

from security import SecurityError, ensure_private_directory  # noqa: E402

from haibox.engagement import EngagementManager  # noqa: E402
from haibox.paths import Paths  # noqa: E402
from haibox.scope import load_scope  # noqa: E402

DEFAULT_CONTEXT = os.environ.get("HAIBOX_DOCKER_CONTEXT", "haibox")
XRPA_PORT = 14500
FIXED_EXEC = ("socat", "-", f"TCP:127.0.0.1:{XRPA_PORT}")
SO_PEERCRED = 17  # Linux
INSPECT_TIMEOUT = 10.0


class RelayError(SecurityError):
    """A safe, operator-facing relay failure."""


def _docker_inspect(context: str, name: str) -> dict[str, Any]:
    try:
        process = subprocess.run(
            ["docker", "--context", context, "inspect", name],
            text=True,
            capture_output=True,
            check=False,
            timeout=INSPECT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        raise RelayError(
            f"docker inspect {name} timed out after {INSPECT_TIMEOUT:.0f}s"
        ) from exc
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


def _preflight_engagement(engagement: Any, engagement_id: str) -> None:
    runtime = engagement.runtime
    if runtime.network_mode != "isolated":
        raise RelayError(
            f"engagement {engagement_id!r} uses {runtime.network_mode!r}; "
            "the GUI requires the 'isolated' network profile"
        )

    scope = engagement.scope
    allowed = list(getattr(scope, "allowed", []) or [])
    allowed_ports = list(getattr(scope, "allowed_ports", []) or [])
    if allowed or allowed_ports:
        raise RelayError(
            f"engagement {engagement_id!r} has external targets; "
            "the GUI requires an empty target scope"
        )


def _preflight_scope_file(engagement: Any, engagement_id: str, paths: Any) -> None:
    """Compare metadata with the scope file bind-mounted into the runner."""

    scope_path = paths.scope_file(engagement_id)
    try:
        canonical = load_scope(scope_path)
    except Exception as exc:  # noqa: BLE001 - any unreadable scope is a refusal
        raise RelayError(
            f"cannot read canonical scope file for {engagement_id!r}: {exc}"
        ) from exc
    if engagement.scope != canonical:
        raise RelayError(
            f"engagement {engagement_id!r} scope metadata does not match "
            f"the canonical scope file {scope_path}"
        )


def resolve_engagement(
    engagement_id: str,
    *,
    data_dir: str | None = None,
    config_dir: str | None = None,
    context: str = DEFAULT_CONTEXT,
    require_gui_preflight: bool = True,
) -> tuple[str, Path]:
    """Resolve one engagement ID to its verified container name and workspace.

    ``require_gui_preflight`` is disabled only by the stop path, so an existing
    session can still remove its container password after the engagement scope
    or network settings have drifted away from the GUI policy.
    """

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

    if require_gui_preflight:
        _preflight_scope_file(engagement, engagement_id, paths)
        _preflight_engagement(engagement, engagement_id)
    raw = _docker_inspect(context, expected)

    config = raw.get("Config")
    config = config if isinstance(config, dict) else {}
    labels = config.get("Labels")
    labels = labels if isinstance(labels, dict) else {}
    state = raw.get("State")
    state = state if isinstance(state, dict) else {}
    host_config = raw.get("HostConfig")
    host_config = host_config if isinstance(host_config, dict) else {}
    network_settings = raw.get("NetworkSettings")
    network_settings = network_settings if isinstance(network_settings, dict) else {}

    if labels.get("haibox.managed") != "true":
        raise RelayError(f"container {expected} is not HAIBOX-managed")
    if labels.get("haibox.engagement") != engagement_id:
        raise RelayError(
            f"container {expected} does not belong to engagement {engagement_id!r}"
        )
    if str(state.get("Status", "")).lower() != "running":
        raise RelayError(f"container {expected} is not running")

    expected_network = engagement.runtime.network_name
    observed_network = str(host_config.get("NetworkMode", ""))
    if require_gui_preflight and observed_network != expected_network:
        raise RelayError(
            f"container {expected} uses network {observed_network!r}; "
            f"expected {expected_network!r}"
        )

    if require_gui_preflight:
        networks = network_settings.get("Networks")
        if not isinstance(networks, dict):
            raise RelayError(
                f"container {expected} does not report network membership"
            )
        memberships = sorted(str(name) for name in networks)
        if memberships != [expected_network]:
            raise RelayError(
                f"container {expected} is attached to networks {memberships!r}; "
                f"expected only {expected_network!r}"
            )

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
    CHILD_WAIT_TIMEOUT = 5.0
    CHILD_TERMINATE_TIMEOUT = 2.0
    CHILD_KILL_TIMEOUT = 2.0
    STREAM_IDLE_TIMEOUT = 120.0
    STREAM_WRITE_TIMEOUT = 10.0
    STREAM_POLL_INTERVAL = 1.0
    THREAD_JOIN_TIMEOUT = 2.0

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
        ensure_private_directory(self.socket_path.parent, create=False)
        if self.socket_path.exists() or self.socket_path.is_symlink():
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
            child.wait(timeout=self.CHILD_WAIT_TIMEOUT)
            return
        except subprocess.TimeoutExpired:
            pass
        with contextlib.suppress(OSError, ProcessLookupError):
            child.terminate()
        try:
            child.wait(timeout=self.CHILD_TERMINATE_TIMEOUT)
            return
        except subprocess.TimeoutExpired:
            pass
        with contextlib.suppress(OSError, ProcessLookupError):
            child.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            child.wait(timeout=self.CHILD_KILL_TIMEOUT)

    @staticmethod
    def _set_nonblocking(stream: Any) -> None:
        with contextlib.suppress(OSError, ValueError):
            os.set_blocking(stream.fileno(), False)

    @staticmethod
    def _read_chunk(source: Any) -> bytes | None:
        try:
            if isinstance(source, socket.socket):
                return source.recv(65536)
            return os.read(source.fileno(), 65536)
        except (BlockingIOError, InterruptedError):
            return None

    def _write_chunk(self, destination: Any, chunk: bytes) -> None:
        view = memoryview(chunk)
        deadline = time.monotonic() + self.STREAM_WRITE_TIMEOUT
        while view:
            try:
                if isinstance(destination, socket.socket):
                    written = destination.send(view)
                else:
                    written = os.write(destination.fileno(), view)
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("relay stream write timed out") from None
                try:
                    writable = select.select(
                        [], [destination], [], min(self.STREAM_POLL_INTERVAL, remaining)
                    )[1]
                except InterruptedError:
                    continue
                if not writable:
                    continue
                continue
            if written <= 0:
                raise OSError("relay stream write returned no progress")
            view = view[written:]

    def _pump(
        self,
        source: Any,
        destination: Any,
        activity: list[float],
        stream_done: threading.Event,
    ) -> None:
        self._set_nonblocking(source)
        self._set_nonblocking(destination)
        try:
            while not self.stop.is_set() and not stream_done.is_set():
                try:
                    ready = select.select(
                        [source], [], [], self.STREAM_POLL_INTERVAL
                    )[0]
                except (OSError, ValueError):
                    break
                if not ready:
                    if time.monotonic() - activity[0] > self.STREAM_IDLE_TIMEOUT:
                        break
                    continue
                chunk = self._read_chunk(source)
                if chunk is None:
                    continue
                if not chunk:
                    break
                activity[0] = time.monotonic()
                self._write_chunk(destination, chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            stream_done.set()
            with contextlib.suppress(OSError):
                if isinstance(destination, socket.socket):
                    destination.shutdown(socket.SHUT_WR)

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
        threads: list[threading.Thread] = []
        try:
            child = self._start_child()
            self.child = child
            assert child.stdin is not None
            assert child.stdout is not None
            assert child.stderr is not None

            activity = [time.monotonic()]
            stream_done = threading.Event()
            to_child = threading.Thread(
                target=self._pump,
                args=(client, child.stdin, activity, stream_done),
                daemon=True,
            )
            from_child = threading.Thread(
                target=self._pump,
                args=(child.stdout, client, activity, stream_done),
                daemon=True,
            )
            to_child.start()
            from_child.start()
            threads.extend((to_child, from_child))

            # Keep the child stderr drained so a noisy Xpra failure cannot
            # block the stream. Never print it: it may contain session data.
            error_thread = threading.Thread(
                target=self._drain, args=(child.stderr,), daemon=True
            )
            error_thread.start()
            threads.append(error_thread)

            while to_child.is_alive() and from_child.is_alive():
                to_child.join(timeout=0.2)
                from_child.join(timeout=0.2)
                if stream_done.is_set():
                    break
                if time.monotonic() - activity[0] > self.STREAM_IDLE_TIMEOUT:
                    break
        finally:
            with contextlib.suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
            client.close()
            self._stop_child()
            for thread in threads:
                thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            self._active.release()

    @staticmethod
    def _drain(stream: Any) -> None:
        try:
            while stream.read(65536):
                pass
        except (BrokenPipeError, OSError, ValueError):
            pass

    def _serve_safely(self, client: socket.socket) -> None:
        try:
            self.serve_client(client)
        except Exception:  # noqa: BLE001 - a bad client must not kill the relay
            client.close()

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
                    target=self._serve_safely, args=(client,), daemon=True
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
        candidate = Path(explicit).expanduser().absolute()
    else:
        runtime = os.environ.get("XDG_RUNTIME_DIR")
        if not runtime:
            raise RelayError(
                "XDG_RUNTIME_DIR is not set; pass --socket inside an "
                "owner-controlled 0700 directory"
            )
        candidate = Path(runtime) / f"haibox-{engagement_id}.sock"
    parent = ensure_private_directory(candidate.parent, create=False)
    return parent / candidate.name


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
    except SecurityError as exc:
        print(f"relay: {exc}", file=sys.stderr)
        return 2

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, relay.request_stop)
    try:
        return relay.run()
    except SecurityError as exc:
        print(f"relay: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
