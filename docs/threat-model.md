# Threat model

> **Status.** The unit suite, lint, and type checks pass on Fedora. Docker
> workload validation is in progress. This document separates what the current
> code enforces and what remains a known gap. Do not treat a mitigation as
> verified until the integration suite has run against the intended endpoint.

## 1. Scope and non-goals

### In scope

- A single operator running the manual lane directly on Fedora, on a dedicated
  Linux server, or optionally inside a KVM VM.
- One container per engagement, with a per-engagement internal bridge network
  using Docker's `isolated` gateway mode (the default).
- Host-only secrets, evidence, reports, and audit logs.
- The boundary between two engagements.
- The boundary between the manual lane and the future AI lane.
- Supply-chain risk from images and tools.
- Network scope enforcement, including DNS, IPv4/IPv6, redirects, host
  services, and VPN failure.

### Out of scope for the MVP

- A compromised Fedora host when HAIBOX runs directly on it, or a compromised
  hypervisor when the optional VM is used.
- A malicious operator with root on the host.
- Kernel or container-runtime zero-days. Docker is not a hard security
  boundary; the optional VM or a dedicated server is the boundary.
- Legal authorization. The platform can encode a scope but cannot grant one.
- Physical access, evil-maid attacks, and firmware compromise.
- Denial of service against the host that requires host-level recovery.
- The AI broker, which is not implemented.
- Transparent VPN routing and kill-switch enforcement, which are not
  implemented yet; profile storage is being added under ADR-0007.

## 2. Assets

| Asset | Why it matters |
|---|---|
| Target networks and systems | Unauthorized traffic can damage third parties |
| Engagement credentials | Reuse could compromise the operator or client |
| Evidence and reports | Integrity and confidentiality of client findings |
| Audit log | Accountability and incident reconstruction |
| Host-only data directory | Contains all of the above |
| Host and Docker daemon | Root-equivalent control of every runner |
| Operator workstation | Holds SSH keys and, with the optional VM, the VM disk |
| Image build inputs | A compromised tool can attack targets or the VM |

## 3. Actors

| Actor | Capability | Trust |
|---|---|---|
| Operator | Runs the CLI, is in the `docker` group | Trusted, but fallible |
| Engagement container | Runs untrusted tools and target-facing code | Untrusted |
| Target | May be malicious and may exploit the runner | Untrusted |
| AI model / agent (future) | Proposes and may execute tool commands | Untrusted |
| Image/tool supply chain | Provides binaries executed in the runner | Untrusted until pinned |
| Other engagement | Another client's container and data | Must be isolated |
| Fedora host | General-purpose workstation | Inside the boundary in direct mode |
| Hypervisor | Runs the optional VM | Trusted for the MVP |

## 4. Trust boundaries

```text
Direct mode (Fedora or dedicated server)
[ host ] --(docker)--> [ runner ] --(internal bridge)--> [ target network ]
    |
    +-- host-only data (secrets/evidence/audit)
    +-- Docker daemon (root-equivalent)

Optional high-assurance mode
[ Fedora host ] --(hypervisor)--> [ haibox VM ] --(docker)--> [ runner ]
```

1. **Host/VM**: in direct mode the host is inside the trust boundary; in the
   optional VM profile the VM is the primary containment boundary.
2. **Host/runner**: Docker namespaces, cgroups, capabilities, seccomp, and the
   read-only root filesystem.
3. **Runner/runner**: per-engagement internal networks and separate workspaces.
4. **Manual/AI**: separate containers, workspaces, identities, and a broker
   that never exposes the Docker socket.
5. **Runner/host data**: no mount of secrets, evidence, reports, or audit.
6. **Runner/target**: scope policy plus the operations network.

## 5. Threats and mitigations

### T1. Container escape to the host

**Scenario:** a target exploits a tool or the kernel and gains code execution in
the runner, then attempts to reach the Docker socket or host filesystem.

**Current mitigations:**
- no `--privileged`, no host PID/IPC/network, no devices;
- `--cap-drop ALL`, only `NET_RAW`/`NET_BIND_SERVICE` allowed;
- `no-new-privileges:true`, read-only root filesystem;
- non-root UID/GID;
- no Docker socket mount, no arbitrary host mounts;
- seccomp defaults are retained (no `--security-opt seccomp=unconfined`).

**Residual risk:** a kernel or runc escape is outside the container boundary.
In direct mode the host limits nothing further; the optional VM or a dedicated
server limits blast radius. That host must not hold unrelated credentials.

### T2. Cross-engagement access

**Scenario:** engagement A reaches engagement B's container, workspace,
network, secrets, or evidence.

**Current mitigations:**
- one internal bridge per engagement, named `haibox-<id>-net`;
- Docker's embedded DNS only resolves names on the same network;
- managed-label checks refuse to operate on another engagement's resources;
- separate workspace, evidence, reports, secrets, and audit paths;
- engagement IDs validated before path construction.

**Residual risk:** the Docker daemon is shared. A runner with Docker access
would break this; runners never receive the socket. Host-level network policy
between bridges is not yet enforced, so a compromised host-level process could
bridge networks. The future nftables policy must default-deny inter-bridge
traffic.

### T3. Scope violation / unauthorized target traffic

**Scenario:** a tool scans an out-of-scope host, an IP inside an allowed CIDR
but on an excluded port, or a hostname that resolves outside scope.

**Current mitigations:**
- `ScopeMatcher` denies by default, never resolves hostnames, applies
  exclusions first, requires a port when `allowed_ports` is set, and treats a
  port-specific exclusion as covering a port-less target;
- the scope file is mounted read-only so the runner cannot rewrite it;
- scope checks are audited.

**Residual risk (high):** the matcher is not wired into the network layer.
Nothing in the current runtime prevents a tool from connecting to an arbitrary
address on the engagement bridge. This is the most important open gap. Until
the default-deny policy exists, scope is advisory at the network level. The
operator must treat every engagement as capable of out-of-scope traffic.

### T4. DNS rebinding and name resolution

**Scenario:** an allowed hostname resolves to an out-of-scope address after the
check, or a tool uses DNS to reach a metadata service.

**Current mitigations:**
- the matcher never resolves names; IP targets only match IP/CIDR rules;
- the isolated bridge has no host address or external gateway, so external DNS
  fails (verified 2026-11-04);
- no host DNS configuration is mounted.

**Residual risk:** Docker's embedded DNS at `127.0.0.11` resolves container
names on the same network; this is intended. If a future VPN gateway provides
DNS, it must resolve through the policy, not around it. IPv6 must be covered
explicitly; an IPv4-only policy is insufficient.

### T5. Host service access

**Scenario:** a runner reaches the Docker API, SSH, libvirt, the host's package
mirror, or another host service through the bridge gateway or a published port.

**Current mitigations:**
- `--internal` network with both gateway modes set to `isolated`, so the host
  has no address on the engagement bridge;
- no published ports, no host network;
- no Docker socket mount;
- the CLI does not publish ports;
- HAIBOX refuses to reuse a network that lacks the isolated profile or still
  reports a host gateway.

**Residual risk:** the isolated profile removes the host-gateway path on
Docker 28+, but it is not a substitute for a host firewall, and it does not
scope allowed lab targets. The legacy `internal` profile was removed
(ADR-0009); requesting it fails validation. The host should still default-deny
inbound traffic from Docker bridges to host services, and the future policy
must test the bridge gateway, link-local addresses, and the Docker API socket
explicitly.

### T6. IPv6 bypass

**Scenario:** a tool reaches a target over IPv6 while the operator only
considered IPv4, or uses IPv6 to reach a host service.

**Current mitigations:** Docker IPv6 is off by default and the spec never
enables it; the engagement network is IPv4-only in the MVP.

**Residual risk:** the host may have IPv6 connectivity. The nftables policy
must default-drop IPv6 from runner bridges and the operations network unless an
engagement explicitly requires it. This is not implemented.

### T7. Redirects and route changes

**Scenario:** an ICMP redirect or a malicious router changes the runner's path
to an out-of-scope network.

**Current mitigations:** runners lack `NET_ADMIN`, so they cannot change routes
or firewall rules. The only route is the bridge subnet.

**Residual risk:** the host's forwarding and ICMP settings are not yet
hardened. Disable ICMP redirect acceptance and sending on the host; do not
enable IP forwarding between runner bridges and the management network.

### T8. VPN disconnection

**Scenario:** an engagement uses a VPN to reach an external target; the tunnel
drops and traffic falls back to the clear net.

**Current mitigations:** none; transparent routing and the kill switch are not
implemented. Profile storage is being added, but a profile does not change
runner routing.

**Required design:** the runner's only route is a gateway container/namespace
that owns the tunnel. The gateway installs a kill switch: when the tunnel is
down, the runner network has no route and DNS fails closed. The gateway must
not be reachable from the runner except as a router, and it must not expose the
host's management network. Test tunnel drop, reconnection, and DNS leakage.

### T9. Secrets disclosure

**Scenario:** a secret is printed in logs, written to the workspace, mounted
into a runner, or exposed through process arguments.

**Current mitigations:**
- secrets live in a host-only mode-0600 file;
- the CLI never prints secret values;
- audit redaction covers password/token/authorization/URL-userinfo patterns;
- secrets are not in `RuntimeSettings.environment` unless a profile explicitly
  adds an environment variable (profiles cannot read the secret store).

**Residual risk:** plaintext at rest; the operator account can read the file;
a command that takes a secret on its command line can leak it to the process
table or shell history. A separate trusted identity and a broker-mediated
secret injection path are planned (ADR-0002).

### T10. Evidence tampering or loss

**Scenario:** a runner or a host user modifies evidence, replaces a file with a
symlink, or deletes the manifest.

**Current mitigations:**
- evidence is copied out of the workspace into a host-only directory;
- SHA-256 manifests, files mode 0400, manifest mode 0600;
- symlink sources and symlinked path components are rejected;
- verification re-hashes files and detects writable files and symlinks;
- copying uses a temporary file and `os.replace`, avoiding a TOCTOU window.

**Residual risk:** a host user with write access can rewrite both the file and
the manifest. This is tamper-evident, not tamper-proof. Off-VM, append-only
backup is required for real assurance.

### T11. Audit tampering

**Scenario:** an attacker edits or deletes audit entries to hide activity.

**Current mitigations:** hash chain, mode 0600, `O_NOFOLLOW`, sequence
validation, redaction before storage.

**Residual risk:** a host user can rewrite the entire chain. The log is not
signed and is not shipped off-host. The future vault identity and remote
append-only sink address this.

### T12. Supply-chain compromise

**Scenario:** a base image, Go module, PyPI package, or nuclei template is
replaced with malicious content.

**Current mitigations:**
- base image digest pinned in the manifest and Dockerfile;
- tool versions pinned;
- Debian snapshot date pinned;
- nuclei templates pinned to a commit;
- image labels record the tool digest;
- optional trivy/grype scan.

**Residual risk:** no signature verification, no SBOM attestation, no
reproducible-build proof. Go module and PyPI installs still fetch from the
network at build time. The build must run in the intended deployment
environment, and the resulting image must be verified and scanned before use.
A compromised upstream at the pinned version is still possible.

### T13. Resource exhaustion

**Scenario:** a tool forks until the host is unusable, fills the disk, or
exhausts memory.

**Current mitigations:** CPU, memory, and PID limits; log rotation; tmpfs size
limits.

**Residual risk:** no workspace disk quota; a runner can fill the host disk.
Add a project quota or a dedicated volume with a quota before untrusted
engagements.

### T14. AI prompt injection / tool abuse (deferred)

**Scenario:** target content instructs an AI agent to run an out-of-scope
command, read a secret, or exfiltrate data.

**Current mitigations:** no AI lane exists.

**Required design:** the AI never receives the Docker socket; it calls a broker
with an allowlisted operation set; the broker enforces scope and resource
policy independently of the model; tool output is treated as untrusted data;
secrets are not in the AI context; the AI runner has its own workspace and
network. The manual lane must remain fully functional without the broker.

### T15. Operator error

**Scenario:** the operator uses the wrong engagement, publishes a port,
overrides the context, or runs against an unintended endpoint.

**Current mitigations:**
- explicit engagement resolution and a current pointer;
- managed labels and confirmation prompts;
- `doctor` checks the endpoint policy;
- the README and host review state the trust boundary and residual risk;
- no automation changes the daemon, firewall, or unrelated workloads.

**Residual risk:** the operator can still pass `--force`, edit configuration,
or run Docker manually. The platform cannot prevent a determined operator from
weakening its own isolation.

## 6. Attack scenarios and expected outcome

| # | Scenario | Expected outcome today | After planned work |
|---|---|---|---|
| 1 | Runner scans `10.0.0.0/8` | Possible; scope not network-enforced | Denied except scope |
| 2 | Runner curls the Docker socket | Fails; not mounted | Fails |
| 3 | Runner reads another engagement's workspace | Fails; not mounted, separate path | Fails |
| 4 | Runner resolves `metadata.google.internal` | Fails; no external DNS/gateway | Fails |
| 5 | Runner reaches the bridge gateway | Fails under the default `isolated` profile (no host address on the bridge, re-verified 2026-11-08); reachable under legacy `internal` | Host firewall denies or no host bridge |
| 6 | Runner uses IPv6 to bypass scope | No global IPv6 in the 2026-11-04 probe; policy still not enforced | IPv6 default-deny |
| 7 | VPN drops mid-engagement | N/A; no VPN routing | Kill switch, no fallback |
| 8 | Target compromises the runner | Contained by the container; host risk in direct mode | Same, plus network policy |
| 9 | Host user edits evidence | Detected by hash, not prevented | Separate identity + off-host backup |
| 10 | Malicious image build input | Possible; pins reduce, do not eliminate | Signing/SBOM + isolated builder |

## 7. Security verification checklist

Run these against the intended Docker endpoint after the first build. Each item
must have a recorded result before the platform is used on a real engagement.

- [ ] `docker inspect` shows `Privileged=false`, `ReadonlyRootfs=true`,
      `CapDrop=["ALL"]`, no `Binds`, no `PortBindings`, no `Devices`.
- [ ] `id -u` in the runner is non-zero and matches the engagement.
- [ ] `/etc/haibox/scope.json` is read-only; `/workspace` is writable.
- [ ] `/evidence`, `/reports`, and `secrets.json` are absent.
- [x] `ip route` in the runner has no default route. (2026-11-04)
- [x] External DNS resolution fails. (2026-11-04)
- [x] The link-local metadata address is unreachable. (2026-11-04)
- [x] The bridge gateway is unreachable under the `isolated` profile.
      (2026-11-08: host SSH, PostgreSQL, host bridges, LAN, public IPs, DNS,
      and HTTP all failed.) The legacy `internal` profile was removed; see
      ADR-0009 and `docs/host-docker-review.md`.
- [ ] A second engagement cannot resolve or reach the first.
- [x] IPv6 is absent or denied on the tested host. (2026-11-04; no global IPv6
      address; network-level IPv6 policy is still M2.)
- [ ] Container removal and network removal require the managed label.
- [ ] The Docker `default` context is refused.
- [ ] Evidence verification detects a modified file, a symlink, and a missing
      file.
- [ ] Audit verification detects an edited entry and a deleted entry.
- [ ] Secrets never appear in CLI output or audit logs.
- [x] `haibox image verify` passes for `web-security`, `core`,
      `network-security`, `ad-security`, and `osint`. (2026-11-09)
- [ ] `trivy image` (or grype) reports no unaccepted HIGH/CRITICAL findings.
      Web Security is still open at 165 findings; the other images have not
      been scanned yet.
- [ ] GUI session (ADR-0011): the runtime refuses an engagement
      that is not `isolated`, has a non-empty scope, has scope metadata that
      differs from the canonical scope file, or is attached to a network other
      than the engagement network; a session is never replaced before the
      previous server is confirmed terminated; a foreign Xpra server on the
      same display is never signalled; the socket is mode 0600 inside a
      mode-0700 directory. (The GUI is not an enabled product feature.)

## 8. Incident response

1. Stop the engagement container (`haibox container stop`).
2. Snapshot the host or VM before changing anything.
3. Export the platform and engagement audit logs; verify the chain.
4. Preserve the workspace and evidence directories read-only.
5. Do not run cleanup commands that could destroy the container or network
   until the snapshot exists.
6. If the host may be compromised, rebuild it from a known-good image or
   snapshot; do not reuse credentials stored in it.
7. Rotate any secret that was present on the compromised host.
