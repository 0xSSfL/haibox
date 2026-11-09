# ADR-0010: Scoped connectivity profile for authorized external targets

- Status: Proposed; not implemented in M1
- Date: 2026-11-08
- Related: ADR-0003 (scope enforcement), ADR-0007 (VPN scope), ADR-0009

## Context

The default engagement network is intentionally isolated: it has no default
route, no host gateway, no external DNS, and no public internet. That is the
correct default for the first Docker workstation milestone, but it means a
runner cannot reach an authorized external target (a client staging host, a
VPN-only range, or an internet-facing asset listed in scope).

Opening unrestricted egress or restoring the legacy bridge would defeat
ADR-0008 and ADR-0009. The supported path must be a separate, explicit profile
whose only route is a controlled gateway that enforces the engagement scope.

## Proposed design

1. **Separate network profile.** Add a `scoped` profile distinct from
   `isolated`. It creates a dedicated per-engagement network and attaches a
   policy gateway container; runners never receive a host gateway address.
2. **Policy gateway owns the only route.** The gateway is the sole egress
   point. It forwards only destinations and ports present in the engagement
   scope file, and denies everything else, including host services, the host
   LAN, metadata addresses, and external DNS unless explicitly allowed.
3. **Scope is enforced in the data path, not only in the CLI.** The matcher
   remains advisory for tool arguments; the gateway policy is the enforcement
   point. Redirects and DNS answers are re-checked against the same allowlist.
4. **Fail closed.** If the gateway is absent, unhealthy, or its policy cannot
   be loaded, the engagement network has no route. There is no automatic
   fallback to a bridge gateway.
5. **Separate credentials and lifecycle.** The gateway is managed like the
   future VPN gateway: host-only profile material, a narrow capability set,
   and an explicit `up`/`down` lifecycle. It is not part of the runner image.
6. **Audit every allowed flow.** The gateway records allowed and denied
   connections to the host-side audit log, so scope decisions are reviewable.

## Non-goals for M1

- No unrestricted egress.
- No transparent VPN routing or kill switch.
- No AI broker or model egress.
- No change to the Fedora firewall or global Docker daemon configuration.

## Exit criteria for implementing this ADR

- Negative tests prove that a runner cannot reach an out-of-scope address even
  when the tool ignores the scope file.
- Tests cover host services, the host LAN, metadata addresses, external DNS,
  redirects, IPv4, and IPv6.
- The default remains `isolated`; `scoped` requires an explicit engagement
  configuration and a running gateway.
