# ADR-0006: Run directly on Fedora; KVM is optional

- Status: Accepted
- Date: 2026-11-03
- Supersedes: ADR-0001

## Context

The original design required a dedicated KVM VM before any HAIBOX code could
run. That made the project a VM-management exercise and blocked development,
unit testing, and basic Docker functionality on the operator's Fedora
workstation.

The objective is a standalone Docker-based penetration-testing platform in the
style of Exegol: install the CLI, build images, create a container, open a
shell, and keep a persistent workspace. A dedicated Linux server is the
expected production target. A KVM VM is useful as an optional high-assurance
deployment, but it is not a prerequisite.

The Fedora host already runs Docker and unrelated services. It is therefore
inside the trust boundary when HAIBOX runs there. The operator is in the
`docker` group, which is root-equivalent. Rootful Docker is not a hard security
boundary against kernel or daemon compromise. These risks must be documented,
not hidden behind a VM requirement.

## Decision

1. **Direct Docker on Fedora is the primary development and runtime target.**
   The CLI, images, containers, workspaces, and tests must work there.
2. **A KVM VM is an optional deployment profile**, not a requirement. It may be
   used for high-risk engagements or when stronger host separation is needed.
3. **A dedicated Linux server is the recommended production target.** The same
   CLI and Docker runtime apply; no VM-specific code path is introduced.
4. **The runtime seam remains.** The manual lane uses the `DockerCli` adapter
   behind `ContainerRuntime`; a future restricted broker can implement the same
   protocol.
5. **The dedicated Docker context remains the default.** A context named
   `haibox` can point at the local socket on Fedora or at a remote dedicated
   server. The context is a guardrail, not proof of isolation.
6. **Before any Docker workload runs, the operator reviews mounts, privileges,
   network configuration, and impact on existing services.** The review is
   recorded in `docs/host-docker-review.md`.
7. **HAIBOX does not change the Fedora firewall, Docker daemon configuration,
   SELinux policy, or unrelated projects.** It uses client-side Docker contexts,
   per-engagement networks, and its own labelled resources.
8. **Secure defaults are non-negotiable:** no host networking, no privileged
   mode, no host PID/IPC, no devices for runners, `--cap-drop ALL`, non-root
   UID/GID, read-only rootfs, `no-new-privileges`, only the workspace writable,
   and the scope file read-only.
9. **Real engagements on a shared workstation remain a risk.** For hostile
   targets or untrusted tooling, use the optional VM or a dedicated server.

## Consequences

- Development and unit testing no longer require provisioning a VM.
- Basic Docker functionality is available immediately on Fedora.
- The Fedora host and its existing services are exposed to Docker-level risk;
  the threat model and host review must say so plainly.
- Rootful Docker means a container escape or daemon compromise can become host
  root. The container hardening reduces the attack surface but is not a hard
  boundary.
- The optional VM runbook remains useful, but it is no longer an approval gate
  for ordinary development.
- The runtime and image layers stay portable across Fedora, a dedicated
  server, and an optional VM.

## Alternatives considered

- **Keep the VM requirement.** Rejected: it blocks the actual product and turns
  HAIBOX into a VM-management project.
- **Rootless Docker only.** Better for some workloads, but it changes image and
  network behaviour and is not what the operator currently runs. It can be
  supported later as an optional deployment profile.
- **Podman.** Similar isolation properties, but the existing runtime and
  tooling target Docker. Revisit only with a concrete requirement.
