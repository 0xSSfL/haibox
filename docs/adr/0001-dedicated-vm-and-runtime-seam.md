# ADR-0001: Dedicated VM and a narrow runtime seam

- Status: Superseded by ADR-0006
- Date: 2026-11-02

> **Superseded.** The dedicated VM is now an optional deployment profile.
> Direct Docker on Fedora is the primary development and runtime target. The
> runtime-seam decision in this ADR remains valid.

## Context

The Fedora workstation is a general-purpose host. The operator is in `wheel`
and `docker`, unrelated services run on it, and the earlier Bubblewrap sandbox
shared the host network namespace. Running engagement containers there would
inherit those boundaries. Docker itself is root-equivalent and is not a hard
security boundary against kernel exploits.

## Decision

1. The supported runtime is a dedicated KVM VM. The workstation is outside the
   trust boundary.
2. The CLI talks to Docker through a `ContainerRuntime` protocol. The manual
   lane uses a `DockerCli` adapter that invokes the `docker` binary without a
   shell and always passes an explicit context or host.
3. The adapter refuses the `default` Docker context by default. A context
   named `haibox` is a guardrail, not proof of endpoint isolation; the VM is
   the isolation boundary.
4. The future AI broker implements the same protocol. It never receives the
   Docker socket.
5. Container options are constructed by `ContainerSpec`; there is no arbitrary
   flag pass-through.

## Consequences

- The platform cannot be used safely on the workstation, even for a quick
  test. That is intentional.
- The VM must be provisioned and maintained separately.
- A named context can still point at a shared daemon; the operator and the
  runbook must verify the endpoint.
- The runtime seam keeps the CLI testable with a fake and leaves room for a
  broker without changing callers.

## Alternatives considered

- **Rootless Docker on the workstation.** Better than rootful Docker, but it
  still shares the workstation's user session, network, and credentials.
- **Podman on the workstation.** Similar boundary problem.
- **Direct Docker SDK calls.** A larger dependency and a wider surface than a
  small subprocess adapter; rejected for the MVP.
