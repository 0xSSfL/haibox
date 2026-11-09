# Feature comparison

This document compares capability **categories**, not implementations. Exegol
is a mature public project; HAIBOX is an independent, early-stage source tree.
Upstream Exegol details change, so verify them against the current upstream
documentation before making a decision. No Exegol source or proprietary
implementation is copied into this repository.

## Summary

| Capability | Exegol-style platform (public docs) | HAIBOX today | Notes |
|---|---|---|---|
| Container-based toolkit | Yes, multiple images | Six images, all built and verified | Web/Core/Network active; AD/OSINT/Full experimental |
| CLI | Yes | Yes | Unit-tested; runtime validation in progress |
| Profiles | Yes | Yes, six built-ins | Web/Core/Network active; AD/OSINT/Full experimental |
| Persistent workspace | Yes | Yes, per engagement | Host path mode 0700 |
| VPN support | Yes (multiple providers) | Host-only profiles + separate gateway lifecycle | No runner routing or kill switch yet; gateway image not built |
| GUI / desktop | Yes | Not implemented | Deferred |
| AI assistance | Public integrations exist | Not implemented | Deferred; broker design only |
| Image build system | Yes | Yes, manifest-driven with local dependencies | Web/Core/Network built and verified |
| Vulnerability scanning | Optional ecosystem tools | trivy/grype adapter | Scanner not bundled |
| Multi-engagement isolation | Varies by deployment | Per-engagement isolated internal network | Scope policy incomplete |
| Scope enforcement | Usually procedural | Matcher + read-only scope file | Not network-enforced yet |
| Host-only secrets | Not a core promise | Mode-0600 store | Plaintext, same identity |
| Audit trail | Not a core promise | Hash-chained JSONL | Tamper-evident, not proof |
| Evidence manifests | Not a core promise | SHA-256 + read-only files | Host-only |
| Strong host boundary | Deployment choice | Optional KVM or dedicated server | Direct Fedora is the default |

## What HAIBOX does differently

1. **Isolation is the product, not a deployment note.** The container
   specification is deny-by-default and validated in code; there is no
   pass-through of arbitrary Docker flags. A post-create inspection removes a
   container whose shape differs from the specification.
2. **One engagement is the unit of isolation.** Each engagement gets its own
   workspace, network, scope file, evidence directory, reports, secrets, and
   audit chain. The platform refuses to operate on resources that lack its
   managed label.
3. **Host-only data is a first-class rule.** Secrets, evidence, reports, and
   audit logs are never mounted into a runner. This is stricter than a shared
   home directory model.
4. **Manual-first.** The manual lane must work without an AI service. The AI
   broker is an optional client of the runtime protocol, never the owner of the
   Docker socket.
5. **Fail-closed scope.** The matcher never resolves hostnames, exclusions
   always win, and a port allowlist requires a port. This is designed to make
   ambiguous targets deny, not allow.
6. **Deployment profiles are explicit.** Direct Docker on Fedora is the
   development target; a dedicated server is the production target; a KVM VM
   is an optional high-assurance profile. The CLI and image format are the
   same in all three.

## What Exegol-style platforms do better today

- A mature, tested image catalog with many specializations.
- Working VPN integrations and provider-specific workflows.
- A polished GUI and onboarding experience.
- A larger community, documentation set, and battle-tested edge cases.
- Packaging and installation ergonomics.

HAIBOX should not pretend to match those before M1–M6 are complete. It should
also not require a VM just to be usable; that would trade Exegol's ergonomics
for a VM-management project.

## Non-goals of the comparison

- Feature parity for its own sake.
- Copying upstream configuration formats or image contents.
- Claiming that a source-level feature is usable before it has run against a
  real Docker endpoint.
- Claiming that a scope file is an authorization or a legal control.
