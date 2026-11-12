# Roadmap

The roadmap is ordered by security dependency, not by feature visibility. A
later milestone may not weaken an earlier invariant.

## M0 — Source foundation (complete)

**Goal:** a coherent, reviewable source tree with a local test baseline.

Delivered:

- package layout, `pyproject.toml`, entry point `haibox`;
- Typer CLI with config, engagement, container, execution, image, scope,
  evidence, secret, audit, and VPN commands;
- strict Pydantic models and built-in profiles;
- `ContainerRuntime` protocol and Docker CLI adapter;
- deny-by-default `ContainerSpec` with post-create verification;
- scope matcher with fail-closed port behaviour;
- host-only evidence, secret, and hash-chained audit stores;
- Web Security image definition and pinned manifest;
- unit tests with a fake runtime; opt-in integration test;
- architecture, threat model, ADRs, and host review;
- `uv sync --extra dev`, `pytest`, `ruff`, and `mypy` passing on Fedora.

**Not yet done:**

- no project image has been built;
- the Web Security image has not been verified or scanned.

**Exit criteria:** met: the unit suite, lint, and type checks pass locally.

## M1 — First runtime validation (complete)

**Goal:** prove the source works against a real Docker endpoint.

- [x] create the client-side `haibox` Docker context;
- [x] run `haibox version`, `init`, and `doctor`;
- [x] build and verify `web-security` (Debian 13, 2026-11-08);
- [x] run the opt-in Docker smoke test with an existing image;
- [x] default engagement networks to Docker's `isolated` gateway mode and
      verify host-service, LAN, internet, DNS, and metadata denial;
- [x] remove the legacy `internal` network profile (ADR-0009);
- [x] add an opt-in integration test that makes real connection attempts;
- [x] record the security checklist results;
- [x] add a dependency-aware image catalog (`core`, `network-security`,
      `web-security`, `ad-security`, `osint`, `full`);
- [x] add the full CLI/TUI/colour/JSON/confirmation surface;
- [x] build and scan every catalog image variant (`core`, `network-security`,
      `web-security`, `ad-security`, `osint`, `full`);
- [ ] make the Trivy HIGH/CRITICAL scan gate green (blocked on upstream Debian/Go dependency fixes);
- [ ] optionally repeat on the KVM VM or dedicated server.

**Exit criteria:** met for runtime verification; image digest and scan reports
are recorded in `README.md`, [`docs/image-validation.md`](image-validation.md),
and [`docs/vulnerability-risk-register.md`](vulnerability-risk-register.md).
Dependency remediation remains tracked as an ongoing gate blocker.

Status on 2026-11-09: build, `image verify`, both integration tests, the network
probe, the suppression-scope check, the CLI/TUI smoke tests, and the Trivy
vulnerability baselines for all six catalog images (`core`, `network-security`,
`web-security`, `ad-security`, `osint`, `full`) are recorded. `haibox image scan`
fails the release gate on dependency findings (Debian 13 base packages and pinned
Go tool modules). All reports and digests are recorded in
[`docs/image-validation.md`](image-validation.md) and
[`docs/vulnerability-risk-register.md`](vulnerability-risk-register.md). M1
verification tasks are complete; the remaining scan gate blocker is dependency
remediation (newer Debian packages and newer pinned Go tool releases).

The CRITICAL findings across the catalog are:

- `CVE-2026-118264` in `github.com/labstack/echo/v4` inside `dalfox`
  (`v4.15.2`, fixed `4.16.1` in `web-security`, `osint`, `full`);
- `CVE-2026-33815` and `CVE-2026-33816` in `github.com/jackc/pgx/v5` inside
  `katana` (`v5.7.2`, fixed `5.9.0` in `web-security`, `osint`, `full`);
- `CVE-2019-16224`, `CVE-2019-16225`, and `CVE-2019-16227` in Debian `liblmdb0`
  (pulled into `network-security` by `knot-dnsutils` and into `ad-security` by
  `samba-common-bin`, inherited by `full`);
- `CVE-2026-6653` in Debian `libxml2` (pulled into `ad-security` by
  `samba-common-bin`, inherited by `full`).

The 162 HIGH findings are concentrated in the Debian base (`python3.13`,
`util-linux`, `libexpat1`, `libsqlite3-0`, `curl`, `libpcap0.8t64`, `libacl1`)
and in Go modules embedded by the latest upstream releases (`golang.org/x/net`,
`golang.org/x/crypto`, `echo`, `kin-openapi`, `x/mod`, `x/text`,
`klauspost/compress`, `pgx`, `grpc`, `go-git`, `go-jose`). They are analysed in
[`vulnerability-risk-register.md`](vulnerability-risk-register.md) and are not
suppressed.

## M2 — Scope enforcement and trusted storage (current)

**Goal:** turn the advisory scope into an enforced policy and separate the
vault identity.

Host-service isolation is now the default network profile: the isolated gateway
profile removes the host address from the engagement bridge, and ADR-0009
removed the legacy `internal` profile. M2 adds scope-aware control over the
authorized lab-target path (ADR-0010 `scoped` connectivity profile) and
hardens trusted storage.

- [x] implement a per-engagement nftables policy engine (`inet haibox-<id>`) with
      stateful forward filtering, fail-closed drop policy, and clean teardown;
- [x] wire the scope file into the policy (IPv4/IPv6 CIDR/address allowlist,
      exclusions with strict precedence over allowlist, port-specific rules);
- [x] default-deny out-of-scope traffic, cloud metadata (`169.254.169.254`),
      loopback (`127.0.0.0/8`, `::1`), and link-local ranges;
- [x] unit test ruleset compilation, dual-stack CIDRs, exclusion precedence, and
      the `apply`/`remove` lifecycle with `CommandRunner`;
- [x] wire policy generation and enforcement into the runtime network creation
      and cleanup paths;
      *Hardened (2026-11-10):* `DockerCli.create_container` applies the policy
      for the `scoped` profile and `network_remove` removes it before deleting
      the network. Re-applying the ruleset flushes and replaces it, a missing
      bridge aborts container creation, cleanup errors propagate, and the
      profile comes from the engagement snapshot instead of the global
      `network.profile` setting. Unit-tested with the scripted runner; no
      negative integration test yet.
- [ ] implement the `scoped` connectivity profile and policy gateway container
      (ADR-0010);
      *Partial (2026-11-10):* the `scoped` profile and a non-internal bridge
      exist and the per-container policy is applied. There is no policy gateway
      container; runners still receive a host gateway address and the nftables
      forward chain does not filter the host input path (bridge gateway, host
      services) or Docker's embedded DNS.
- [ ] add negative integration tests proving a runner cannot bypass scope even
      when a tool ignores the scope file;
- [ ] create a separate `haibox-vault` identity for secrets and audit (ADR-0002);
- [ ] add an append-only off-VM audit/evidence sink;
- [ ] add workspace disk quotas (XFS project quotas or Docker storage-opt).

**Exit criteria:** the threat-model checklist passes with enforcement enabled;
a runner cannot reach an out-of-scope address even when the tool ignores the
scope file.

## M3 — Manual lane hardening

**Goal:** a comfortable, auditable manual workflow.

- scope editing commands and validation (`haibox scope edit`, `validate`, `diff`);
- engagement export/import and archive format (`haibox engagement export/import`);
- report scaffolding and Markdown/PDF synthesis;
- evidence tagging, checksum verification, and full-text search;
- container health checks, uptime monitoring, and live resource metrics;
- backup and restore runbooks for host-side state;
- key rotation and migration for the vault identity.

**Exit criteria:** complete engagement lifecycle can be executed, archived,
restored, and verified on a clean workstation without manual database or file
surgery.

## M4 — Restricted AI broker

**Goal:** add an AI lane without giving it the Docker socket.

- broker service implementing `ContainerRuntime` over a narrow RPC;
- separate AI runner image, workspace, network, and identity;
- allowlisted operations, per-engagement quotas, and full audit;
- scope enforcement independent of the model;
- prompt-injection-resistant tool-output handling;
- manual lane remains fully functional with the broker disabled.

**Exit criteria:** the AI cannot create a privileged container, publish a port,
mount a host path, read a secret, or reach another engagement; every AI action
is attributable in the audit log.

## M5 — VPN gateway

**Goal:** safe external engagements.

- host-only VPN profile store and CLI (done, unit-tested);
- separate gateway specification and lifecycle (done, unit-tested);
- gateway image definition (`haibox/vpn-gateway`);
- WireGuard and OpenVPN adapters;
- runner attachment to the gateway;
- kill switch on tunnel loss, DNS leak prevention, IPv6 handling;
- provider registry (generic WireGuard/OpenVPN first; commercial providers
  only after their terms are reviewed);
- tests for disconnect, reconnect, and route fallback.

**Exit criteria:** tunnel drops immediately sever all runner egress; zero
packets leak to the local LAN or host default route; DNS resolves exclusively
through the tunnel.

## M6 — Packaging and release

**Goal:** reproducible distribution.

- signed image builds and SBOM attestations (Cosign / in-toto);
- lockfile committed and audited;
- standalone binary packaging (pex / PyInstaller / RPM) and install tests;
- semantic versioning and automated changelog generation;
- public name decision, logo, and branding finalization;
- independent security review before any public release.

**Exit criteria:** reproducible builds verified from clean source clone; signed
artifacts verify against public key; end-to-end installation test passes on
Fedora and Debian.

## M7 — Desktop / GUI (optional)

A thin client over the same CLI and broker interfaces. It must not add a new
privileged path.

**Current state (2026-11-11):** design review and readiness prototype only.
[ADR-0011](adr/0011-gui-session-in-existing-runner.md) chooses the existing
GUI-enabled runner over a per-engagement sidecar and fixes an engagement-bound
Unix-socket relay, independent Xpra file authentication, deny-by-default
forwarding, and isolated-network restriction. The prototype passed Fedora 44 X11
and headless-Wayland display/surface tests, plus authentication,
cross-engagement, concurrency, detach, stop, and cleanup negatives. It did not
pass the image vulnerability gate: Grype covers Fedora 44 but reports 4
CRITICAL and 61 HIGH findings. A 2026-11-12 hardening pass added fail-closed
isolated/empty-scope preflight, canonical scope-file comparison, exact network
membership checks, private password and socket directories, credential rotation
and removal, bounded relay cleanup, and a verified session replacement that
refuses to reset the runtime, replace the credential, or start a second server
until the previous server is confirmed gone. The hardened scripts were re-run on
a disposable real Docker endpoint with 64 fake-runtime regressions covering the
same paths.

**Program (2026-11-12):** the GUI production program runs in
[phases](superpowers/plans/2026-11-12-gui-production-program.md) — image
security and vulnerability remediation first, then the production runtime in
`src/haibox/gui/`, then the CLI, desktop compatibility, adversarial testing,
and an independent acceptance review. The baseline is `main` at `73aa4cf` with
`make check` at 392 passed and 2 skipped. The image gate stays closed and no
GUI command ships until it is resolved.

**Not started:**

- `haibox gui start|attach|stop|status` commands, audit events, and tests;
- `ContainerSpec` GUI fields or a supported GUI runtime seam;
- the rebuild of the GUI image on the Fedora 46 stable release (the candidate
  image scans clean but its base is still a pre-release snapshot);
- hostile-stream testing, resource limits, and a host-client version matrix;
- a real Fedora Workstation Wayland input test;
- Debian packaging and host-client distribution.

**Exit criteria:** the image gate is open, the relay and session lifecycle are
product code with negative integration tests, GUI refuses non-isolated networks
and external scopes, and the host-client matrix (X11 and Wayland) is recorded.

## Deferred indefinitely

- Windows and macOS runners;
- Kubernetes deployment;
- multi-tenant SaaS;
- automatic exploitation or lateral movement;
- any feature that requires mounting the Docker socket into a runner.
