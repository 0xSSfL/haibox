# Xpra GUI readiness verification

**Status:** Prototype verified; production feature not approved.  
**Date:** 2026-11-11; hardening evidence added 2026-11-12  
**Decision record:** [ADR-0011](../../adr/0011-gui-session-in-existing-runner.md)  
**Prior design review:** [2026-11-10 Desktop security review](../reviews/2026-11-10-haibox-desktop-security-review.md)

This record covers the disposable readiness prototype for optional Xpra
seamless windows in an existing HAIBOX engagement runner. It does not add a
`haibox gui` command, GUI fields to `ContainerSpec`, a catalog image, or a
production security approval.

## Environment

| Item | Value |
|---|---|
| Host | Fedora Linux 44 x86_64, X11 `:0`, dwm |
| Docker | 29.9.2 client and server, dedicated `haibox` context |
| Host Xpra client | 6.5.4, extracted from the Fedora RPM into `/tmp`; no host package install |
| Container Xpra server | 6.5.4 |
| Image | `haibox/gui-poc-validation:0.1.0` |
| Image digest | `sha256:929aed1739d5f48f76809856cdf0de8bb7aa9b8ee0fba2fc2c572d670c10068b` |
| Image size | 1,399,669,162 bytes |
| Engagements | `gui-a`, `gui-b`; `core` profile, empty scope, isolated network |

The production CLI, runtime, `ContainerSpec`, and `images/` catalog trees were
not changed. All prototype files live under `docs/superpowers/poc/`.

## Artifacts

| Path | Purpose |
|---|---|
| `docs/superpowers/poc/gui-image/Dockerfile` | Pinned Fedora 44 Xpra fixture |
| `docs/superpowers/poc/gui-image/manifest.yaml` | Base digest, direct versions, inventory, scan policy |
| `docs/superpowers/poc/gui-image/packages.lock` | 502-package RPM inventory |
| `docs/superpowers/poc/gui-relay/relay.py` | Engagement-bound Unix-socket relay |
| `docs/superpowers/poc/gui-relay/session.py` | Xpra server prepare/verify/stop helper |
| `docs/superpowers/poc/gui-relay/security.py` | Private directory and password-file helpers |

`packages.lock` SHA-256:
`5c87a0908d77144f8beff935097e220814f8d1802ba9bad658bac277642afe06`.

## Image and scanner result

The fixture builds from the pinned Fedora 44 digest
`sha256:15da97ed9aa94dd3d92c3925eb89520f6c80e07ea7ee24cba848d1f8b6912b3e`
and installs pinned direct packages. It contains 502 RPMs.

The hardened HAIBOX scanner was run against the real image:

- Trivy 0.76.2 reports Fedora 44 as unsupported and does not scan OS packages.
- The adapter rejects that report and falls back to Grype 0.121.3.
- Grype covers Fedora 44 (`grype: fedora 44`).
- Grype reports **4 CRITICAL and 61 HIGH** findings. The scan gate is closed.

Representative findings:

| Severity | Package | Installed | Fixed |
|---|---|---|---|
| CRITICAL | `pillow` | 12.3.0 | 13.0.0 |
| HIGH | `pillow` | 12.3.0 | 13.0.0 |
| HIGH | `pcre2` / `pcre2-syntax` | 10.47-1.fc44.1 | 10.49-1.fc44 |

The scanner did not suppress findings. This closes the "Trivy silently passes
Fedora" coverage gap (F-01) but **does not** open the vulnerability gate. A
production GUI image must reduce or formally justify these findings under the
normal image policy.

## Transport and authentication

The host client connects to a Unix-domain socket, not a TCP listener and not a
published Docker port.

```
xpra client
  -> /tmp/opencode/gui-readiness/runtime/relay-a.sock  (directory 0700, socket 0600)
  -> relay.py (same local UID, SO_PEERCRED check)
  -> docker --context haibox exec -i haibox-gui-a socat - TCP:127.0.0.1:14500
  -> Xpra server bound to 127.0.0.1:14500 inside the container
```

The relay derives the container from a validated engagement ID, verifies
`haibox.managed=true`, `haibox.engagement=<id>`, and a running state, and only
spawns the fixed `socat` bridge. It never accepts a container name or an
operator-supplied command.

The Xpra server uses `--bind-tcp=127.0.0.1:14500,auth=file:filename=...`; the
password is delivered over stdin to a mode-0600 file inside the container and is
not present in argv. The container path is
`/tmp/xpra-runtime/xpra-auth`; the runtime directory is recreated with mode 0700,
the write uses `noclobber`, and the helper checks the resulting mode. The host
password file is created with `O_EXCL | O_NOFOLLOW` and mode 0600 in a verified
owner-controlled 0700 state directory. The tested password length was 24 bytes
for `gui-b` and 16 bytes for `gui-a`; both matched exactly with no trailing
newline.

Evidence:

- Client log: `Attached to xpra server at socket:///tmp/opencode/gui-readiness/runtime/relay-a.sock`.
- `wmctrl -l`: `xterm on haibox-gui-a` and `xterm on haibox-gui-b`.
- Container listener: `/proc/net/tcp` shows only `0100007F:38A4` (`127.0.0.1:14500`).

## Deny-by-default forwarding

The server started with 14 explicit controls:

```
--clipboard=no --file-transfer=no --printing=no
--speaker=disabled --microphone=disabled --webcam=no
--notifications=no --system-tray=no
--dbus=no --dbus-control=no
--start-new-commands=no --sharing=no --html=no --mdns=no
```

`session.py verify` asserts every flag in `/proc/<pid>/cmdline`, confirms
`sharing=False`, and checks the negotiated client subsystem list. Observed
client subsystems:

```
Client, ClientID, ClientInfo, Event, Sharing, MMAP, Keyboard, Pointer,
Bandwidth, Ping, Menu, Display, Cursors, Windows, Encodings
```

No `Clipboard`, `FileTransfer`, `Printing`, `Audio`, `Webcam`, `Notifications`,
or `Tray` subsystem was negotiated. The host client used matching flags. The
container has no PulseAudio server, so audio cannot be captured even if a
subsystem were negotiated. No automated per-feature negative test exists yet;
this is an assertion check, not adversarial proof (F-04 remains open).

## Container invariants

`docker inspect haibox-gui-a` recorded:

| Property | Value |
|---|---|
| `Privileged` | `false` |
| Network | `haibox-gui-a-net` (isolated) |
| `PidMode` / `IpcMode` | empty / `private` |
| `ReadonlyRootfs` | `true` |
| `CapDrop` / `CapAdd` | `["ALL"]` / none |
| `SecurityOpt` | `no-new-privileges:true` |
| `PortBindings` / `PublishAllPorts` | `{}` / `false` |
| `Devices` | none |
| Mounts | workspace read-write; `scope.json` read-only |
| User | `1000:1000` |

The container cannot see `/run/user`, a host display socket, or
`/var/run/docker.sock`. The only X11 socket under `/tmp/.X11-unix` is the
container's own Xvfb display (`X100`), not a host socket.

## Test matrix

| Test | Result | Evidence |
|---|---|---|
| Pinned image build | Pass | `sha256:929aed…068b`, 502 RPMs |
| Package inventory | Pass | 502-line `packages.lock`, SHA-256 recorded |
| Scanner coverage fallback | Pass for coverage, fail for findings | Trivy unsupported; Grype covers Fedora; 4 CRITICAL + 61 HIGH |
| Fedora X11 attach | Pass | `Attached…`, `xterm on haibox-gui-a` |
| Wayland client backend | Pass for display/surface | `GTK3 Wayland client`, Weston scene graph shows `xdg_toplevel` window `xterm on haibox-gui-a` |
| Wayland input forwarding | Not verified | headless Weston has no seat/input devices |
| Second engagement attach | Pass | `Attached…`, `xterm on haibox-gui-b` |
| Wrong password | Pass (refused) | exit 28, `Authentication failed`, server log confirms |
| Cross-engagement password A→B | Pass (refused) | exit 28, `Authentication failed` |
| Cross-engagement password B→A | Pass (refused) | exit 28, `Authentication failed` |
| Concurrent second client | Pass (refused) | exit 18, first client and window unaffected |
| Unknown engagement | Pass (refused) | exit 2, `unknown engagement` |
| Unmanaged container | Pass (refused) | exit 2, `is not HAIBOX-managed` |
| Wrong engagement label | Pass (refused) | exit 2, `does not belong to engagement` |
| Client detach | Pass | window and Docker Exec child gone; socket still listens for reconnect |
| Container stop while attached | Pass | window closed, relay child gone, client exited |
| Relay start against stopped container | Pass (refused) | exit 2, `is not running` |
| Relay SIGTERM while attached | Pass | socket removed, child exited, client exited |
| Cross-engagement network probe | Pass (blocked) | `gui-a` cannot resolve `haibox-gui-b` (no DNS); TCP probe exit 255 |
| Host display/Docker socket absent | Pass | paths absent in container |
| Host firewall/daemon changes | None | only `haibox` context and managed containers used |

## Wayland

The host has no Wayland session (`XDG_SESSION_TYPE=x11`). To test the client
backend without changing the host, a disposable Fedora 44 container ran Weston
15.0.1 as a headless compositor:

```
weston --backend=headless --renderer=pixman --socket=wayland-haibox \
       --width=1280 --height=720 --idle-time=0 --debug
```

The Weston socket directory was mounted into the host runtime directory with
mode 0700. The host Xpra 6.5.4 client was started with `GDK_BACKEND=wayland`,
`WAYLAND_DISPLAY=wayland-haibox`, `XDG_RUNTIME_DIR` pointing at that directory,
and `DISPLAY` unset.

Evidence:

- `xpra GTK3 Wayland client version 6.5.4`;
- `window manager is 'dwm on wayland'`;
- `desktop size is 1280x720: wayland-haibox (1280x720 mm)`;
- `Attached to xpra server at socket:///tmp/opencode/gui-readiness/runtime/relay-a.sock`;
- Weston scene graph:
  `View … role xdg_toplevel … top-level window 'xterm on haibox-gui-a' of Xpra`
  with a 875x1094 SHM buffer on the 1280x720 headless output.

This proves the Xpra client creates a real Wayland `xdg_toplevel` surface and
renders the remote window through the relay. It does **not** prove keyboard or
pointer input forwarding: headless Weston provides no seat or input devices, and
GTK logged `gdk_seat_get_keyboard`/`gdk_seat_get_pointer` assertions. A real
Fedora Workstation Wayland session remains untested (F-08 partially closed).

## Prototype hardening (2026-11-12)

The relay and session scripts were revised without changing the approved
architecture. The production CLI, runtime, `ContainerSpec`, and image catalog
remain untouched.

| Control | Implementation | Regression evidence |
|---|---|---|
| Fail-closed target preflight | `isolated` network and empty `allowed`/`allowed_ports` are required before Docker inspection; observed `HostConfig.NetworkMode` must match the engagement network | `test_relay_preflight_*`, `test_resolve_engagement_rejects_scope_before_docker_inspect`, `test_resolve_engagement_rejects_observed_network_mismatch` |
| Host password creation | `O_EXCL`/`O_NOFOLLOW`, mode 0600 from creation, verified owner-owned 0700 parent, symlink/non-regular replacement refused | `test_password_file_is_private_and_rotation_replaces_content`, `test_password_file_refuses_symlink_without_touching_target`, `test_password_file_requires_private_parent`, `test_private_directory_rejects_symlink` |
| Container password | Private `/tmp/xpra-runtime` recreated at 0700, `noclobber` write over stdin, mode checked after creation | `test_prepare_writes_container_password_in_private_runtime` |
| Rotation and stale credentials | Every prepare rotates the password and replaces only a regular host file; stale container state is removed before writing | `test_prepare_creates_private_host_file_and_rotates_secrets`, `test_prepare_failure_removes_stale_host_and_container_password` |
| Stop and failure cleanup | Host and container password files removed on stop, even when `xpra stop` fails; failed prepare removes both; unsafe engagement IDs are rejected before any path is built | `test_stop_removes_host_and_container_password_even_if_xpra_stop_fails`, `test_stop_rejects_unsafe_engagement_id_before_removing_anything`, `test_prepare_refuses_non_private_state_directory` |
| Socket path | No `/tmp` fallback; `XDG_RUNTIME_DIR` or an explicit socket path must be inside an owner-controlled 0700 directory; existing paths are refused | `test_socket_path_requires_xdg_runtime_dir`, `test_socket_path_rejects_shared_parent`, `test_socket_path_accepts_private_parent`, `test_relay_refuses_existing_socket_path` |
| Bounded relay I/O | Docker inspect 10 s, stream idle 120 s, blocked write 10 s, child wait/terminate/kill 5/2/2 s, non-blocking stream copies, disconnect marks the stream done | `test_docker_inspect_timeout_is_bounded`, `test_relay_pump_idle_timeout_marks_stream_done`, `test_relay_pump_eof_marks_stream_done`, `test_relay_blocked_write_times_out`, `test_relay_child_cleanup_is_bounded` |
| Bounded session Docker calls | Every helper call carries a timeout and converts `TimeoutExpired` into a clean `SessionError` | `test_session_docker_timeout_is_reported` |

The new tests are in `tests/unit/test_gui_prototype.py` and use fakes only. They
do not re-run the hardened scripts against a real Docker endpoint; that
revalidation remains required before any production claim.

### Shared trust boundary

The GUI does not create a new sandbox inside the runner. Xpra and every
application it starts run as the same container user, with the same writable
workspace and read-only scope file, network namespace, capability set, and
resource limits as terminal tools in the engagement. A GUI application can read
the Xpra password file when it runs as that user, connect to the loopback
listener, inspect or signal Xpra, inject input into other applications in the
same display, and read or modify everything in the workspace.

The Xpra password protects the host-to-container transport only. Applications
in one GUI session are trusted at the same level as anything else launched in
that runner; do not run mutually untrusted applications there. Per-application
isolation would require a separate trust domain and is not part of this design.
See [ADR-0011 section 4](../../adr/0011-gui-session-in-existing-runner.md).

## Remaining blockers

The prototype does not close F-02 through F-09:

- no hostile/malformed/truncated Xpra stream tests;
- no fixed resource-limit or client/server version matrix beyond Fedora 44 Xpra
  6.5.4;
- relay crash/reconnect/backpressure and audit integration are not production
  code;
- no automated negative test for each disabled forwarding feature;
- external targets remain forbidden until M2 scope enforcement is complete;
- the prototype rotates and removes credentials, but container-side removal
  requires the engagement container to be running; if it is already stopped,
  the host copy is removed and the container runtime directory remains until
  the next prepare resets it;
- audited revocation and log-redaction are not implemented in a product
  lifecycle;
- the hardened relay/session scripts have unit regressions but have not been
  re-run against a real Docker endpoint;
- server packaging for the Debian-based catalog and host-client distribution
  remain undecided;
- container escape, compositor, and host-client vulnerabilities remain residual
  risks.

## Reproduction

Prototype commands (not production entry points):

```bash
# Build the disposable fixture
docker --context haibox build -t haibox/gui-poc-validation:0.1.0 \
  docs/superpowers/poc/gui-image

# Prepare and verify the server for an engagement
uv run python docs/superpowers/poc/gui-relay/session.py prepare \
  --engagement gui-a --state-dir /tmp/opencode/gui-readiness \
  --data-dir /tmp/opencode/gui-readiness/data \
  --config-dir /tmp/opencode/gui-readiness/config
uv run python docs/superpowers/poc/gui-relay/session.py verify \
  --engagement gui-a --data-dir /tmp/opencode/gui-readiness/data \
  --config-dir /tmp/opencode/gui-readiness/config

# Stop the server and remove host/container password files
uv run python docs/superpowers/poc/gui-relay/session.py stop \
  --engagement gui-a --state-dir /tmp/opencode/gui-readiness \
  --data-dir /tmp/opencode/gui-readiness/data \
  --config-dir /tmp/opencode/gui-readiness/config

# Regression checks for the hardened prototype (no Docker required)
uv run pytest tests/unit/test_gui_prototype.py -q

# Start the relay, then attach with the extracted host client
uv run python docs/superpowers/poc/gui-relay/relay.py --engagement gui-a \
  --data-dir /tmp/opencode/gui-readiness/data \
  --config-dir /tmp/opencode/gui-readiness/config \
  --socket /tmp/opencode/gui-readiness/runtime/relay-a.sock
```
