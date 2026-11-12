# ADR-0011: Optional GUI sessions in the existing engagement runner

- Status: Proposed; prototyping direction accepted, production implementation not approved
- Date: 2026-11-11
- Related: ADR-0003 (scope enforcement), ADR-0008 (isolated network), ADR-0009 (no legacy internal profile), ADR-0010 (scoped profile), PR #8 design review

## Context

PR #8 reviewed an optional native-window workflow for tools running inside a
HAIBOX engagement. It left two questions open:

1. whether GUI support belongs in the existing engagement runner or in a
   separate per-engagement GUI sidecar; and
2. whether the transport, authentication, forwarding controls, and lifecycle
   can satisfy the HAIBOX invariants.

The review recorded blocking findings F-01 through F-09. This ADR resolves the
lifecycle question and fixes the security contract for the first prototype. It
does not approve a production feature, add a `haibox gui` command, add GUI
fields to `ContainerSpec`, or add a catalog image.

## Decision

### 1. Use the existing GUI-enabled runner; do not add a GUI sidecar

An engagement keeps exactly one runner container, one engagement network, one
workspace, one scope file, and one lifecycle. GUI support is an optional
capability of the runner image and an optional process inside that runner.

- Terminal-only images remain unchanged and require no GUI packages.
- A GUI-capable image is an opt-in image choice, not a second container.
- The GUI server starts only when the operator asks for it. Normal manual CLI
  operation (`shell`, `run`, `container create/start/stop`) never starts a
  display server.
- Stopping or removing the engagement stops the GUI session with it. There is
  no separate GUI process, container, network, or workspace to leak or clean up.
- The GUI session inherits the runner's existing managed labels, network
  profile, resource limits, read-only root filesystem, dropped capabilities, and
  workspace mount. No new privileged path is introduced.

### 2. Transport is an engagement-bound local Unix-socket relay

The host does not mount a display socket or expose a container port. The data
path is:

```
host Xpra client
  -> Unix-domain socket (0700 directory, 0600 socket)
  -> HAIBOX relay process owned by the same local UID
  -> fixed non-TTY `docker exec -i <container> socat - TCP:127.0.0.1:14500`
  -> Xpra server bound only to container loopback
```

The relay:

- accepts an engagement ID, never a container name or arbitrary command;
- resolves the engagement through `EngagementManager`, derives the expected
  `haibox-<id>` container name, and rejects a mismatch;
- verifies `haibox.managed=true` and `haibox.engagement=<id>` on the running
  container before listening;
- fails closed unless the engagement uses the `isolated` network profile with
  an empty `scope.allowed` and `scope.allowed_ports`, then verifies the observed
  `HostConfig.NetworkMode` matches the engagement network;
- binds the socket only inside an owner-controlled 0700 directory. If `--socket`
  is omitted, `XDG_RUNTIME_DIR` must be set; there is no world-writable `/tmp`
  fallback;
- bounds Docker inspection (10 s), stream idle time (120 s), blocked stream
  writes (10 s), and child shutdown (5 s wait, 2 s terminate, 2 s kill);
- authenticates the local peer with `SO_PEERCRED` and accepts only the relay's
  own UID;
- allows one Xpra stream at a time and refuses additional local clients without
  disturbing the active stream;
- spawns only `socat - TCP:127.0.0.1:14500` over Docker Exec, never a
  user-selected command, shell, or TTY;
- removes its socket and terminates its child on disconnect, crash, SIGINT, or
  SIGTERM.

A relay restart is required after the container stops. The relay validates the
container at startup and does not become a general TCP proxy.

### 3. Xpra authenticates the session independently

The Xpra server binds only `127.0.0.1:14500` inside the container and uses the
file authentication module with a per-session random password written over
stdin to a mode-0600 file. The password is passed to the server as a filename,
never as a command-line value. The container password lives in a freshly
created mode-0700 runtime directory, is written with `noclobber`, and its mode
is checked after creation.

The host holds the matching password in a mode-0600 file outside the workspace.
The host file is created with `O_EXCL | O_NOFOLLOW` in a verified owner-owned
0700 directory; a pre-existing symlink or non-regular file is refused. The
password is rotated on every prepare, and both host and container copies are
removed on stop and on failed prepare. A stale host copy is replaced only when
it is a regular file.

The relay's UID check and the Xpra password are independent controls. Neither
is sufficient alone: the relay prevents other local users from reaching the
container stream, and Xpra prevents an unauthenticated stream from controlling
the display.

### 4. Graphical applications share the runner's trust boundary

Admitting a GUI does not add a sandbox between the graphical application and
the rest of the engagement runner. Xpra and every application it starts run as
the same container user, in the same mount and network namespaces, with the
same capability set, workspace mount, scope file, and resource limits as
terminal tools in that engagement.

Consequences:

- A GUI application can read and modify the entire writable workspace, read the
  scope file, inspect Xpra's environment and process memory, read the Xpra
  password file when it runs as the same user, connect to the container
  loopback listener, inject input into another application in the same display,
  kill the session, and consume the engagement's CPU and memory budget.
- The Xpra password protects the host-to-container transport. It does not
  isolate applications from each other inside the container.
- GUI applications must be treated as trusted at the same level as any other
  tool launched in the engagement. Do not run mutually untrusted applications
  in one GUI session or assume that closing a window revokes their access.
- A production design that needs per-application isolation requires a separate
  trust domain (for example a separate display server and container), which is a
  different architecture and is not approved by this ADR.

### 5. Forwarding is deny-by-default

The first implementation starts Xpra with all non-display features explicitly
disabled:

- clipboard;
- file transfer;
- printing;
- audio output and microphone input;
- webcam;
- desktop notifications and system tray;
- DBus and DBus control;
- server-side new-command execution;
- session sharing;
- HTML and mDNS listeners.

The host client starts with the matching client-side flags. Production code
must assert both the server argv and the negotiated client subsystem list, and
must fail closed if a flag is missing or a subsystem appears. Tested flags and
assertions are recorded in the verification evidence.

### 6. GUI is restricted to the isolated network profile

The GUI is available only with the `isolated` network profile. It must not be
used with external or LAN targets, with the prototype `scoped` profile, or with
a non-empty external scope. Until M2 scope enforcement is complete and has
negative integration tests, GUI use is offline-only, consistent with
ADR-0003 and ADR-0010.

A future `haibox gui` command must refuse to start when the engagement network
is not `isolated`, or when the scope contains external targets. That refusal
must be covered by a test; documentation alone is not enforcement.

The prototype enforces this in both `relay.py` and `session.py` before any
Docker inspection or password write. It also checks the observed container
`NetworkMode` against the engagement network. Unit regression tests cover the
`isolated` requirement, non-empty `allowed` and `allowed_ports`, preflight
ordering, and a network-mode mismatch.

### 7. Lifecycle is engagement-scoped

Starting a GUI session is a state-changing action and must produce an audit
entry. Stopping, failing to start, and refusing an invalid target must also be
audited. Session state belongs to the engagement, not to a global daemon.

The prototype currently removes the socket, Xpra child, host password, and
container password on stop and on failed prepare. The production design must
still define:

- explicit `gui start`, `gui attach`, `gui stop`, and `gui status` semantics;
- cleanup on container stop, container removal, engagement archive/destroy,
  host crash, and relay crash;
- reconnection behaviour after a host client detach;
- resource limits for the Xpra server and applications;
- a fixed, documented host-client version policy;
- audit entries for start, attach, stop, refusal, and failure;
- credential revocation that does not depend on the container still running.

## Rejected alternatives

### Per-engagement GUI sidecar

Rejected. A second container would need the same workspace, a route to the
engagement network, and its own labels and lifecycle. That duplicates the
privilege surface, complicates cleanup, creates a second place where engagement
identity can drift, and makes it easier for a GUI process to outlive or bypass
the runner's managed-label checks. The runner already provides the isolation
boundary the GUI needs.

### Host display socket or Xauthority mount

Rejected. Mounting `/tmp/.X11-unix`, a Wayland socket, or `.Xauthority` gives
the container direct control of the host session and violates the host-only
data boundary. Xpra forwards pixels and events over its own authenticated
stream instead.

### Published Docker port or TCP relay on the host

Rejected. A published port exposes the display stream beyond the local host and
weakens the local-only trust model. The relay binds a Unix-domain socket in a
private directory rather than a TCP listener.

### TigerVNC or a full remote desktop

Rejected for this milestone. The requirement is native, seamless application
windows, not a remote desktop. TigerVNC would add a different authentication
and clipboard/file-transfer surface without solving the seamless-window
requirement.

### Reusing the legacy `internal` network profile

Rejected. ADR-0009 removed it. GUI support does not justify reintroducing it.

## Consequences

- GUI images are larger and carry a larger vulnerability surface than
  terminal-only images. They must remain optional.
- The host needs a compatible Xpra client. The host-client support matrix is a
  production gate, not something this ADR assumes.
- The relay adds a small host process. It is not a daemon: it is tied to one
  engagement and exits when the operator stops it or the container disappears.
- A same-UID process on the host can still connect to the relay socket and
  attempt authentication. The Xpra password remains mandatory, and the socket
  mode plus private directory limit access to the owning UID.

## Open gates

This ADR does **not** close the following, and no production command may ship
until they are resolved:

1. **Scanner gate (F-01):** the disposable Fedora 44 fixture is covered by
   Grype after Trivy rejects the unsupported OS, but the scan currently reports
   4 CRITICAL and 61 HIGH findings. The gate is closed. A production image must
   reduce or justify these findings under the normal image policy.
2. **Host client and protocol hardening (F-02):** hostile, malformed, and
   truncated stream tests, fixed resource limits, and a reviewed client/server
   version matrix are still required.
3. **Relay productionization (F-03):** the prototype validates engagement
   identity, fail-closed network/scope preflight, and bounded cleanup, but
   production needs tested crash/reconnect paths, backpressure limits, audit
   integration, and a restricted runtime seam rather than prototype scripts.
4. **Feature assertions (F-04):** the prototype checks the server argv and the
   negotiated client subsystems; production needs automated negative tests per
   disabled subsystem and a fail-closed configuration check at both ends.
5. **Scope (F-05):** GUI remains isolated and the prototype now refuses
   non-isolated profiles or non-empty target scope before inspect; external
   targets wait for M2.
6. **Credentials (F-06):** the prototype now creates host files with
   `O_EXCL | O_NOFOLLOW` in a verified 0700 directory, writes the container
   password in a private runtime directory, rotates on prepare, and removes
   both copies on stop or failed prepare. Production still needs audited
   revocation and log-redaction guarantees.
7. **Packaging (F-07):** host-client distribution and server image packaging
   are undecided. Debian 13 has no suitable Xpra package in the recorded
   snapshot.
8. **Wayland (F-08):** a real compositor test is required before claiming
   Wayland support.
9. **Residual risk (F-09):** container escape, compositor vulnerabilities, and
   host-client vulnerabilities remain out of scope for the prototype.

## Verification

Prototype evidence is recorded in
[`docs/superpowers/poc/2026-11-11-xpra-gui-readiness.md`](../superpowers/poc/2026-11-11-xpra-gui-readiness.md).

The 2026-11-12 hardening pass adds unit regressions for the fail-closed network
and scope preflight, observed `NetworkMode` mismatch, private socket/host-file
directories, symlink refusal, password rotation and stale-file removal, stop
and failed-prepare cleanup, unsafe engagement IDs, Docker inspect timeout,
stream idle/write bounds, and bounded child termination. These tests use fakes
and do not replace real-Docker revalidation of the hardened scripts.
