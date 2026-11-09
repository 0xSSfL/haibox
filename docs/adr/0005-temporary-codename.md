# ADR-0005: Keep "HAIBOX" as a temporary codename

- Status: Accepted
- Date: 2026-11-02

## Context

The project needs a name for directories, imports, and the CLI while it is
being built. A public name creates expectations, package names, and branding
that are hard to change. The final name is not decided.

## Decision

1. "HAIBOX" is a temporary internal codename.
2. The distribution name is `haibox-platform`; the import package and CLI are
   `haibox`.
3. No package is published to a public index and no public release is made
   under this name.
4. A rename is expected before M6 (packaging and release). The rename must
   include the package name, CLI, data directory, Docker labels, and image
   references.

## Consequences

- Internal paths and labels use `haibox` for now.
- The rename is a deliberate migration, not an accident.
- Documentation must say "working title" until the decision is made.
