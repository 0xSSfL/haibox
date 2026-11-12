# Architecture

HAIBOX is an isolation-first, manual-first penetration-testing platform. This
document describes the current architecture, the trust boundaries it assumes,
and the seams reserved for VPN and AI work.

> **Implementation status.** The unit suite, lint, and type checks pass on
> Fedora. Direct Docker on Fedora is the primary development and runtime
> target; a dedicated Linux server is the production target; a KVM VM is an
> optional high-assurance deployment. The Web Security, Core, and Network
> Security images build and verify; the Trivy scan gate remains open on
> dependency findings. Statements below describe implemented behaviour unless a
> section explicitly marks a gap.

## 1. Design goals

1. **One engagement, one container, one network.** An engagement cannot address
   another engagement's container, workspace, secrets, or evidence.
2. **The host is the trusted computing base.** Secrets, evidence, reports, and
   audit logs live on the host and are never mounted into an engagement.
3. **Deny by default.** Every container option is constructed by
   `ContainerSpec`; there is no pass-through of arbitrary Docker flags.
4. **The manual lane works without AI.** The AI broker is an optional,
   restricted client of the same runtime interface, not a prerequisite.
5. **Fail closed.** An empty scope denies everything. An unknown profile, an
   unmanaged container, or a missing dedicated Docker context is an error, not
   a warning.

## 2. Deployment shape

```text
Primary: Fedora workstation or dedicated Linux server
└── Docker Engine (rootful, shared with unrelated workloads on Fedora)
    ├── haibox-<engagement>        manual runner container
    ├── haibox-<engagement>-net    internal bridge, isolated gateway mode
    └── (future) haibox-ai-<engagement>  separate AI runner
        haibox CLI (operator account)
        host-only data: secrets, evidence, reports, audit

Optional high-assurance profile:
Fedora workstation
└── KVM / libvirt
    └── haibox-lab VM  <-- the security boundary
        └── the same Docker and CLI layout as above
```

On Fedora, the host is inside the trust boundary. Rootful Docker is
root-equivalent, so a daemon compromise or container escape can become host
root. The container hardening reduces the attack surface but is not a hard
boundary. Use the optional VM or a dedicated server for hostile targets. The
runtime and CLI are identical across all three deployment profiles.

## 3. Components

### 3.1 CLI (`src/haibox/cli/`)

A Typer application. The root callback resolves `Paths`, creates the XDG
directories, loads `config.yaml`, and stores an `AppContext` on the Typer
context. Commands are thin: they validate input, call a service, write an audit
entry, and render output with Rich.

Command groups:

| Group | Responsibility |
|---|---|
| `config` | Write/show the effective configuration |
| `engagement` | Create, list, show, select, archive, destroy |
| `container` | Create/start/stop/restart/remove/inspect/logs |
| `shell`, `run` | Interactive shell and one-off command in the runner |
| `image` | List, inspect, build, verify, scan image definitions |
| `scope` | Show the mounted scope file and evaluate a target |
| `evidence` | Add, list, verify, remove host-side evidence |
| `secret` | Set, list, remove host-only secrets |
| `audit` | Verify and tail the hash chain |
| `vpn` | Store host-only profiles; start/stop a separate gateway |
| `doctor` | Check directories, profiles, endpoint policy, daemon |

### 3.2 Configuration and profiles (`config.py`, `profiles.py`, `models.py`)

`HAIBOXConfig` is a strict Pydantic model (`extra="forbid"`). The default
Docker setting requires a named context other than `default`; a raw `host` is
allowed as an explicit alternative.

Profiles are YAML documents validated by `Profile`. Built-ins ship under
`src/haibox/data/profiles/`; a user profile in `<config_dir>/profiles/`
overrides a built-in with the same name. A profile declares an image, network
mode, resource limits, a capability allowlist, environment, and tool names.

The security-relevant part of a profile is **frozen into the engagement** at
creation (`RuntimeSettings`). Editing a profile later cannot widen an existing
engagement.

### 3.3 Engagement lifecycle (`engagement.py`, `paths.py`)

An engagement is a directory:

```text
<data_dir>/engagements/<id>/
├── engagement.yaml     # frozen metadata, mode 0600
├── scope.json          # mounted read-only at /etc/haibox/scope.json
├── workspace/          # the only writable bind mount
│   ├── notes/
│   ├── scans/
│   ├── loot/
│   └── .home/          # HOME, XDG config/cache
├── evidence/           # host-only
├── reports/            # host-only
├── secrets.json        # host-only, mode 0600
└── audit.jsonl         # host-only hash chain
```

`Paths.engagement_dir` validates every engagement ID before joining it to the
data directory. A tampered `current` pointer cannot escape the data directory.

### 3.4 Scope (`scope.py`)

Scope entries may be IP addresses, CIDR networks, hostnames, wildcard
hostnames, or URLs. Hostnames are **never resolved** by the matcher: an IP
target only matches an IP or CIDR rule, so DNS rebinding cannot silently widen
an engagement. Exclusions always win. If `allowed_ports` is non-empty, a target
without a port is denied (fail closed). A port-specific exclusion also covers a
port-less target, because the matcher cannot prove the eventual port is safe.

The matcher is a policy decision, not an enforcement mechanism. Network-level
enforcement is a separate layer and is not implemented yet (see §7).

### 3.5 Container specification (`runtime/spec.py`)

`ContainerSpec` is a frozen dataclass. Its constructor validates the image,
name, network, UID/GID, resources, capabilities, environment, labels, and mount
paths. `to_create_args()` emits the complete `docker create` argument list:

- `--read-only`, tmpfs `/tmp` and `/run`;
- `--cap-drop ALL`, then an explicit allowlist;
- `--security-opt no-new-privileges:true`;
- `--init`, `--ipc private`, `--restart no`, PID/memory/CPU limits;
- non-root `--user`;
- exactly two bind mounts: the workspace (rw) and the scope file (ro);
- no `--privileged`, `--pid host`, `--device`, `--publish`, or `--volume`.

### 3.6 Runtime seam (`runtime/base.py`, `runtime/docker_cli.py`)

`ContainerRuntime` is a protocol. The manual CLI uses `DockerCli`, which:

- invokes the `docker` binary without a shell;
- always passes an explicit context or host;
- refuses the `default` context by default;
- verifies `haibox.managed=true` before destructive operations;
- re-inspects a container immediately after creation and removes it if its
  security shape differs from the specification;
- redacts credentials from logged commands;
- creates and verifies the separate VPN gateway with a narrower protocol
  surface (`create_vpn_gateway`, `vpn_network_create`, `vpn_network_remove`).

The future broker implements the same protocol, so callers do not depend on the
Docker CLI shape.

### 3.7 Images (`images/`)

Each image definition is a directory with a `Dockerfile` and a `manifest.yaml`.
The manifest pins the base digest, tool versions, build arguments, and a
verification command per tool. `ImageBuilder` validates the manifest, resolves
paths inside the image directory, builds declared local `depends_on` bases in
order, rejects dependency cycles, and passes labels and build arguments to the
runtime. `ImageVerifier` runs the verification script in an ephemeral,
network-isolated, read-only, non-root container. `ImageScanner` is an optional
host adapter for trivy or grype; a missing scanner is an error.

The catalog ships six definitions: `core` (shared base), `network-security`,
`web-security`, `ad-security`, `osint`, and `full`. The Web Security image is
the reference artifact for the scan gate. Core and Network Security are active;
AD Security, OSINT, and Full are built but remain experimental until their
scans are recorded. See [`image-catalog.md`](image-catalog.md).

### 3.8 Host-only stores

- **Audit** (`audit.py`): JSON Lines, each entry hashes the previous hash.
  Tamper-evident, not tamper-proof. The log is created mode 0600 with
  `O_NOFOLLOW`; symlinks are rejected.
- **Evidence** (`evidence.py`): files are copied into the host-only evidence
  directory, hashed with SHA-256, made read-only, and recorded in a manifest.
  Sources that are symlinks (or contain symlinked components) are rejected.
  Copying uses a temporary file and `os.replace`, so the stored hash describes
  the stored bytes.
- **Secrets** (`secrets.py`): a mode-0600 JSON file. Plaintext at rest; the
  MVP relies on host filesystem permissions and does not claim protection
  against a compromised operator account.
- **VPN profiles** (`vpn.py`): `<data_dir>/vpn/<name>/` with `profile.yaml`
  metadata and `vpn.conf`, both mode 0600, inside a mode-0700 directory.
  Symlinks, oversized files, and hook/script directives are rejected. The
  configuration is never printed and is never mounted into an engagement
  runner. The trusted gateway receives it read-only.

## 4. Request flow: create an engagement

```text
operator
  │ haibox engagement init demo --target 10.10.20.5
  ▼
CLI validates arguments
  ▼
EngagementManager.create
  ├── load_profile (built-in or user override)
  ├── freeze RuntimeSettings (uid/gid, caps, env, limits)
  ├── create directories (mode 0700)
  ├── write scope.json (mode 0600)
  ├── write engagement.yaml (mode 0600)
  └── append engagement.created to both audit logs
  ▼
operator
  │ haibox shell
  ▼
container_cmd._ensure_running
  ├── ContainerSpec.from_engagement
  ├── ensure_workspace_ownership
  ├── runtime.create_container
  │     ├── ensure_network (internal, labeled)
  │     ├── docker create ...
  │     └── inspect + verify security shape
  └── runtime.start_container
```

## 5. Data classification

| Data | Location | Mounted into runner? | Protection |
|---|---|---|---|
| Workspace | engagement/workspace | yes, rw | mode 0700, owner UID/GID |
| Scope | engagement/scope.json | yes, ro | mode 0600 |
| Engagement metadata | engagement/engagement.yaml | no | mode 0600 |
| Secrets | engagement/secrets.json | no | mode 0600, plaintext |
| Evidence | engagement/evidence/ | no | files mode 0400, manifest 0600 |
| Reports | engagement/reports/ | no | mode 0700 |
| Audit | engagement/audit.jsonl + logs/audit.jsonl | no | mode 0600, hash chain |

The separate trusted identity for secrets and audit is a planned hardening
step, not part of the current implementation. Today those files are owned by
the operator account that runs the CLI. See ADR-0002.

## 6. Security invariants

These are enforced by code and covered by the unit suite:

1. No privileged container, host network, host PID, host IPC, or devices.
2. `--cap-drop ALL` with only `NET_RAW` and `NET_BIND_SERVICE` permitted.
3. `no-new-privileges:true` and a read-only root filesystem.
4. A non-root UID/GID recorded at creation.
5. Exactly two bind mounts; only the workspace is writable.
6. Host-only data is never mounted.
7. Destructive operations require the managed label.
8. The Docker `default` context is refused unless explicitly overridden.
9. Engagement IDs cannot traverse outside the data directory.
10. Scope matching fails closed.
11. The default network profile is `isolated`; a reused network without both
    gateway modes set to `isolated`, or with a host gateway, is refused.

### 6.1 Prototype-only GUI session invariants

The optional Xpra GUI is a disposable prototype documented in
[ADR-0011](adr/0011-gui-session-in-existing-runner.md). It is not part of the
product: there is no `haibox gui` command, no `ContainerSpec` field, and no
catalog image. While the prototype exists, these invariants hold:

12. A GUI session is refused unless the engagement uses the `isolated` network
    profile with an empty target scope, the engagement metadata matches the
    canonical scope file, and the container is attached to exactly the
    engagement network.
13. A GUI session is never replaced before the previous server is confirmed
    terminated. The `xpra stop` exit code is advisory only; termination is
    confirmed by a bounded inspection of the container. An ambiguous result is
    a refusal, and the credential, the runtime, and the server are left
    untouched.
14. An Xpra server on the same display that does not belong to the engagement
    is reported and never signalled.
15. The GUI transport is a Unix-domain socket in an owner-controlled 0700
    directory, and the session credential is a mode-0600 file that is rotated
    on every prepare and removed on stop.

## 7. Known gaps

- **Network enforcement is incomplete.** The default `isolated` profile
  removes the host address from the engagement bridge, so runners cannot reach
  host services, the host LAN, public internet, or external DNS. The platform
  still does not install a scope-aware default-deny policy for allowed lab
  targets, redirects, or VPN disconnection, and the scope matcher is not
  consulted by the network layer. The legacy `internal` profile was removed in
  ADR-0009 because it kept the host gateway reachable.
- **Docker is root-equivalent.** The operator in the `docker` group can control
  the daemon. On Fedora the host is therefore inside the trust boundary. The
  optional VM or a dedicated server is the mitigation for hostile targets.
- **Secrets are plaintext** and share the operator identity.
- **Audit is tamper-evident, not tamper-proof.**
- **No image signing or SBOM.** Build pins and labels exist; provenance does
  not.
- **No disk quota** on the workspace.
- **No AI broker.** It remains deferred until a restricted broker exists.
- **VPN routing is not implemented.** Host-only profile storage and a separate
  gateway lifecycle exist, but the gateway image is not built and runner
  traffic is not routed through it. Transparent routing and the kill switch
  require negative tests before they can be claimed.
- **No public name.** "HAIBOX" is a temporary internal codename.

## 8. Deferred components

### AI broker

A separate process implementing `ContainerRuntime` over a narrow RPC. It will
run as a different identity, expose only allowlisted operations, use a separate
runner container and workspace, and never expose the Docker socket. The manual
lane remains independent.

### VPN gateway

A dedicated trusted container or network namespace that owns the tunnel.
Profiles are stored host-only and mounted read-only into the gateway, never
into the runner. The gateway may receive `NET_ADMIN` and `/dev/net/tun`; the
runner never does. Engagement runners attach to an internal network whose only
route is the gateway. If the tunnel drops, the gateway removes the route;
runners have no fallback path. Kill-switch behaviour must be tested, not
assumed. See ADR-0007.

### Default-deny network policy

A per-engagement policy applied on the Docker host (nftables) and inside the
runner (no NET_ADMIN). It must cover:

- host services (including the Docker API and the host's own services);
- the bridge gateway and link-local metadata addresses;
- DNS (both Docker's embedded resolver and external resolvers);
- IPv4 and IPv6;
- ICMP redirects and other route-changing messages;
- VPN disconnection and reconnection;
- target scope, including port-specific rules.

The scope JSON is the intended source of truth, but enforcement must be
independent of the tools running inside the container.
