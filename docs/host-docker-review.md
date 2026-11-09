# Host Docker review: Fedora workstation

- Date: 2026-11-03
- Host: Fedora Linux 44, x86_64
- Docker client/server: 29.8.2
- Docker root: `/var/lib/docker`
- Operator: UID/GID 1000, member of `wheel` and `docker`
- SELinux: disabled
- Docker daemon: rootful (no rootless security option reported)
- Existing workloads observed:
  - container `reswip-scrapping-platform-postgres-1`
  - network `reswip-scrapping-platform_default` (`172.18.0.0/16`)

This review is required before HAIBOX creates containers or networks on this
host. It records what HAIBOX will and will not touch.

## 1. Trust boundary

The Fedora host is now inside HAIBOX's trust boundary for development and
ordinary use. The operator is in the `docker` group, which is root-equivalent.
Rootful Docker is not a hard security boundary: a container escape or daemon
compromise can become host root.

Consequences:

- HAIBOX containers must remain unprivileged and non-root.
- Host networking, host PID/IPC, devices, and unrestricted bind mounts are
  refused by the container specification.
- Real engagements against hostile targets should use the optional KVM VM or a
  dedicated Linux server. Direct Fedora use is appropriate for development,
  unit testing, and controlled lab work.

## 2. Mounts

The normal engagement container receives exactly two bind mounts:

| Host path | Container path | Mode | Purpose |
|---|---|---|---|
| `~/.local/share/haibox/engagements/<id>/workspace` | `/workspace` | read-write | Persistent engagement workspace |
| `~/.local/share/haibox/engagements/<id>/scope.json` | `/etc/haibox/scope.json` | read-only | Scope policy input |

Not mounted:

- the Docker socket;
- the home directory;
- `/var/run`, `/etc`, or the host root;
- evidence, reports, secrets, or audit logs;
- VPN profiles (these are gateway-only, if VPN support is enabled);
- unrelated project directories.

The workspace is owned by the operator UID/GID. HAIBOX does not `chown` host
directories automatically. If a different container UID/GID is requested, the
operator must adjust ownership explicitly.

Docker also creates its own `/etc/resolv.conf`, `/etc/hostname`, and `/etc/hosts`
bind mounts from the container state directory. These are Docker-managed and
are verified as such after creation.

## 3. Privileges

The engagement container is created with:

- non-root `--user <uid>:<gid>`;
- `--cap-drop ALL`, with only `NET_RAW` or `NET_BIND_SERVICE` allowed by a
  profile;
- `--security-opt no-new-privileges:true`;
- read-only root filesystem;
- `tmpfs` for `/tmp` and `/run`;
- private PID, IPC, and network namespaces;
- no `--privileged`;
- no host network, host PID, or host IPC;
- no devices;
- no published ports;
- CPU, memory, PID, and file-descriptor limits;
- restart policy `no`;
- local log driver with size rotation.

`NET_RAW` is required by some scanning tools. It allows raw packet creation in
the container's network namespace; it does not grant host network access.
`NET_BIND_SERVICE` is only needed by tools that bind low ports inside the
container. Neither capability is granted unless a profile asks for it.

The VPN gateway, when implemented, is a separate trusted container. It may need
`NET_ADMIN` and `/dev/net/tun` to establish a tunnel. It must not receive host
networking, privileged mode, the Docker socket, or broad host mounts. The
engagement runner must not receive those privileges.

## 4. Network

- Each engagement gets a dedicated Docker bridge network named
  `haibox-<engagement>-net`.
- The default `network.profile: isolated` creates the network with
  `--internal` plus
  `com.docker.network.bridge.gateway_mode_ipv4=isolated` and
  `com.docker.network.bridge.gateway_mode_ipv6=isolated`. Docker assigns the
  host **no address** on that bridge, so the bridge gateway is not reachable
  from a runner. This requires Docker 28.0.0 or newer.
- HAIBOX verifies the created or reused network: it must be internal, both
  gateway modes must be `isolated`, and IPAM must not report a host gateway.
  A non-conforming network is refused rather than reused.
- The legacy `network.profile: internal` profile was removed (ADR-0009). It
  kept `--internal` without isolated gateway mode, which blocked internet
  egress but **not** host services on the bridge gateway. A configuration that
  requests it now fails validation.
- No ports are published.
- HAIBOX never uses `--network host`.
- The existing `reswip-scrapping-platform_default` network is not modified or
  joined.
- Docker's IPAM chooses a free subnet from the daemon's address pool. HAIBOX
  does not change the daemon's default address pools.
- Scope enforcement at the network layer is **not implemented yet**. The
  internal bridge removes direct internet access, but it is not a default-deny
  policy for host services, gateways, DNS, redirects, IPv4/IPv6, or VPN
  failure. Do not treat the scope file as network enforcement.
- **Legacy gap (removed from normal use): the host bridge gateway is reachable
  on `--internal` alone.** A probe from a runner on a plain `--internal` bridge
  reached TCP/22 on the gateway, where the host SSH daemon listens on
  `0.0.0.0:22`. Docker's `isolated` gateway mode removes the host address from
  the bridge and closes that path. ADR-0009 removed the legacy profile, so
  HAIBOX no longer creates or accepts such a network; a manually created
  non-isolated bridge remains a host-level risk outside HAIBOX's control.

A VPN-enabled design must add a controlled egress path and a kill switch before
it can claim transparent VPN routing. That work is tracked in ADR-0007.

## 5. Impact on existing services

HAIBOX uses unique resource names and labels:

- containers: `haibox-<engagement>`;
- networks: `haibox-<engagement>-net`;
- labels: `haibox.managed=true`, `haibox.engagement=<id>`.

It does not:

- restart or reconfigure the Docker daemon;
- change `/etc/docker/daemon.json`;
- change Fedora firewall rules, nftables, or SELinux policy;
- remove or modify unlabelled containers or networks;
- publish ports;
- join the existing application network;
- touch `~/Work/pentest-lab` or other projects.

Resource impact: each engagement container is limited to the profile's CPU,
memory, and PID limits. Each internal network consumes a Docker bridge and a
subnet. Images and container logs consume disk under `/var/lib/docker`; the host
currently has about 153 GiB free. A workspace disk quota is not implemented, so
a runner can still fill the host filesystem through `/workspace`.

## 6. Preflight before a Docker workload

Run these read-only checks:

```bash
docker context ls
docker version
docker info --format '{{json .SecurityOptions}}'
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'
docker network ls
getenforce
df -h /var/lib/docker
```

Then verify:

- [ ] The dedicated context exists and points at the intended daemon.
- [ ] No unexpected HAIBOX containers or networks are already present.
- [ ] The existing application container is healthy and will not be touched.
- [ ] SELinux state is known. On an enforcing host, bind-mount labels must be
      handled explicitly; HAIBOX does not change SELinux policy.
- [ ] Enough disk space exists for the image and workspace.
- [ ] The engagement scope and image are intentional.

## 7. Current verification status

The unit suite, lint, and type checks pass on this host. The client-side
`haibox` context points at `unix:///var/run/docker.sock`; `haibox version`,
`init`, and `doctor` pass. The first Docker smoke test ran with an existing
local image, an internal network, no published ports, and a disposable
engagement. It verified the non-root UID, writable workspace, read-only scope
file, internal network label, and absence of host-only paths, then removed the
container and network.

The smoke test exposed two issues that are now fixed:

- Docker reports capabilities as `CAP_NET_RAW` even when `NET_RAW` is
  requested; the post-create verifier normalizes both forms.
- An image that declares `VOLUME` creates an anonymous writable volume that
  bypasses the read-only root filesystem. The verifier now refuses such a
  container, and cleanup removes anonymous volumes.

The existing `reswip-scrapping-platform-postgres-1` container remained
healthy and was not modified. No HAIBOX container, network, or volume remains.

On 2026-11-04 a manual network probe from a runner on an `--internal` bridge
confirmed:

- no default route;
- no global IPv6 address;
- external DNS resolution fails;
- the link-local metadata address is unreachable;
- **TCP/22 on the bridge gateway is reachable**, matching the host SSH daemon
  bound to `0.0.0.0:22`.

That probe is the reason the default profile changed. A second probe on the
same day, using `--internal` with both gateway modes set to `isolated`,
confirmed that the host address is gone from the bridge and that all of the
following fail from a runner:

- TCP/22, TCP/5432, and TCP/80/443 on the former gateway address;
- the host LAN address (`192.168.1.34`) on SSH and PostgreSQL;
- `1.1.1.1:443` and `8.8.8.8:53`;
- external DNS resolution;
- ICMP to the gateway.

Container-to-container traffic on the engagement bridge still works, including
name resolution between two containers on that network. The first probe's
gateway finding is the legacy `internal` profile; the second probe is the
default `isolated` profile.

Re-verified on 2026-11-08 against the final Debian 13 image
(`haibox/web-security:0.1.0`, digest
`sha256:4297d6c01a36135e442bed11e4fd89fce43c3cf63be8e5f8a5929ce917189ba6`):

- the network reports `internal=true`, both gateway modes `isolated`, subnet
  `172.19.0.0/16`, and `gateway=invalid IP`;
- the host bridge interface has no IPv4 address;
- the runner has no default route and no global IPv6 address;
- `192.168.1.34:22`, `172.17.0.1:22`, `172.18.0.1:22`, `169.254.169.254:80`,
  and `1.1.1.1:443` are all blocked;
- DNS resolution and an HTTP request to `example.com` fail;
- container-to-container TCP by name still succeeds.

A manually created legacy `--internal` network created on the same day still
reported a host gateway (`172.19.0.1`) and still allowed TCP/22 to it. That is
why ADR-0009 removed the profile instead of keeping it as an opt-in.
PostgreSQL on the host remains loopback-only, so it was blocked on both
profiles.
