# Documentation

HAIBOX is an isolation-first, manual-first penetration-testing platform. The
documents below describe the current source tree and the evidence behind each
claim. A procedure is not a result; verification rows live in the top-level
`README.md` and in the per-image validation record.

| Document | Purpose |
|---|---|
| [user-guide.md](user-guide.md) | Concepts, first run, engagement lifecycle, TUI, global options, full CLI reference, images, security model, troubleshooting |
| [architecture.md](architecture.md) | Components, data flow, invariants, trust boundaries, known gaps |
| [threat-model.md](threat-model.md) | Assets, actors, threats, mitigations, verification checklist |
| [image-catalog.md](image-catalog.md) | Image variants, tool sets, dependency graph, build order, and status |
| [verification-status.md](verification-status.md) | Recorded verification history, test results, and capability status |
| [image-validation.md](image-validation.md) | Build inputs, verification, integration, scan, and suppression results for the Web Security image |
| [vulnerability-risk-register.md](vulnerability-risk-register.md) | Per-group analysis of remaining HIGH/CRITICAL findings and why they are not suppressed |
| [roadmap.md](roadmap.md) | Milestones from source foundation to release |
| [feature-comparison.md](feature-comparison.md) | Capability categories vs. an Exegol-style platform |
| [host-docker-review.md](host-docker-review.md) | Host Docker endpoint review and dedicated-context policy |
| [adr/](adr/) | Architecture decision records, including isolated networking and the future scoped profile |
| [runbooks/kvm-vm-setup.md](runbooks/kvm-vm-setup.md) | Optional VM specification, network design, installation plan |

## How the project works in one paragraph

The operator creates an **engagement** with a frozen profile and an explicit
scope. HAIBOX writes host-only state under the XDG data directory, creates a
per-engagement **internal bridge network** using Docker's `isolated` gateway
mode, and builds the runner from a deny-by-default `ContainerSpec` (non-root,
read-only root, dropped capabilities, no host network, one writable workspace
bind). The operator uses `shell` or `run` for manual work. Evidence, secrets,
reports, and the hash-chained audit log stay on the host and are never mounted
into the runner. Image definitions pin the base digest, Debian snapshot, and
tool versions; `image build` resolves local image dependencies, `image verify`
runs the manifest checks as a non-root user, and `image scan` fails closed on
HIGH/CRITICAL findings.

## Research note

The independent capability review of Exegol, toolbox-pentest-web, Vulpes,
Leviathan, and ai-RedAlert is kept outside this repository at
`/home/souaib/Work/haibox-research/docs/technical-comparison.md`. It is a
read-only research artifact: no third-party source, configuration, branding, or
protected implementation is copied into HAIBOX. The repository license and
provenance notes are in `haibox-research/meta/` on that workstation.
