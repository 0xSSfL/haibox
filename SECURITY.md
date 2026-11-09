# Security policy

## Intended use

HAIBOX is a controlled penetration-testing platform. Use it only against
systems for which you have explicit, written authorization. The platform does
not grant authorization and cannot enforce the legal scope of an engagement.

## Deployment boundary

HAIBOX runs directly on Fedora through Docker during development, or on a
dedicated Linux server for production. A KVM VM is an optional high-assurance
deployment, not a requirement.

Direct Docker on a workstation places the host inside the trust boundary.
Rootful Docker is root-equivalent, and the operator's membership in the
`docker` group grants daemon control. The container hardening reduces the
attack surface but is not a hard security boundary. For hostile targets or
untrusted tooling, use the optional VM or a dedicated server.

Review `docs/host-docker-review.md` before the first Docker workload. HAIBOX
does not change the Docker daemon, the Fedora firewall, SELinux policy, or
unrelated projects.

## Implementation status

The unit suite, lint, and type checks pass on Fedora. Docker workloads are
being validated. The following gaps are known and must not be described as
solved:

- scope is **not** enforced at the network layer; the matcher is advisory;
- the default network profile blocks host services, the host LAN, public
  internet, and external DNS, but it does not restrict which authorized lab
  targets on the engagement bridge a tool may contact;
- secrets are plaintext and share the operator identity;
- audit and evidence are tamper-evident, not tamper-proof;
- no separate trusted identity for secrets and audit exists yet;
- no image signing, SBOM, or reproducible-build proof exists;
- no workspace disk quota exists;
- VPN profile storage is in progress; transparent routing and the kill switch
  do not exist yet;
- no AI broker exists.

## Reporting a vulnerability

Do not open a public issue for a vulnerability that could weaken isolation.
Send a private report to the maintainers with:

- affected version and commit;
- a minimal reproduction;
- the security boundary you believe is crossed;
- whether the issue affects the CLI, the container specification, the image,
  the audit log, or the evidence store.

## Security invariants

The following are product invariants, not optional hardening:

- no `--privileged` containers;
- no host network mode;
- no Docker socket inside an engagement container;
- no arbitrary host bind mounts;
- a non-root container user;
- `--cap-drop ALL`, with a small explicit capability allowlist;
- `no-new-privileges:true`;
- a read-only container root filesystem;
- per-engagement workspace and network;
- the default engagement network uses Docker's `isolated` gateway mode, so the
  host has no address on the bridge; a reused network without both isolated
  gateway modes, or with a host gateway, is refused;
- the legacy `internal` network profile has been removed; a configuration that
  requests it fails validation instead of exposing the host gateway;
- evidence, reports, and secrets are host-only and are never mounted into the
  engagement container;
- destructive operations refuse containers and networks that do not carry the
  HAIBOX managed label;
- engagement IDs cannot traverse outside the data directory;
- scope matching fails closed.

A change that weakens any of these invariants requires an ADR and a security
review. A change that claims to enforce scope at the network layer must include
negative tests for host services, gateways, DNS, redirects, IPv4/IPv6, and VPN
disconnection.
