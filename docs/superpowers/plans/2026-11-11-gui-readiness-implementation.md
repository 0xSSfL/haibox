# GUI readiness implementation plan

**Goal:** turn the verified Xpra readiness prototype into an optional,
auditable GUI capability without weakening the existing runner invariants.

**Decision:** [ADR-0011](../../adr/0011-gui-session-in-existing-runner.md) — the GUI
runs inside the existing engagement runner, never in a per-engagement sidecar.

**Evidence:** [`2026-11-11 Xpra GUI readiness`](../poc/2026-11-11-xpra-gui-readiness.md).

**Current gate:** no production `haibox gui` command until Phases 1 and 2 are
complete. The prototype scripts under `docs/superpowers/poc/` are not product
code.

## Non-negotiable constraints

- One runner per engagement; no GUI sidecar, second network, or second
  workspace.
- No host X11/Wayland socket, Xauthority, Docker socket, device, published port,
  privileged mode, or host namespace.
- GUI only on the `isolated` network profile, with no external targets.
- Clipboard, file transfer, printing, audio, microphone, webcam, notifications,
  tray, DBus, sharing, and server-side command execution stay disabled by
  default.
- The relay accepts an engagement ID, never a container name or command.
- Every state change is audited and tested.
- No catalog image or production claim while the scan gate is closed.

## Phase 1 — Image and vulnerability gate

**Deliverables**

1. Choose the production base and packaging path for the server image:
   - preferred: a base the primary scanner supports, with distro Xpra packages;
   - fallback: a Fedora image with a recorded Grype-only exception approved
     under the image policy.
2. Add `images/gui/` with a `manifest.yaml` and `Dockerfile` only after the base
   decision. Do not reuse the disposable fixture tag.
3. Pin the base digest, direct package NEVRAs, Xpra server version, and the
   host-client version range.
4. Record `packages.lock` from the built image and check it into the image
   directory or evidence record.
5. Run `uv run haibox image scan gui` through the hardened adapter and record
   every HIGH/CRITICAL finding.

**Exit criteria**

- `image build` and `image verify` pass.
- The scan gate is open: zero HIGH/CRITICAL findings, or a reviewed and
  documented exception that does not suppress findings.
- The manifest and Dockerfile agree on the base digest and versions.
- No `--ignore-unfixed`, global ignores, or path-wide suppressions.

## Phase 2 — Runtime seam and relay

**Deliverables**

1. Add a small `src/haibox/gui/` package:
   - `spec.py`: fixed session specification (display, loopback port, password
     file path, disabled features, start command). No arbitrary flags.
   - `session.py`: prepare/verify/stop operations against the existing
     `ContainerRuntime`.
   - `relay.py`: the Unix-socket relay, extracted from the prototype with
     production error handling and audit hooks.
2. Extend the runtime seam only as needed for:
   - a fixed, non-TTY `docker exec -i <container> socat - TCP:127.0.0.1:<port>`
     bridge;
   - a fixed `xpra start` invocation and a fixed `xpra info` verification read.
   Do not add a general command-execution API.
3. Resolve engagements through `EngagementManager` and verify:
   - expected `haibox-<id>` container name;
   - `haibox.managed=true`;
   - `haibox.engagement=<id>`;
   - container is running;
   - network mode is `isolated`;
   - scope has no external targets.
4. Bind the relay socket in a 0700 directory with mode 0600, authenticate the
   peer with `SO_PEERCRED`, and allow one active client.
5. Generate a per-session password, deliver it over stdin, rotate on start, and
   delete it on stop. Never put it in argv, the workspace, or logs.
6. Audit `gui.session.prepared`, `gui.session.started`, `gui.session.stopped`,
   `gui.session.refused`, and relay cleanup outcomes.

**Exit criteria**

- Unit tests with `FakeRuntime` cover engagement resolution, managed-label
  rejection, wrong engagement label, non-isolated network, external scope,
  wrong password, concurrent client, detach, stop, and SIGTERM cleanup.
- The relay has no container-name or command parameter in any public API.
- Audit tests assert one entry for every state change and refusal.
- A negative test shows the relay cannot bridge to a different engagement.

## Phase 3 — CLI surface

Add commands only after Phase 2 lands:

```
haibox gui start   [--engagement ID]
haibox gui attach  [--engagement ID]
haibox gui stop    [--engagement ID]
haibox gui status  [--engagement ID]
```

**Behaviour**

- `start` prepares the server and prints the socket/URI; it does not start a
  host client.
- `attach` requires a prepared session and runs the host client with the fixed
  deny-by-default flags.
- `stop` stops the server, removes the password, and terminates the relay.
- `status` reports the session, listener, and relay state.
- Every command supports the root `--json` option and audits its result.
- Any non-isolated network or external target is refused with a non-zero exit
  code and an audit entry.

**Tests**

- CLI tests through `tests.conftest.invoke` with `FakeRuntime`.
- Audit entry per command and per refusal.
- No command accepts an image, command, socket path, port, or Docker flag from
  the user.
- `gui attach` fails closed if the host client is missing or the wrong version.

## Phase 4 — Host client distribution

**Deliverables**

1. Define the supported host matrix. Minimum: the tested Fedora release; add a
   Debian/Ubuntu path only after packaging and version tests exist.
2. Add a `doctor` check for the Xpra client binary and version. Do not install
   packages automatically.
3. Document the exact package source and verification step for the host client.
4. Keep the client version pinned to the server major/minor pair that was
   tested.

**Exit criteria**

- `doctor` reports a missing or unsupported client without a traceback.
- A clean host install path is documented and tested on at least one Fedora
  release.
- Debian packaging remains explicitly unsupported until tested.

## Phase 5 — Security validation

Add these before claiming the feature is usable:

1. **Protocol robustness:** malformed, truncated, oversized, and slow streams
   against the relay and Xpra server; assert bounded memory, timeouts, and clean
   teardown.
2. **Forwarding negatives:** a test client attempts clipboard, file transfer,
   printing, audio, microphone, webcam, notifications, DBus, and command
   execution; every attempt must fail and be recorded.
3. **Authentication:** wrong password, missing password, empty password,
   repeated attempts, and password rotation on restart.
4. **Cross-engagement:** password reuse, relay socket confusion, label tamper,
   non-managed container, stopped container, and network probe.
5. **Lifecycle:** client detach/reconnect, relay crash, container stop, container
   removal, engagement archive/destroy, and host reboot cleanup.
6. **Resources:** pids, memory, and session time limits for the Xpra server and
   started applications.
7. **Wayland:** a real Fedora Workstation Wayland session with keyboard and
   pointer input, not only a headless compositor surface.
8. **Client surface:** record the host-client version and review its release
   notes before each supported update.

## Phase 6 — Documentation and release gate

Update:

- `docs/architecture.md` for the GUI data path and trust boundary;
- `docs/threat-model.md` for the host client, relay, and Xpra server;
- `docs/verification-status.md` with every command and negative result;
- `docs/user-guide.md` with installation, start/attach/stop, and limitations;
- `docs/roadmap.md` only when the milestone state actually changes.

**Release gate**

- image build, verify, and scan pass under policy;
- unit, CLI, and opt-in integration suites pass;
- the relay and session have negative integration tests against real Docker;
- a real X11 and a real Wayland input test pass on supported hosts;
- no open F-02 through F-09 blocker remains, or each exception is recorded with
  an owner and expiry;
- documentation does not claim more than the recorded evidence.

## Out of scope

- TigerVNC or full remote-desktop sessions;
- external or LAN targets through the GUI before M2 scope enforcement;
- browser-embedded or web clients;
- Windows/macOS hosts;
- automatic host package installation;
- GUI support in terminal-only catalog images.
