# ADR-0008: Isolated gateway mode for engagement networks

- Status: Accepted; decision 3 and rollback superseded by ADR-0009
- Date: 2026-11-04
- Related: ADR-0003 (scope enforcement), ADR-0006 (direct Docker)

## Context

HAIBOX created each engagement network with `docker network create
--internal`. That removes the default route to the internet, but Docker still
assigns the host an address on the bridge. On 2026-11-04 a probe from a runner
on such a network reached TCP/22 on the bridge gateway, where the Fedora host's
SSH daemon listens on `0.0.0.0:22`. The same path could reach any host service
bound to a Docker bridge address.

The first milestone cannot claim host-service isolation while that path is
open. The runtime must prevent runners from reaching host services by default,
without changing the global Docker daemon configuration or the Fedora firewall.

Docker 28.0.0 added `isolated` as a value for the
`com.docker.network.bridge.gateway_mode_ipv4` and
`com.docker.network.bridge.gateway_mode_ipv6` bridge options. It is only valid
with `--internal`, and it prevents the host from being assigned an address on
the bridge. For IPv6 it also disables IPv6 on the bridge. The local client and
server are 29.8.2.

## Decision

1. **The default engagement network profile is `isolated`.** HAIBOX creates
   the per-engagement network with:
   - `--internal`;
   - `--opt com.docker.network.bridge.gateway_mode_ipv4=isolated`;
   - `--opt com.docker.network.bridge.gateway_mode_ipv6=isolated`.
2. **Creation and reuse are verified.** After creating or finding an existing
   network, HAIBOX inspects it. The network must be internal, both gateway
   modes must be `isolated`, and IPAM must not report a gateway. A
   non-conforming network is refused instead of reused.
3. **The legacy profile stays available as an explicit opt-in.** Setting
   `network.profile: internal` keeps the old `--internal` behaviour. It is
   documented as unsafe for host-service isolation and is not the default.
4. **No global host change is required.** The profile is implemented with
   per-network Docker options and client-side verification. HAIBOX does not
   edit the daemon configuration, the Fedora firewall, or SELinux.
5. **The profile is not scope enforcement.** It denies host services, the host
   LAN, public internet, external DNS, and the metadata address. It does not
   restrict which authorized lab targets on the engagement bridge a tool may
   contact. That remains ADR-0003 work.

## Consequences

- Runners can no longer reach host SSH, PostgreSQL, other host listeners, the
  host LAN, public IPv4/IPv6, external DNS, or the link-local metadata address.
- Container-to-container traffic on the same engagement network still works,
  including Docker's embedded DNS for container names. This is the authorized
  lab-target path.
- Docker 28.0.0 or newer is required for the default profile. On an older
  daemon, network creation fails rather than silently falling back.
- Networks created by earlier HAIBOX versions are not conforming. HAIBOX
  refuses them; the operator must remove and recreate them. The error message
  says so.
- The profile does not replace a host firewall. A host-level compromise or a
  manually created non-isolated network can still expose services. The host
  review and threat model record this residual risk.

## Alternatives considered

- **Keep `--internal` and add a Fedora firewall policy.** Rejected for the
  default: it changes host-global state, needs approval, and is easy to drift.
  It remains a reasonable defence-in-depth layer later.
- **Use `com.docker.network.bridge.inhibit_ipv4=true`.** Rejected: it covers
  IPv4 only, and its documented purpose is to move the gateway elsewhere, not
  to isolate the network.
- **Use a user-defined network with no gateway via IPAM.** Not supported by
  Docker without additional host configuration.
- **Require the optional KVM VM.** Rejected by ADR-0006: direct Docker is the
  primary target.

## Rollback

To return a host to the legacy behaviour for a specific deployment, set:

```yaml
network:
  profile: internal
```

Then remove and recreate affected engagement networks so they no longer carry
the isolated gateway options. This restores the host-gateway exposure
documented in `docs/host-docker-review.md`; do not do it while host-service
isolation is required.
