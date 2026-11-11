# HAIBOX Desktop security review

**Status:** Design review completed; production implementation not approved.  
**Date:** 2026-11-10, image evidence rechecked 2026-11-11.  
**Scope:** The isolated desktop architecture proposal, Xpra proof of concept,
vendor research, and disposable image evidence in this branch. There is no
production GUI CLI, runtime, or image code to review.  
**Decision:** Continue design and throwaway prototyping behind a hard production
gate. Do not add `haibox gui` commands, GUI fields to `ContainerSpec`, or a
catalog image until every blocking finding below is closed and the production
acceptance gates in the plan are met.

## Method

The review compared the proposal with:

- the security invariants in `AGENTS.md`;
- the trust boundaries in `docs/threat-model.md` and
  `docs/architecture.md`;
- the existing `ContainerSpec` constraints and managed-label rules;
- the recorded Xpra proof of concept and vendor research; and
- a rebuilt disposable Fedora fixture scanned with the installed Trivy.

The review does not certify Xpra, Docker, the Fedora or Debian package
ecosystems, or the host display server. A successful window test is not a
security test.

## Invariant review

| Invariant | Design position | Evidence | Status |
|---|---|---|---|
| No host display socket, Wayland socket, or Xauthority mount | Host Xpra client connects outward to a loopback relay; the container uses a headless Xpra display | PoC inspection found no host X11/Wayland socket, `XAUTHORITY`, `DISPLAY`, or `WAYLAND_DISPLAY` | Pass for PoC |
| No privileged mode, host namespaces, devices, or published ports | Reuse the existing engagement container shape | Inspection found `Privileged=false`, private IPC, no devices, empty port bindings | Pass for PoC |
| Non-root, dropped capabilities, no-new-privileges, read-only root, resource limits | Reuse the existing runner constraints | PoC ran as UID/GID 1000:1000 with the existing limits | Pass for PoC |
| Only workspace read/write and scope read-only | Reuse the existing mounts | Inspection found only those mounts | Pass for PoC |
| Engagement network policy applies to GUI processes | GUI runs in the engagement container | Isolated-network negative probes passed | Pass for isolated only |
| Engagement-bound identity and managed labels | GUI session must resolve from an engagement ID, never a caller-supplied container name | No production CLI exists | Not implemented |
| Per-session authentication; no unauthenticated mode | Random password, wrong-password and credential-rotation tests | PoC passed | Pass for PoC; production mechanism not designed |
| Disable clipboard, file transfer, audio, camera, printing, notifications, tray, DBus, and remote command start | Disable at both client and server | Launched disabled, but not adversarially tested | Partial |
| Every state-changing action is audited | GUI start/run/stop must be audited | No GUI commands exist | Not implemented |
| Pinned and scanned image | Optional image with manifest versions and scanner evidence | Fixture pins direct packages; Trivy does not support Fedora 44 | Blocked |
| External scope is enforced or absent | GUI stays on `isolated`; no external targets | `scoped` remains a forward-only prototype | Pass by restriction |

## Findings

### F-01 (High, production blocker): scanner coverage is not established

The disposable Fedora 44 fixture is not a supported Trivy OS. The installed
Trivy 0.76.2 reports `WARN Unsupported os family="fedora"` and produces no
vulnerability results. This is not a clean scan.

Worse, the current `ImageScanner` adapter treats a zero exit code as success and
does not reject unsupported-OS or empty-result reports. A Fedora-based GUI image
could therefore appear to pass `haibox image scan` without any vulnerability
data. The production image must use a scanner-supported base, or the adapter
must explicitly fail on unsupported OS and empty results, with a regression
test. That adapter change is out of scope for this design-review branch.

### F-02 (High, production blocker): host client and display server attack surface

The host Xpra client parses attacker-influenced pixels, window metadata, and
protocol messages from the engagement. An Xpra server or application exploit can
also cross the shared container boundary between the GUI application and the
Xpra server. Required mitigations are pinned client/server versions, distro
packages where possible, disabled unused handlers, fixed resource limits, and
malformed/truncated/hostile stream tests. No such tests exist yet.

### F-03 (High, production blocker): relay authorization and lifecycle

The PoC relay was hard-coded to one managed container and did not implement
dynamic engagement selection, cross-engagement rejection, backpressure, or a
production child-cleanup path. The production relay must resolve a fixed target
from a validated engagement ID, authenticate the local client, support only the
Xpra stream for that target, and never become a general TCP proxy. Detach, stop,
crash, and reconnect paths need negative tests.

### F-04 (High): forwarding features must be deny-by-default and tested

The PoC launched both ends with clipboard, file transfer, printing, audio,
microphone, webcam, notifications, tray, DBus controls, and server-side command
execution disabled. Those flags were not verified adversarially, and an upstream
default or packaging change could re-enable a feature. Production needs
configuration assertions at both ends and negative tests for every disabled
subsystem.

### F-05 (High): scope enforcement is not ready for GUI targets

The GUI proof used the `isolated` network. The existing `scoped` profile only
hooks `forward`; it does not cover host services or Docker embedded DNS and has
no negative integration tests. GUI sessions must remain isolated. Do not expose
external or LAN targets through the GUI until the M2 scope prerequisites and
negative tests are complete.

### F-06 (Medium): session credential handling

The PoC used a random password file in container `/tmp` and a host-side mode-0600
file. A compromised same-UID application can inspect container-local material.
A production design must define credential generation, delivery, rotation,
revocation, and log redaction without putting secrets in argv, images, or the
workspace. The current evidence is sufficient for a disposable PoC only.

### F-07 (Medium): packaging and version-pair coverage

Only Fedora 44 Xpra 6.5.4 client and server were tested. Debian 13, the HAIBOX
catalog base, has no `xpra` package candidate in the recorded snapshot; using
xpra.org packages would add a third-party repository and signing key. The
supported host-client matrix and the server packaging path remain undecided.
Wayland and other distributions are unverified.

### F-08 (Medium): Wayland and compositor behavior

The PoC ran on Fedora 44 X11 with dwm. Xpra's native client may work on Wayland
without mounting a compositor socket, but that has not been tested. A Wayland
result is required before claiming Linux desktop support.

### F-09 (Low): proof-of-concept limits

The PoC did not test Docker/kernel escape resistance, hostile protocol inputs,
host Xpra client vulnerabilities, compositor vulnerabilities, or non-Docker
runtimes. These remain residual risks, not failures of the narrow display test.

## Required decisions before production

1. Choose a scanner-supported base and a reviewed Xpra source. Close F-01 and
   F-07 together.
2. Approve the relay architecture, authentication mechanism, and lifecycle
   contract. Close F-03 and F-06.
3. Define deny-by-default feature controls and add automated assertions. Close
   F-04.
4. Record a tested host-client matrix, including at least one Wayland session.
   Close F-08.
5. Keep GUI sessions isolated and defer external targets until scope
   enforcement is real. Close F-05 only through the M2 gate.
6. Add production audit, managed-label resolution, and negative integration
   tests before any `haibox gui` command is exposed.
7. Keep Burp Suite and other restricted binaries out of distributable images
   until the licensing position is reviewed.

## Verdict

The design direction is acceptable for continued isolated prototyping. The
production implementation is **not approved**, the disposable image is **not a
catalog image**, and this branch makes **no claim of GUI security, scanner
coverage, or supported cross-distro operation**.
