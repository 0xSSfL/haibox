# HAIBOX

**Working title.** An independent, isolation-first penetration-testing platform.

HAIBOX is not an Exegol installation, wrapper, or fork. It is a from-scratch
platform with its own Python CLI, container specification, image build system,
engagement model, evidence store, audit log, and (later) VPN and AI adapters.
The public Exegol documentation is used only as a capability comparison; no
Exegol source or proprietary implementation is copied.

> **Status: working source foundation with validated runtime images.** The unit
> suite, lint, and type checks pass on Fedora. All six catalog images build,
> verify, and have recorded Trivy scan baselines; the vulnerability scan gate
> remains open on dependency findings (Debian 13 base packages and pinned Go tool
> modules). Direct Docker on Fedora is the primary development and runtime
> target; a KVM VM is optional. VPN profile storage and a separate gateway
> lifecycle exist; transparent routing and the kill switch do not. The
> restricted Docker broker, AI adapter, and GUI are not implemented. See
> [`docs/roadmap.md`](docs/roadmap.md),
> [`docs/image-catalog.md`](docs/image-catalog.md), and
> [`docs/host-docker-review.md`](docs/host-docker-review.md).

## Why a separate platform

The earlier `~/Work/pentest-lab` audit found that the Fedora laptop is a
general-purpose host: it runs unrelated services, the operator is in `wheel`
and `docker`, and the Bubblewrap sandbox shares the host network namespace.
HAIBOX is a from-scratch platform that keeps its own resource names, networks,
workspaces, and audit trail instead of inheriting another project's layout.

HAIBOX assumes:

- the Docker runtime runs on Fedora during development, or on a dedicated Linux
  server for production; a KVM VM is an optional high-assurance deployment;
- the manual operator is the only identity with Docker access;
- an engagement container is untrusted and may be compromised by a target;
- the AI lane, when added, gets a narrow broker API, never the Docker socket;
- rootful Docker is root-equivalent, so the host is inside the trust boundary
  unless the optional VM or a dedicated server is used.

## Verification status

| Check | Status |
|---|---|
| `uv sync --extra dev` | Passed on Fedora, 2026-11-03 |
| `pytest` (unit, fake runtime) | 238 passed, 2 skipped, 2026-11-09 |
| `ruff check .` | Passed, 2026-11-09 |
| `mypy src` | Passed, 2026-11-09 |
| `haibox` CLI invocation | `version`, `init`, `doctor`, `info`, `tui` passed on Fedora, 2026-11-09 |
| Docker context `haibox` | Created; client/server 29.9.2, rechecked 2026-11-08 |
| Docker integration smoke test | Passed with the final image: 2 passed, 2026-11-09 |
| Runner network probe (isolated profile) | Manual probe: no default route, no global IPv6, external DNS fails, metadata unreachable, host LAN SSH/PostgreSQL, host bridges, and public IPv4/IPv6 unreachable; container-to-container works, 2026-11-08 |
| `haibox vpn` profile CLI | `add`, `list`, `show`, `status` passed on Fedora, 2026-11-03 |
| `haibox vpn up` without gateway image | Fails cleanly with exit 1 and no traceback, 2026-11-03 |
| VPN gateway lifecycle | Not run; `haibox/vpn-gateway:0.1.0` is not built |
| Web Security image build & verify | Passed; digest `sha256:5dfddb51…520b9aa`, 15 pinned tools verified, 2026-11-08 |
| Core image build & verify | Passed; digest `sha256:962ce703…d68c5fc`, 18 pinned tools verified, 2026-11-09 |
| Network Security build & verify | Passed; digest `sha256:75a634b4…effcd3`, 12 pinned tools verified, 2026-11-09 |
| Active Directory build & verify | Passed; digest `sha256:8cef90b5…effaf3d9`, 5 pinned tools verified, 2026-11-09 |
| OSINT image build & verify | Passed; digest `sha256:baf53815…c000d3c5`, 6 pinned tools verified, 2026-11-09 |
| Full image build & verify | Passed; digest `sha256:bfac7833…be69dd2b`, 31 pinned tools verified, 2026-11-09 |
| Catalog vulnerability scans (Trivy) | Baselines recorded for all 6 variants; gate open on dependency findings (Debian 13 base packages and pinned Go modules), 2026-11-09 |
| Trivy suppression scope check | **Passed** for `web-security`, `osint`, and `full`: all removed secret findings matched declared path/rule scopes, 2026-11-09 |
| `haibox info` / interactive menu | `info` (table and JSON) and `tui` smoke-tested, 2026-11-09 |
| KVM VM | Optional; not created |

The table is intentionally blunt. Do not treat a source-level feature as
working until the corresponding row has a recorded result.

## What exists in source

| Capability | State |
|---|---|
| Python CLI (`haibox`) | `version`, `init`, `doctor`, `info`, `tui` verified on Fedora; colour/quiet/JSON/confirmation options |
| Interactive menu (TUI) | Implemented as a dispatcher over the same Typer commands; smoke-tested |
| Engagement directories and scope files | Implemented; unit tests pass |
| Deny-by-default container specification | Implemented; unit and smoke tests pass |
| Docker CLI runtime with managed-label checks | Implemented; unit and smoke tests pass |
| Interactive shell and one-off command execution | Implemented; runtime validation in progress |
| Per-engagement persistent workspace | Implemented; smoke-tested |
| Host-side hash-chained audit log | Implemented; unit tests pass |
| Host-only secret store | Implemented; plaintext at rest |
| Host-only evidence store with SHA-256 manifests | Implemented; unit tests pass |
| Web Security Dockerfile + pinned tool manifest | Built and verified; scan gate open on dependency findings |
| Image build/verify/scan adapters | Implemented; Docker/scanner required |
| Core / Network Security images | Built and verified; Core is the shared base |
| Active Directory image | Built and verified; experimental profile |
| OSINT image | Built and verified; experimental profile |
| Full image | Built and verified; experimental combined profile |
| Dependency-aware image builds | Implemented; `depends_on` builds local bases in order and rejects cycles |
| VPN profile store and gateway lifecycle | Implemented; gateway image not built |
| Transparent VPN routing and kill switch | Not implemented |
| Restricted Docker broker + AI adapter | Not implemented |
| GUI / desktop | Not implemented |

## Security model in one page

- One container per engagement, on a per-engagement **internal bridge network**
  with Docker's `isolated` gateway mode (`network.profile: isolated`, the
  default). The host has no address on that bridge.
- `--cap-drop ALL`; only `NET_RAW` or `NET_BIND_SERVICE` can be enabled by a
  profile.
- `--security-opt no-new-privileges:true`.
- Read-only root filesystem, with `tmpfs` for `/tmp` and `/run`.
- Non-root container user; UID/GID recorded at engagement creation.
- No `--privileged`, no host network, no host PID/IPC, no devices.
- The only writable bind mount is the engagement workspace.
- The scope file is mounted read-only; secrets, evidence, reports, and audit
  logs are **not** mounted.
- Destructive operations verify the `haibox.managed=true` label before acting.
- The CLI refuses the Docker `default` context by default; configure a named
  `haibox` context that points at the local socket or a dedicated server.
- HAIBOX does not change the Docker daemon, Fedora firewall, SELinux policy,
  or unrelated projects.
- Every Docker invocation and every engagement command is appended to a
  hash-chained audit log.

**Important limitation:** scope is not enforced at the network layer yet. The
scope matcher and the read-only scope file are policy inputs; a tool can still
attempt out-of-scope traffic on its bridge. The default `isolated` profile
removes the host address from the engagement bridge, so runners cannot reach
host services, the host LAN, public internet, or external DNS. The legacy
`internal` profile has been removed; a configuration that requests it fails
validation. A future `scoped` connectivity profile (ADR-0010) is the planned
way to reach authorized external targets. See
[`docs/threat-model.md`](docs/threat-model.md),
[`docs/host-docker-review.md`](docs/host-docker-review.md), ADR-0003,
ADR-0008, and ADR-0009.

## Quick start (Fedora or a dedicated Linux server)

Review [`docs/host-docker-review.md`](docs/host-docker-review.md) before the
first Docker workload. HAIBOX uses client-side Docker contexts and does not
change the daemon, firewall, or SELinux policy.

```bash
# 1. Install the CLI in a project venv
uv sync --extra dev

# 2. Create a dedicated client-side context.
#    On Fedora this points at the local Docker socket. On a server, replace the
#    endpoint with the reviewed remote Docker endpoint.
docker context create haibox --docker host=unix:///var/run/docker.sock

# 3. Initialise HAIBOX and check the environment
uv run haibox init
uv run haibox doctor

# 4. Build the Web Security image (requires network at build time)
uv run haibox image build web-security

# 5. Create an engagement and open a shell
uv run haibox engagement init demo \
  --name "Demo engagement" \
  --profile web-security \
  --target 10.10.20.5 \
  --allowed-port 443

uv run haibox shell
```

The optional KVM deployment is documented in
[`docs/runbooks/kvm-vm-setup.md`](docs/runbooks/kvm-vm-setup.md). It is not a
prerequisite.

Inside the shell, the workspace is `/workspace`; the read-only scope file is
`/etc/haibox/scope.json`. The host-side workspace is under
`~/.local/share/haibox/engagements/<id>/workspace`.

## CLI overview

```text
haibox init
haibox doctor [--json]
haibox info [--json]
haibox tui
haibox version

haibox engagement init|list|show|use|current|archive|destroy
haibox shell
haibox run -- <command...>
haibox container create|start|stop|restart|rm|ps|inspect|logs
haibox image list|build|inspect|verify|scan
haibox scope show|check
haibox evidence add|list|verify|rm
haibox secret set|list|rm
haibox audit verify|tail
haibox vpn add|list|show|remove|up|down|status
haibox config init|show|path
```

`haibox vpn add` stores a WireGuard or OpenVPN configuration host-only under
`~/.local/share/haibox/vpn/<name>/`, with mode `0600`; the contents are never
printed and never mounted into an engagement runner. `haibox vpn up` starts a
separate trusted gateway container with `NET_ADMIN` and `/dev/net/tun`, but the
gateway image is not built yet and **no runner traffic is routed through it**.
Transparent routing and the kill switch remain unimplemented.

### Network profile

`config.yaml` selects the engagement network profile:

```yaml
network:
  profile: isolated   # default
```

`isolated` creates an internal bridge with Docker's `isolated` gateway mode and
requires Docker 28.0.0 or newer. The host has no address on the bridge, so
runners cannot reach host services, the host LAN, public internet, or external
DNS; container-to-container traffic on the same engagement still works. HAIBOX
refuses to reuse a network that is not internal, is missing both `isolated`
gateway modes, or still reports a host gateway.

`internal` is no longer accepted. It kept the host gateway reachable, so a
configuration that still requests it fails validation. Networks created by
older HAIBOX versions must be removed and recreated to pick up `isolated`.
Authorized external targets are planned through a separate `scoped`
connectivity profile (ADR-0010), not through a host gateway.

## Repository layout

```text
src/haibox/          Python package
  cli/                Typer commands
  runtime/            ContainerRuntime protocol + Docker CLI implementation
  images/             image build, verify, scan adapters
  data/profiles/      built-in profiles
images/               independent Dockerfiles and tool manifests
profiles/             documentation pointer for built-in profiles
tests/                unit tests and opt-in integration tests
docs/                 architecture, threat model, roadmap, ADRs, runbooks
scripts/              build/verify convenience scripts
```

## Development

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy src
```

Unit tests use a fake runtime and never touch Docker. Integration tests are
opt-in and require a dedicated Docker context; see
[`tests/integration/README.md`](tests/integration/README.md).

## What this milestone deliberately does not do

- It does not require or create a KVM VM. The VM runbook is optional.
- It does not change the Docker daemon, Fedora firewall, SELinux policy, or
  unrelated projects.
- It does not install host packages automatically.
- It does not expose a Docker socket to an AI.
- It does not enforce scope at the network layer yet.
- It does not use a separate trusted identity for secrets and audit yet.
- It does not claim that VPN kill-switch or transparent routing is complete
  before the negative tests pass.
- It does not claim to be production-ready.

## Documentation

- [User guide](docs/user-guide.md)
- [Architecture](docs/architecture.md)
- [Threat model](docs/threat-model.md)
- [Host Docker review](docs/host-docker-review.md)
- [Image catalog](docs/image-catalog.md)
- [Image validation](docs/image-validation.md)
- [Vulnerability risk register](docs/vulnerability-risk-register.md)
- [Roadmap](docs/roadmap.md)
- [Feature comparison](docs/feature-comparison.md)
- [ADRs](docs/adr/)
- [Optional KVM VM runbook](docs/runbooks/kvm-vm-setup.md)

## License

MIT. See [`LICENSE`](LICENSE).
