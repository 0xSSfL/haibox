# ADR-0004: Defer AI and VPN until the manual lane is proven

- Status: Partially superseded by ADR-0007 (VPN); AI remains deferred
- Date: 2026-11-02

> **Update.** VPN management is now in scope under ADR-0007. AI integration
> remains deferred until a restricted broker exists.

## Context

AI integration and VPN support are the features most likely to widen the
attack surface. An AI that can execute tools needs a broker, a separate
identity, scope enforcement, and prompt-injection handling. A VPN needs a
kill switch, DNS leak prevention, and IPv6 handling. Building either on top of
an unproven container runtime would multiply the unknowns.

## Decision

1. The manual lane is the first deliverable. It must work with no AI service
   and no VPN.
2. VPN support is deferred until the network enforcement layer (ADR-0003) and
   the VM baseline are verified.
3. AI support is deferred until the broker can enforce the same invariants as
   the manual lane without exposing the Docker socket.
4. No placeholder command may imply that a deferred feature works. The CLI
   does not register `vpn` commands in this milestone.

## Consequences

- The first release is less feature-complete than an Exegol-style platform.
- The runtime protocol and the scope model are designed now so the later
  components can reuse them.
- Any future AI or VPN code must ship with negative tests and an ADR update.

## Alternatives considered

- **Build all lanes at once.** Rejected: too many unverified boundaries.
- **Give the AI the Docker CLI with a restricted wrapper.** Rejected: the
  Docker CLI is root-equivalent and has a large surface.
