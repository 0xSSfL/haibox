# ADR-0002: Host-only data and a separate vault identity

- Status: Accepted; the separate identity is not implemented yet
- Date: 2026-11-02

## Context

Secrets, evidence, reports, and audit logs are the most sensitive data the
platform handles. A runner may be compromised by a target. If any of this data
is mounted into the runner, or owned by the same identity that runs the runner,
the compromise extends to the client's findings and credentials.

## Decision

1. Secrets, evidence, reports, and audit logs live on the host and are **never**
   mounted into an engagement container. Only the workspace (rw) and the scope
   file (ro) are mounted.
2. Evidence files are copied out of the workspace, hashed, made read-only, and
   recorded in a host-only manifest.
3. The audit log is a hash chain and is stored host-only.
4. The target design uses a separate trusted identity (`haibox-vault`) that
   owns the private data directory. The operator's CLI accesses it through a
   narrow helper or broker, not by sharing the identity.
5. Until the vault identity exists, the MVP stores the files under the
   operator's engagement directory with mode 0600 and documents the gap.

## Consequences

- The MVP does not yet meet the separate-identity requirement. This is a known
  gap, not an implied guarantee.
- A host user with write access can rewrite evidence and the audit chain. The
  hash chain makes tampering evident, not impossible.
- Off-VM, append-only backup is required for real assurance.
- The future broker and vault helper must not become a path for a runner to
  read secrets.

## Alternatives considered

- **Mount a read-only secrets file into the runner.** Rejected: a compromised
  runner could read it, and read-only does not prevent disclosure.
- **Use Docker secrets.** Docker secrets are designed for swarm services and
  still place the value inside the container. Rejected for the same reason.
- **Encrypt with a key stored on the same host.** Adds complexity without
  protecting against a host compromise. A hardware token or external KMS is a
  later option.
