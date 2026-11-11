# HAIBOX Desktop architecture proposal

**Status:** Design proposal and isolated proof-of-concept scope; not an accepted
production architecture.  
**Date:** 2026-11-10  
**Branch:** `design/haibox-desktop`

**Review records:** [security review](../reviews/2026-11-10-haibox-desktop-security-review.md),
[image validation](../poc/2026-11-10-gui-image-validation.md), and
[design-review plan](../plans/2026-11-10-haibox-desktop-design-review.md). The
security review allows further isolated prototyping but does not approve a
production feature.

## Goal

Provide optional, native Linux application windows for tools running inside a
HAIBOX engagement. A user should be able to start an engagement's GUI session,
launch an application such as `xterm` or Burp Suite, see that application as a
normal window on the Linux desktop, disconnect, and later reconnect. Terminal
use remains the default and requires no GUI packages.

The experience takes Exegol's individual-window workflow as a usability
reference. The local Exegol source was inspected read-only:

- `exegol/exegol/model/ContainerConfig.py::enableGUI()` binds the host X11
  socket and/or Wayland socket into the container and forwards display-related
  environment variables.
- `exegol/exegol/model/ExegolContainer.py::__applyX11ACLs()` can grant
  `xhost +local:<user>` on local Linux X11, or extracts an Xauthority cookie
  for forwarded X11.

That approach is not the secure HAIBOX design: a compromised GUI application
would speak directly to the host display server, and the container receives
host display authority. HAIBOX must not expose `/tmp/.X11-unix`, a Wayland
socket, a host Xauthority file, or a broadly relaxed display ACL to the runner.

## Recommendation

Prototype **Xpra seamless mode with an isolated Xpra server and headless X11
display per engagement**. The initial implementation should keep the Xpra
server, GUI applications, and engagement workspace in the same GUI-enabled
engagement container. This preserves the existing one-engagement/one-network
boundary and avoids a second container-to-container display channel. “Separate
display server” means the Xpra-managed headless display is separate from the
operator's host display; it does not mean sharing the host display socket.

The operator's native Xpra client connects to a short-lived local relay bound
only to `127.0.0.1`. The relay authorizes the selected engagement, then bridges
Xpra's transport over an attached, non-TTY Docker Exec stream. The Xpra server
listens only on its container loopback and has per-session authentication.
There are no published ports. The client binary is a host prerequisite supplied
by the user's Linux distribution; HAIBOX should document packages and a
capability check without assuming Fedora-specific package names.

This is still a candidate architecture, not a production-verified transport.
Xpra documents stdin/stdout as its SSH transport pattern, but does not document
Docker Exec as an Xpra transport. The isolated PoC verifies a generic byte
relay and one actual Xpra version pair on one host only. Do not implement a
public `haibox gui` command or claim cross-distro/Wayland support until a
production relay and host-client matrix have been reviewed and tested.

The follow-on isolated PoC has now connected a Fedora 44 Xpra 6.5.4 native
client to a container Xpra 6.5.4 server through a localhost relay backed by
non-TTY Docker Exec, and rendered xterm windows in the Fedora window manager.
That validates the basic transport and X11 display path on this one host. It
does not validate a production relay, cross-distro/Wayland behavior, or hostile
protocol handling. Detailed evidence and limits are recorded in
[`2026-11-10-xpra-seamless.md`](../poc/2026-11-10-xpra-seamless.md).

The temporary Fedora test image required 233 packages and measured 1.16 GB
because the distro Xpra package pulls desktop and multimedia dependencies. A
production GUI image must remain optional and separate from terminal-only
images, and its dependency closure should be minimized and scanned before any
release.

### Proposed shape

```text
Linux desktop (X11 or Wayland session)
  └── host Xpra client (trusted, distro-provided)
        └── 127.0.0.1 ephemeral authenticated relay
              └── HAIBOX CLI / Docker Exec (no TTY, no published port)
                    └── haibox-gui-<engagement> container
                          ├── Xpra server + headless X11 display
                          ├── GUI application process(es), non-root
                          ├── same isolated engagement network policy
                          └── same persistent /workspace, ro scope file
```

The client/server protocol should use Xpra's native transport over the relay,
not expose a direct container address. The Xpra listener must bind only to
container loopback. The Docker Exec helper connects to that loopback listener;
the relay must not implement a second display protocol. A future implementation
may use a maintained Xpra SSH/stdio adapter if its API supports the installed
client/server versions. Otherwise a small, audited byte relay can wrap Docker
Exec and localhost TCP, with framing, backpressure, cancellation, and child
cleanup tested explicitly.

### CLI proposal

```text
haibox gui start <engagement>
haibox gui run <engagement> -- <application> [arguments...]
haibox gui status <engagement>
haibox gui stop <engagement>
```

- GUI is disabled when an engagement is created. `gui start` is the explicit,
  audited opt-in and creates or starts only that engagement's GUI runtime.
- `gui run` validates the engagement and GUI session, checks the application
  against the image/profile's allowed tool inventory, and passes argv without a
  shell. The first PoC may directly start only the fixed `xterm` test command.
- `gui status` shows the associated container/session and relay state, without
  exposing credentials.
- `gui stop` closes the relay, detaches the client, stops GUI child processes,
  invalidates session credentials, and keeps the engagement workspace.
- All operations are tied to the engagement ID and managed Docker labels. A
  GUI session cannot be looked up by a free-form container name.

These names are a design sketch only; do not add them to the CLI in this phase.

## Alternatives

| Approach | Native-window behavior | Security and operations | Decision |
|---|---|---|---|
| Direct host X11/Wayland socket sharing | Straightforward and widely familiar; Exegol's `--gui` is an example | Violates the no-host-socket requirement. X11 clients can observe/control broad parts of the display session; Xauthority is a sensitive credential. Wayland uses per-session sockets, but handing the socket to an untrusted container still delegates compositor protocol authority. ACL changes can widen access beyond one engagement. | Reject for secure mode. Never use `xhost +`; do not silently fall back to direct sharing. |
| Xpra seamless with per-engagement headless X11 server | Xpra presents individual remote application windows to the host window manager; multiple apps can appear side by side. Host X11 and host Wayland sessions can use a native Xpra client, subject to testing. | Adds Xpra server/client and relay attack surface, but the app sees only its isolated display. Per-engagement session identity, authentication, local-only relay, disabled forwarding features, and Docker Exec avoid host display sockets and published ports. | Preferred prototype. Validate actual protocol transport, host display integration, and disconnect/reconnect before production design review. |
| Waypipe | Native Wayland application forwarding, designed for an SSH-like workflow | Waypipe documents that it does not provide strong security guarantees and does not filter all Wayland protocols. Container-to-host Wayland protocol forwarding through Docker Exec is not tested here. Support and behavior depend on the compositor and app. | Keep as a later comparison, not the first implementation. Revisit if Xpra's host Wayland support proves inadequate and protocol isolation can be strengthened. |
| Xpra Wayland server backend | Could provide seamless windows from a Wayland-native server | Xpra describes the backend as experimental and notes it may require a separate `xpra-server-wayland` package. Compatibility across host clients, apps, and distros is unproven. | Defer; use Xpra's headless X11 server for the first PoC. |
| KasmVNC/noVNC sidecar | Full desktop in a browser; not individual host-managed windows | Prior research verified that Docker Exec can relay generic WebSocket bytes over loopback on the current isolated bridge, but no Kasm desktop, auth, or browser session was tested. | Retain for a future optional full-desktop mode; it does not meet this native-window goal. |

## Security analysis

### Assets and principals

- Host display session, host filesystem, Docker daemon, and all other
  engagements.
- Each engagement's persistent workspace and scope policy.
- Host-only evidence, audit records, secrets, and session credentials.
- Operator (trusted control-plane user), GUI applications and targets
  (untrusted), Xpra client/server and relay (additional attack surface).

### Boundaries and controls required before production

1. **Display boundary:** no display socket, Xauthority, host runtime directory,
   or host filesystem mount in the GUI container. Xpra's headless display is
   created inside the container and isolated to one engagement.
2. **Container boundary:** non-root UID/GID, `CAP_DROP ALL`,
   `no-new-privileges`, read-only root, private IPC, existing seccomp defaults,
   CPU/memory/PID limits, and only the existing workspace RW + scope RO mounts.
   No privileged mode, host namespaces/network, device, Docker socket, port
   publishing, or arbitrary bind mount.
3. **Network boundary:** GUI process uses the engagement's exact network policy.
   `isolated` is appropriate for the offline PoC. The existing `scoped` M2 mode
   is only a prototype: it does not enforce scope for host services or embedded
   DNS and lacks negative integration tests. Do not expose external targets or
   claim target-scope enforcement until M2 prerequisites and its tests pass.
4. **Identity boundary:** session IDs and credentials are engagement-bound;
   CLI actions verify managed labels and engagement identity before attaching.
   The Xpra listener is loopback-only inside its own container. The host relay
   binds `127.0.0.1` only, chooses an ephemeral port, authenticates the local
   Xpra client, and terminates on detach/stop. No relay can attach to another
   engagement by changing a name or container ID supplied by the caller.
5. **Session boundary:** disable clipboard in both directions, file transfer,
   audio playback/capture, microphone, webcam, printing, notifications, system
   tray, DBus control, and any unused device/feature forwarding. Disable server
   command-start features and session sharing. Never use Xpra's unauthenticated
   `allow`/`none` auth mode. Generate short-lived per-session credentials; do
   not place secrets in argv, logs, image layers, or workspace.
6. **Lifecycle boundary:** explicit opt-in; normal user can close/detach, stop,
   and restart the GUI. Stopping revokes the auth material and kills only the
   engagement's GUI processes. The workspace remains attached to the engagement
   and persists through stop/restart. Every state-changing action is audited.
7. **Supply-chain boundary:** Xpra and GUI package versions are pinned in any
   future manifest and scanned through both existing vulnerability scanners.
   Keep all HIGH/CRITICAL findings visible; a successful build or GUI test is
   not a security verification claim. The Fedora proof-of-concept image is not
   supported by the installed Trivy and therefore has no vulnerability result;
   the production image is blocked until a scanner-supported packaging path is
   chosen and scanned. See the [image validation record](../poc/2026-11-10-gui-image-validation.md).

### Threats and residual risk

| Threat | Required mitigation | Residual risk |
|---|---|---|
| Malicious app exploits Xpra server | Keep server in the same restricted engagement container; patch/pin it; disable unused handlers; resource limits | App and server share a process/container trust boundary; an Xpra exploit may compromise the engagement container |
| Malicious display data exploits host Xpra client | Pin supported client versions, use distro packages, minimize enabled features, test disconnect/hostile protocol inputs | The host client parses attacker-influenced pixels, window metadata, and protocol messages; client bugs can affect the operator account |
| Relay used to reach host services | Bind only to host loopback; relay only from authenticated client and only to a fixed Docker Exec for one managed GUI container; never expose a general TCP proxy | Other local processes under the same user, and processes with Docker access, may connect or control the daemon; this is inside the current host trust boundary |
| Cross-engagement attachment | Per-engagement container/network/display, random session credentials, immutable ID mapping, strict label checks, explicit relay teardown | A compromised Docker daemon or host operator can cross this boundary |
| GUI bypasses network policy | GUI process inherits exactly the engagement network; use `isolated` for initial PoC only | Current `scoped` M2 does not enforce scope; no external target connectivity until that is fixed and negatively tested |
| Clipboard/file/audio exfiltration | Disable each forwarding subsystem at both ends and regression-test defaults | Future upstream/config changes could re-enable a feature; pinned version and config checks are required |
| Session credential exposure | Store mode 0600 host-side, inject over an authenticated control channel, avoid mounts/argv/logs, revoke on stop | Same-UID applications may inspect processes or files in the runner; if app execution is untrusted, container-local secret exposure remains a design concern |
| Host display authority leakage | No host X11/Wayland socket or Xauthority mount; host-side Xpra client connects outward to a loopback relay | The native client is still a host process exposed to remote display content |

The existing isolated bridge removes ordinary bridge host addressing and
external routing in the recorded Docker Engine test. It is not a universal host
security boundary and does not replace isolation testing on each supported
Docker Engine/platform combination.

## Burp Suite and browser notes

Burp Suite Community Edition is available from PortSwigger's Linux installer,
and PortSwigger documents Burp's browser for Community Edition. Its Community
license is non-transferable/non-sublicensable and its terms restrict resale,
copying, and making it available to non-employees or as a service without
written consent. Do not place Burp binaries in a public HAIBOX image or make
them downloadable through HAIBOX. A later opt-in flow may ask the operator to
download the installer and accept PortSwigger's terms, subject to confirming
the intended distribution model. The included Burp browser is the most direct
candidate for testing browser traffic through Burp Proxy against a local,
authorized lab target. Do not expose internet/LAN routing for this test.

## Minimal proof-of-concept

### Environment and scope

- Run on the user's current Fedora 44 X11 session as the actual host-display
  integration check; keep the architecture distro-neutral and separately
  describe host client packaging for Arch, Fedora, and other Linux families.
- Use the dedicated HAIBOX Docker context and an isolated-network disposable
  engagement. No daemon, firewall, SELinux, service, or global package changes.
- Use an existing or temporary GUI test image containing only Xpra, a headless
  X server, `xterm`, and relay support. Do not change any production image.
- Launch the host Xpra client against a localhost relay; relay to the Xpra
  listener using non-TTY Docker Exec. No published Docker port, host display
  socket mount, or host Xauthority mount.
- Create only a harmless offline target inside the same engagement for the
  later browser/Burp check. No external target or LAN access.

### Acceptance tests

1. A seamless `xterm` window appears on the Fedora desktop, can be moved and
   closed normally, and can coexist with a second GUI window.
2. `ps`/process inspection through the managed CLI proves `xterm` and Xpra
   server processes run inside the GUI container; host process list shows only
   the host Xpra client and relay.
3. Inspect the GUI container and relay: no host X11/Wayland socket, Xauthority,
   Docker socket, device, host namespace, published port, or mount other than
   workspace RW and scope RO is present.
4. From the GUI container, probe known local host services and a second
   disposable engagement; both must be unreachable. Confirm no default route,
   no external DNS, and no public IPv4/IPv6 reachability under isolated mode.
5. Attempt attachment using an invalid token and another engagement's identity;
   both must fail without changing session state.
6. Disconnect, stop, and restart. Confirm host listener and Docker Exec child
   disappear on detach/stop, the old credential fails, a new session attaches,
   and workspace files remain.
7. Confirm clipboard, file transfer, audio, webcam, printing, notification,
   tray, DBus, and server-side command execution features are unavailable.
8. Only after the xterm gate passes, test browser access to an offline local
   lab through Burp Proxy. Do not claim Burp redistribution is permitted; use
   the user's own installer and license acceptance if testing is authorized.

The existing generic WebSocket/Docker Exec probe does not satisfy tests 1–8.
This proof of concept is not a production security assessment and cannot
establish resistance to kernel, Docker daemon, Xpra client/server, or host
compositor vulnerabilities.

## Production implementation plan (blocked on review)

1. **Review, transport, and packaging gate:** review this proposal; resolve Xpra
   version compatibility and prove the real seamless Xpra stream over Docker Exec
   on Fedora X11. Confirm the client works on a Wayland desktop without mounting
   a host socket into the container. In parallel, choose a scanner-supported
   image base and Xpra package path; the current Fedora fixture is not scanned
   because Trivy does not support it. If the transport or host client requires a
   forbidden host socket, stop and reassess Waypipe/other protocols.
2. **Prototype artifacts:** build a disposable GUI image and a narrow host
   relay harness outside the production CLI. Record commands, versions,
   screenshots, Docker inspection output, negative probes, and cleanup proof.
3. **Security review:** test relay authentication, session authorization,
   cross-engagement rejection, client/server compatibility, feature-disable
   defaults, malformed/disconnected streams, bounded resources, and cleanup.
4. **Production design:** only after review, update the ADR, `docs/architecture`,
   `docs/threat-model`, `docs/roadmap`, image manifest/catalog, verification
   status, and user guide. Add validated GUI fields to `ContainerSpec`, a narrow
   duplex Docker Exec seam, CLI audit/tests, negative integration tests, and a
   pinned/scanned optional image.
5. **Scope gate:** GUI sessions remain isolated by default. External target
   access is deferred until M2 scope enforcement covers host services, embedded
   DNS, IPv4/IPv6, and has negative integration tests. Do not rely on GUI
   transport as network enforcement.

## References

- [Exegol CLI start and `--gui`](https://docs.exegol.com/wrapper/cli/start)
- Read-only local Exegol source: `exegol/exegol/model/ContainerConfig.py`
  (`enableGUI`) and `exegol/exegol/model/ExegolContainer.py`
  (`__applyX11ACLs`) under `/home/souaib/Work/haibox-research/repos/exegol`.
- [Xpra seamless mode](https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Seamless.md)
- [Xpra security](https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Security.md)
- [Xpra authentication](https://github.com/Xpra-org/xpra/blob/master/docs/Usage/Authentication.md)
- [Xpra network transports](https://github.com/Xpra-org/xpra/blob/master/docs/Network/README.md)
- [Xpra manual](https://xpra.org/manual)
- [Xpra Go client and SSH stdio transport](https://github.com/Xpra-org/go-xpra)
- [Waypipe man page](https://gitlab.freedesktop.org/mstoeckl/waypipe/-/raw/master/waypipe.scd)
- [Fedora Xpra packages](https://packages.fedoraproject.org/pkgs/xpra/xpra/)
- [Docker Engine Exec API](https://docs.docker.com/reference/api/engine/version/v1.56/)
- [Burp downloads](https://portswigger.net/burp/downloads),
  [Burp Community terms](https://portswigger.net/burp/tc-community),
  [EULA](https://portswigger.net/burp/eula),
  [Burp browser](https://portswigger.net/burp/documentation/desktop/tools/burps-browser)
- Detailed checked sources and earlier KasmVNC/isolated-bridge research:
  [`2026-11-10-desktop-vendor-research.md`](../research/2026-11-10-desktop-vendor-research.md)
