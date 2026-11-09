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

## M1 — First runtime validation (current)

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

**Exit criteria:** all commands pass; the image digest and scan report are
recorded; the smoke test and checklist results are recorded in `README.md`.

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

## M2 — Scope enforcement and trusted storage

**Goal:** turn the advisory scope into an enforced policy and separate the
vault identity.

Host-service isolation is now the default and the only network profile: the
isolated gateway profile removes the host address from the engagement bridge,
and ADR-0009 removed the legacy `internal` profile. M2 adds scope-aware
control over the authorized lab-target path; ADR-0010 describes the planned
separate `scoped` connectivity profile.

- implement a per-engagement nftables or equivalent policy for the engagement
  bridge;
- wire the scope file into the policy (address/port allowlist and exclusions);
- default-deny out-of-scope traffic to lab targets, redirects, and DNS;
- add negative tests for each bypass path;
- create a separate `haibox-vault` identity for secrets and audit;
- add an append-only off-VM audit/evidence sink;
- add a workspace disk quota.

**Exit criteria:** the threat-model checklist passes with enforcement enabled;
a runner cannot reach an out-of-scope address even when the tool ignores the
scope file.

## M3 — Manual lane hardening

**Goal:** a comfortable, auditable manual workflow.

- scope editing commands and validation;
- engagement export/import and archive format;
- report scaffolding;
- evidence tagging and search;
- container health checks and resource usage;
- backup/restore runbook;
- key rotation for the vault identity.

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
- gateway image definition (not built);
- WireGuard and OpenVPN adapters;
- runner attachment to the gateway (not implemented);
- kill switch on tunnel loss, DNS leak prevention, IPv6 handling;
- provider registry (generic WireGuard/OpenVPN first; commercial providers
  only after their terms are reviewed);
- tests for disconnect, reconnect, and route fallback.

## M6 — Packaging and release

**Goal:** reproducible distribution.

- signed image builds and SBOM attestations;
- lockfile committed and audited;
- package build and install test;
- versioning and changelog;
- public name decision and branding;
- security review before any public release.

## M7 — Desktop / GUI (optional)

A thin client over the same CLI and broker interfaces. It must not add a new
privileged path.

## Deferred indefinitely

- Windows and macOS runners;
- Kubernetes deployment;
- multi-tenant SaaS;
- automatic exploitation or lateral movement;
- any feature that requires mounting the Docker socket into a runner.
