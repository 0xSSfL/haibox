"""Local Unix-domain relay into one engagement's Xpra server.

The relay is the only way a host process reaches a GUI session:

* the socket lives in an owner-controlled 0700 directory and is created with
  mode 0600;
* the peer is authenticated with ``SO_PEERCRED`` and only the relay's own user
  is accepted, so another local account cannot attach;
* at most ``max_connections`` clients are served at a time;
* every copy is bounded by an idle and a write timeout, and the container
  bridge is a fixed command that the caller cannot influence.
"""

from __future__ import annotations

import contextlib
import os
import select
import socket
import struct
import threading
import time
from pathlib import Path
from typing import Any

from haibox.gui.credentials import ensure_private_directory
from haibox.gui.errors import GuiCredentialError, GuiRelayError
from haibox.gui.spec import GuiSessionSpec
from haibox.runtime.base import ContainerRuntime

SO_PEERCRED = 17  # Linux
CHUNK_SIZE = 65536


class GuiRelay:
    """Serve one GUI session over a local Unix-domain socket."""

    def __init__(
        self,
        runtime: ContainerRuntime,
        spec: GuiSessionSpec,
        socket_path: Path,
    ) -> None:
        self.runtime = runtime
        self.spec = spec
        self.socket_path = Path(socket_path).expanduser().absolute()
        self.stop = threading.Event()
        self._listener: socket.socket | None = None
        self._active = threading.Lock()
        self._workers: list[threading.Thread] = []

    # ------------------------------------------------------------------ setup
    def _listen(self) -> socket.socket:
        try:
            ensure_private_directory(self.socket_path.parent)
        except GuiCredentialError as exc:
            raise GuiRelayError(str(exc)) from exc
        if self.socket_path.exists() or self.socket_path.is_symlink():
            raise GuiRelayError(f"relay socket already exists: {self.socket_path}")
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            listener.bind(str(self.socket_path))
            self.socket_path.chmod(0o600)
            listener.listen(max(2, self.spec.limits.max_connections))
        except OSError as exc:
            listener.close()
            raise GuiRelayError(f"cannot bind the relay socket: {exc}") from exc
        listener.settimeout(0.5)
        return listener

    # ------------------------------------------------------------ peer checks
    @staticmethod
    def peer_uid(client: socket.socket) -> int | None:
        """Return the peer credentials of a connected socket."""

        try:
            raw = client.getsockopt(socket.SOL_SOCKET, SO_PEERCRED, struct.calcsize("3i"))
        except OSError:
            return None
        try:
            _pid, uid, _gid = struct.unpack("3i", raw)
        except struct.error:
            return None
        return uid

    def _authenticate(self, client: socket.socket) -> None:
        uid = self.peer_uid(client)
        if uid is None:
            raise GuiRelayError("cannot read the peer credentials")
        if uid != os.getuid():
            raise GuiRelayError("the peer user does not own this session")

    # ---------------------------------------------------------------- bridging
    def _bridge_command(self) -> list[str]:
        """Return the fixed container command that carries the Xpra stream."""

        return ["socat", "-", f"TCP:{self.spec.bind_tcp}"]

    def _open_stream(self) -> Any:
        try:
            return self.runtime.exec_stream(self.spec.container, self._bridge_command())
        except Exception as exc:  # noqa: BLE001 - surfaced as a relay error
            raise GuiRelayError(f"cannot open the container stream: {exc}") from exc

    # ------------------------------------------------------------------ copies
    @staticmethod
    def _set_nonblocking(stream: Any) -> None:
        """Put a socket or a pipe into non-blocking mode."""

        with contextlib.suppress(OSError, AttributeError, ValueError):
            os.set_blocking(stream.fileno(), False)

    def _write_chunk(self, destination: Any, chunk: bytes) -> None:
        """Write a chunk to a socket or a pipe, bounded by the write timeout."""

        view = memoryview(chunk)
        deadline = time.monotonic() + self.spec.limits.stream_write_timeout
        descriptor = destination.fileno()
        while view:
            try:
                written = os.write(descriptor, view)
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("relay write timed out") from None
                with contextlib.suppress(InterruptedError, OSError, ValueError):
                    select.select([], [destination], [], min(0.5, remaining))
                continue
            except OSError as exc:
                raise ConnectionError(str(exc)) from exc
            if written <= 0:
                raise ConnectionError("relay write made no progress")
            view = view[written:]

    def _pump(self, source: Any, destination: Any, activity: list[float]) -> None:
        """Copy bytes in one direction until the stream ends or goes idle.

        Both ends may be a socket or a pipe: the client side is a Unix-domain
        socket and the container side is a byte stream.
        """

        self._set_nonblocking(source)
        self._set_nonblocking(destination)
        try:
            while not self.stop.is_set():
                try:
                    ready, _, _ = select.select([source], [], [], 0.5)
                except (OSError, ValueError):
                    break
                if not ready:
                    if time.monotonic() - activity[0] > self.spec.limits.stream_idle_timeout:
                        break
                    continue
                try:
                    chunk = os.read(source.fileno(), CHUNK_SIZE)
                except BlockingIOError:
                    continue
                except OSError:
                    break
                if not chunk:
                    break
                activity[0] = time.monotonic()
                self._write_chunk(destination, chunk)
        except (BrokenPipeError, ConnectionError, TimeoutError, OSError):
            pass
        finally:
            with contextlib.suppress(OSError):
                if isinstance(destination, socket.socket):
                    destination.shutdown(socket.SHUT_WR)

    # ------------------------------------------------------------------ serving
    def serve_client(self, client: socket.socket) -> None:
        """Bridge one authenticated local client to the container stream."""

        try:
            self._authenticate(client)
        except GuiRelayError:
            with contextlib.suppress(OSError):
                client.close()
            return
        if not self._active.acquire(blocking=False):
            client.close()
            return
        stream = None
        try:
            stream = self._open_stream()
            client.setblocking(False)
            activity = [time.monotonic()]
            upstream = threading.Thread(
                target=self._pump,
                args=(client, stream.stdin, activity),
                daemon=True,
            )
            downstream = threading.Thread(
                target=self._pump,
                args=(stream.stdout, client, activity),
                daemon=True,
            )
            upstream.start()
            downstream.start()
            self._workers = [upstream, downstream]
            while upstream.is_alive() and downstream.is_alive():
                upstream.join(timeout=0.2)
                downstream.join(timeout=0.2)
                if self.stop.is_set():
                    break
        except Exception:  # noqa: BLE001 - a bad client must not kill the relay
            pass
        finally:
            if stream is not None:
                with contextlib.suppress(Exception):
                    stream.shutdown()
            with contextlib.suppress(OSError):
                client.shutdown(socket.SHUT_RDWR)
            with contextlib.suppress(OSError):
                client.close()
            for worker in self._workers:
                worker.join(timeout=self.spec.limits.shutdown_timeout)
            self._workers = []
            self._active.release()

    def serve_forever(self) -> int:
        """Serve clients until the relay is stopped."""

        listener = self._listen()
        self._listener = listener
        try:
            while not self.stop.is_set():
                try:
                    ready, _, _ = select.select([listener], [], [], 0.5)
                except InterruptedError:
                    continue
                if not ready:
                    continue
                try:
                    client, _ = listener.accept()
                except OSError:
                    continue
                worker = threading.Thread(
                    target=self._safe_serve, args=(client,), daemon=True
                )
                worker.start()
        finally:
            listener.close()
            with contextlib.suppress(FileNotFoundError):
                self.socket_path.unlink()
        return 0

    def _safe_serve(self, client: socket.socket) -> None:
        try:
            self.serve_client(client)
        except Exception:  # noqa: BLE001 - a bad client must not kill the relay
            with contextlib.suppress(OSError):
                client.close()

    def request_stop(self) -> None:
        """Stop the relay and release the socket."""

        self.stop.set()
        listener = self._listener
        if listener is not None:
            with contextlib.suppress(OSError):
                listener.close()
