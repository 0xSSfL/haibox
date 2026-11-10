# Verification Status

This document records the verification history and test results for the HAIBOX
platform. The table is intentionally blunt: do not treat a source-level feature
as working until the corresponding row has a recorded result.

## Verification Matrix

| Check | Status |
|---|---|
| `uv sync --extra dev` | Passed on Fedora, 2026-11-03 |
| `pytest` (unit, fake runtime) | 275 passed, 2 skipped (integration opt-in), 2026-11-10 |
| `ruff check .` | Passed, 2026-11-10 |
| `mypy src` | Passed, 2026-11-10 |
| `haibox` CLI invocation | `version`, `init`, `doctor`, `info`, `tui` passed on Fedora, 2026-11-09 |
| Docker context `haibox` | Created; client/server 29.9.2, rechecked 2026-11-08 |
| Docker integration smoke test | Passed with the final image: 2 passed, 2026-11-09 |
| Runner network probe (isolated profile) | Manual probe: no default route, no global IPv6, external DNS fails, metadata unreachable, host LAN SSH/PostgreSQL, host bridges, and public IPv4/IPv6 unreachable; container-to-container works, 2026-11-08 |
| `haibox vpn` profile CLI | `add`, `list`, `show`, `status` passed on Fedora, 2026-11-03 |
| `haibox vpn up` without gateway image | Fails cleanly with exit 1 and no traceback, 2026-11-03 |
| VPN gateway lifecycle | Not run; `haibox/vpn-gateway:0.1.0` is not built |
| Web Security image build & verify | Passed; digest `sha256:5dfddb51…520b9aa`, 15 pinned tools verified, 2026-11-08 |
| Core image build & verify | Passed; digest `sha256:962ce703…d68c5fc`, 18 pinned tools verified, 2026-11-09 |
| Network Security build & verify | Passed; digest `sha256:75a634b4…effcd3`, 12 pinned tools verified, 2026-11-09 |
| Active Directory build & verify | Passed; digest `sha256:8cef90b5…effaf3d9`, 5 pinned tools verified, 2026-11-09 |
| OSINT image build & verify | Passed; digest `sha256:baf53815…c000d3c5`, 6 pinned tools verified, 2026-11-09 |
| Full image build & verify | Passed; digest `sha256:bfac7833…be69dd2b`, 31 pinned tools verified, 2026-11-09 |
| Catalog vulnerability scans (Trivy) | Baselines recorded for all 6 variants; gate open on dependency findings (Debian 13 base packages and pinned Go modules), 2026-11-09 |
| Trivy suppression scope check | **Passed** for `web-security`, `osint`, and `full`: all removed secret findings matched declared path/rule scopes, 2026-11-09 |
| `haibox info` / interactive menu | `info` (table and JSON) and `tui` smoke-tested, 2026-11-09 |
| KVM VM | Optional; not created |

## Capabilities in Source

| Capability | State |
|---|---|
| Python CLI (`haibox`) | `version`, `init`, `doctor`, `info`, `tui` verified on Fedora; colour/quiet/JSON/confirmation options |
| Interactive menu (TUI) | Implemented as a dispatcher over the same Typer commands; smoke-tested |
| Engagement directories and scope files | Implemented; unit tests pass |
| Deny-by-default container specification | Implemented; unit and smoke tests pass |
| Docker CLI runtime with managed-label checks | Implemented; unit and smoke tests pass |
| Interactive shell and one-off command execution | Implemented; runtime validation in progress |
| Per-engagement persistent workspace | Implemented; smoke-tested |
| Host-side hash-chained audit log | Implemented; unit tests pass |
| Host-only secret store | Implemented; plaintext at rest |
| Host-only evidence store with SHA-256 manifests | Implemented; unit tests pass |
| Web Security Dockerfile + pinned tool manifest | Built and verified; scan gate open on dependency findings |
| Image build/verify/scan adapters | Implemented; Docker/scanner required |
| Core / Network Security images | Built and verified; Core is the shared base |
| Active Directory image | Built and verified; experimental profile |
| OSINT image | Built and verified; experimental profile |
| Full image | Built and verified; experimental combined profile |
| Dependency-aware image builds | Implemented; `depends_on` builds local bases in order and rejects cycles |
| Network-layer nftables policy generator | Implemented; unit tests pass (ruleset generation, exclusions precedence, always-drop, apply/remove) |
| nftables runtime wiring (`scoped` profile) | Partially implemented in `DockerCli`: policy applied on container create and removed with the network. Unit-tested only through the generator; no runtime/integration test yet. Known gaps: host input path, DNS, hostname entries, policy re-apply, and config/profile mismatch (see M2 in `roadmap.md`) |
| VPN profile store and gateway lifecycle | Implemented; gateway image not built |
| Transparent VPN routing and kill switch | Not implemented |
| Restricted Docker broker + AI adapter | Not implemented |
| GUI / desktop | Not implemented |

## Related Documentation

- [User Guide](user-guide.md)
- [Image Catalog](image-catalog.md)
- [Image Validation Evidence](image-validation.md)
- [Vulnerability Risk Register](vulnerability-risk-register.md)
- [Host Docker Review](host-docker-review.md)
- [Roadmap](roadmap.md)
