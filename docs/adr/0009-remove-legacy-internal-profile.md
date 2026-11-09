# ADR-0009: Remove the legacy internal network profile

- Status: Accepted
- Date: 2026-11-08
- Supersedes: ADR-0008 decision 3 and its rollback section
- Related: ADR-0003 (scope enforcement), ADR-0008 (isolated gateway mode)

## Context

ADR-0008 introduced Docker's `isolated` gateway mode as the default engagement
network profile and kept the old `--internal` behaviour as an explicit opt-in
(`network.profile: internal`). A probe on 2026-11-08 confirmed that the legacy
profile still assigns the host an address on the engagement bridge and that a
runner can reach TCP/22 on it, where the Fedora host SSH daemon listens on
`0.0.0.0:22`.

Leaving that profile available makes it possible for an ordinary configuration
mistake to reopen host-service access. The first milestone must not ship a
documented switch that defeats its own isolation invariant.

## Decision

1. **`isolated` is the only accepted network profile.** The `NetworkProfile`
   type and `NetworkSettings` model accept only `isolated`.
2. **Legacy configurations fail closed.** A configuration containing
   `network.profile: internal` fails validation with a clear error instead of
   creating a host-reachable bridge.
3. **The runtime always applies and verifies the isolated options.** There is
   no branch that omits the gateway-mode options, and every reused network must
   report both modes as `isolated` with no IPAM gateway.
4. **Existing legacy networks are refused.** Operators must remove and
   recreate them; HAIBOX does not silently reuse or "fix" them.
5. **No replacement escape hatch is added in this milestone.** A future scoped
   connectivity profile (ADR-0010) is the supported way to reach authorized
   external targets.

## Consequences

- A configuration that previously used `internal` stops working until the
  profile line is removed or set to `isolated`.
- Engagement networks created before this change are refused until recreated.
- Host-service isolation no longer depends on the operator choosing the safe
  profile; it is the only profile.
- The isolated profile still does not enforce target scope. That remains
  ADR-0003 work and is why ADR-0010 is deferred.

## Alternatives considered

- **Keep `internal` behind an environment variable.** Rejected: it preserves a
  normal-use path to host SSH and adds a bypass that is hard to audit.
- **Warn but allow `internal`.** Rejected: a warning does not prevent the
  exposure and makes the security invariant advisory.
- **Add nftables rules instead.** Rejected for this milestone: it changes
  host-global state and is not required to remove the unsafe profile.

## Rollback

There is no supported rollback to the legacy profile. If host-service access
is required for a specific deployment, use a separate, reviewed connectivity
design (ADR-0010) rather than restoring the old bridge behaviour.
