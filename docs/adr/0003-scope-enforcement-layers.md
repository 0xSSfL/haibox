# ADR-0003: Scope enforcement in layers

- Status: Accepted; only the matcher layer is implemented
- Date: 2026-11-02

## Context

A scope file that a tool may ignore is not an enforcement mechanism. The
platform needs to prevent out-of-scope traffic even when a tool is malicious,
misconfigured, or does not understand the scope format. The bypass surface
includes host services, the bridge gateway, DNS, IPv4/IPv6, redirects, and VPN
disconnection.

## Decision

Scope is enforced in independent layers:

1. **Input validation.** The scope model rejects empty entries and invalid
   ports; the engagement cannot be created with an ambiguous scope unless the
   operator explicitly allows an empty scope.
2. **Policy decision.** `ScopeMatcher` denies by default, never resolves
   hostnames, applies exclusions first, and fails closed on ports.
3. **Container shape.** The runner has no host network, no published ports, no
   `NET_ADMIN`, no Docker socket, and no arbitrary mounts. It cannot change its
   own routes or firewall.
4. **Network policy (planned).** A host-side nftables policy on the VM
   default-denies traffic from the runner bridge except to the scope. It covers
   IPv4/IPv6, DNS, host services, the gateway, link-local addresses, redirects,
   and VPN failure.
5. **VPN gateway (planned).** The runner's only route is a gateway that owns
   the tunnel. If the tunnel drops, the route disappears.

Layer 4 is the enforcement layer. Layers 1–3 reduce the attack surface but do
not replace it. A scope check is not a guarantee that a tool obeyed it.

## Consequences

- The MVP must be described as **advisory scope**, not enforced scope, until
  layer 4 exists.
- The integration suite must include negative tests for each bypass path.
- The network policy must be generated from the same scope data the matcher
  uses, or the two can drift.
- The policy must be tested with a compromised runner, not only with a
  cooperative tool.

## Alternatives considered

- **Proxy all traffic through an HTTP proxy.** Fails for non-HTTP tools and
  does not cover raw sockets.
- **Rely on the tool's own scope flag.** A malicious or buggy tool ignores it.
- **Put the runner in a network namespace with no route.** Safe but useless
  for an engagement; the gateway design adds the controlled route.
