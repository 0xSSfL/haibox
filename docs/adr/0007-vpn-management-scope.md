# ADR-0007: VPN management is in scope; AI remains deferred

- Status: Accepted
- Date: 2026-11-03
- Supersedes: ADR-0004 (VPN portion only)

## Context

VPN support is a core capability for a penetration-testing platform. The first
milestone deferred it until a VM baseline existed. With the VM now optional,
VPN management must be designed for direct Docker use without giving the
engagement runner broad privileges.

A VPN client normally needs `NET_ADMIN` and `/dev/net/tun`. Granting those to
an untrusted engagement runner would weaken the container boundary and make
scope enforcement harder. A separate gateway container is therefore the
preferred design.

## Decision

1. **AI integration remains deferred.** It will return only with a restricted
   broker that never exposes the Docker socket to a model.
2. **VPN management is in scope.** HAIBOX will manage host-only VPN profiles
   for WireGuard and OpenVPN, validate them, and start/stop a dedicated gateway
   container per engagement.
3. **VPN configuration is host-only.** Profile files are stored under the
   HAIBOX data directory with mode `0600`. They are mounted read-only into the
   gateway container only, never into the normal engagement runner.
4. **The VPN gateway is separate from the runner.** The gateway is trusted
   infrastructure. It may receive `NET_ADMIN` and `/dev/net/tun`, but it must
   not receive host networking, privileged mode, the Docker socket, or
   unrestricted host mounts.
5. **The runner stays unprivileged.** A VPN-enabled runner either shares the
   gateway's network namespace or uses a gateway-provided proxy. It must not
   receive `NET_ADMIN` or `/dev/net/tun` itself.
6. **The default is no VPN.** An engagement without an explicit VPN profile
   uses the ordinary isolated bridge.
7. **Kill-switch behaviour must be tested, not assumed.** Transparent routing is
   not claimed until DNS leaks, IPv4/IPv6 fallback, and tunnel-drop behaviour
   have negative tests.
8. **No placeholder command may imply connectivity works.** The CLI may expose
   profile management before routing is complete, but it must label the state
   accurately.

## Implementation status (2026-11-03)

- Profile storage, validation, and the `haibox vpn` profile commands are
  implemented and unit-tested.
- The separate gateway specification and Docker adapter are implemented and
  unit-tested. The gateway receives exactly `NET_ADMIN` and `/dev/net/tun`.
- The gateway image `haibox/vpn-gateway:0.1.0` is not built. `haibox vpn up`
  fails cleanly and reports that the image is missing.
- Gateways are currently keyed by VPN profile, not by engagement. Attaching a
  runner to a gateway remains future work.
- Runner routing and kill-switch enforcement are not implemented; the CLI and
  status output say so explicitly.

## Consequences

- Users can register and inspect VPN profiles without weakening the runner.
- A gateway sidecar adds a second container and a controlled privilege
  exception; this is visible and auditable.
- Transparent routing and kill-switch behaviour need dedicated integration
  tests before they are described as working.
- The AI lane remains out of scope until its broker is designed.

## Alternatives considered

- **Run the VPN client inside the engagement runner.** Simpler, but requires
  `NET_ADMIN` and `/dev/net/tun` in the untrusted container. Rejected as the
  default.
- **Use the host VPN client.** Changes host networking and affects unrelated
  services. Rejected.
- **Proxy-only VPN.** Useful for HTTP tools but not transparent for arbitrary
  scanners. Kept as a possible fallback, not the primary design.
