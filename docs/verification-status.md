# Verification Status

This document records the verification history and test results for the HAIBOX
platform. The table is intentionally blunt: do not treat a source-level feature
as working until the corresponding row has a recorded result.

## Verification Matrix

| Check | Status |
|---|---|
| `uv sync --extra dev` | Passed on Fedora, 2026-11-03 |
| `pytest` (unit, fake runtime) | 392 passed, 2 skipped (integration opt-in), 2026-11-12 |
| `ruff check .` | Passed, 2026-11-12 |
| `mypy src` | Passed, 2026-11-12 |
| `haibox` CLI invocation | `version`, `init`, `doctor`, `info`, `tui` passed on Fedora, 2026-11-09 |
| Docker context `haibox` | Created; client/server 29.9.2, rechecked 2026-11-08 |
| Docker integration smoke test | Passed with the final image: 2 passed, 2026-11-09 |
| Runner network probe (isolated profile) | Manual probe: no default route, no global IPv6, external DNS fails, metadata unreachable, host LAN SSH/PostgreSQL, host bridges, and public IPv4/IPv6 unreachable; container-to-container works, 2026-11-08 |
| GUI production program baseline | Baseline recorded 2026-11-12 on `main` at `73aa4cf` (PR #11 merged): `make check` 392 passed, 2 skipped, ruff and mypy clean; Docker 29.9.2 on the dedicated `haibox` context; Fedora 44 X11 host with the extracted Xpra 6.5.4 client; Trivy 0.76.2 and Grype 0.121.3. The GUI image gate is still closed (4 CRITICAL, 61 HIGH on the Fedora 44 fixture), real Wayland input is untested, M2 scope enforcement is unimplemented, GUI audit events and explicit resource limits are missing. Plan: `docs/superpowers/plans/2026-11-12-gui-production-program.md` |
| GUI image | `haibox/gui:0.1.0` built, verified, and scanned 2026-11-12: Fedora 46 base pinned by digest, Xpra 6.5.6, 379 RPMs, 1.21 GB, package inventory in `images/gui/packages.lock`. The hardened scan pipeline reports `Unsupported os` for Fedora and covers the OS through the Grype fallback: **0 HIGH/CRITICAL findings**, exit 0, the only image in the catalog with a green scan. The 66 findings of the previous Fedora 44 fixture (50 Pillow, 16 PCRE2) are remediated by the fixed upstream packages, with no ignore file and no exception. Qualification: Fedora 46 is still a pre-release snapshot, so the image is experimental and must be rebuilt on the stable release. Evidence: `docs/superpowers/poc/2026-11-12-gui-image-security.md` |
| Xpra seamless GUI readiness | Prototype passed, 2026-11-11: pinned Fedora 44 Xpra 6.5.4 fixture with a 502-RPM inventory; native xterm on X11; GTK3 Wayland client created an `xdg_toplevel` on headless Weston 15.0.1; engagement-bound Unix-socket relay with `SO_PEERCRED`, managed-label/engagement checks, file authentication, 14 deny-by-default controls, and cross-engagement, wrong-password, concurrency, detach, container-stop, and relay-cleanup negatives. Docker inspect confirms no privileged mode, host namespaces, ports, devices, Docker socket, or host display socket. Scan: Trivy 0.76.2 rejects Fedora as unsupported, Grype 0.121.3 covers it but reports 4 CRITICAL and 61 HIGH, so the image gate stays closed. Wayland input forwarding is untested. 2026-11-12 hardening: relay/session fail closed on non-isolated or non-empty target scope, compare engagement metadata with the canonical scope file, require exactly one observed Docker network membership, create host password files with 0600 from creation in a verified 0700 directory, rotate and remove credentials on stop/failure, require private socket directories, and bound inspect/stream/child cleanup. 39 fake-runtime unit regressions were added, later extended to 64 for the session replacement lifecycle. The hardened scripts were re-run against real Docker on disposable isolated engagements: an added internal network with an unchanged `HostConfig.NetworkMode` was refused, non-empty/mismatched/mode-000 scope files were refused with the original hash restored, host and container passwords were 0600 and byte-identical, a second prepare left one server and rotated the password, old/wrong/cross-engagement passwords failed, sockets were 0600 in a 0700 directory, detach/reconnect worked, stop and failed-start cleanup removed credentials, and cross-engagement TCP/DNS probes failed. A further disposable engagement confirmed the session replacement lifecycle: a frozen server that survived a timed-out stop was refused with the credential, runtime, and server left untouched, a foreign Xpra server on the same display was refused and never signalled, and a successful second prepare left exactly one server with rotated credentials. No production CLI, sidecar, or catalog image; internal evidence: `docs/superpowers/poc/2026-11-11-xpra-gui-readiness.md` |
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
| Scanner coverage and Grype fallback | **Passed** against real Docker: Trivy covered Debian core (138 findings); Fedora 44 (`Unsupported os`) fell back to Grype for 16 HIGH, and Arch Linux (OS not detected) combined 2 Grype HIGH with 24 Trivy non-OS findings. Uncovered reports fail instead of passing, 2026-11-11 |
| Scanner validation hardening | **Passed** against real Docker and unit regressions: Trivy `--list-all-pkgs` now requires an `os-pkgs` result with a package-manager type and non-empty package inventory; Grype requires image target identity/layers/size, distro name and version, a valid database, and structurally complete matches. Reports with contradictory exit codes, missing inventory, or malformed matches fail. Rerun reproduced Debian 138, Fedora 16, and Arch 26 combined findings, 2026-11-11 |
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
| nftables runtime wiring (`scoped` profile) | Implemented in `DockerCli`: policy applied on container create, flushed and replaced on re-apply, removed before network deletion, cleanup errors propagate, a missing bridge aborts creation, and the profile comes from the engagement snapshot. Unit-tested with the scripted runner. Still prototype-level: no negative integration test, host input path and Docker embedded DNS uncovered, hostname entries advisory, and the policy gateway is not implemented (see M2 in `roadmap.md`) |
| VPN profile store and gateway lifecycle | Implemented; gateway image not built |
| Transparent VPN routing and kill switch | Not implemented |
| Restricted Docker broker + AI adapter | Not implemented |
| GUI runtime and commands | Phase 2-5 of the GUI program, 2026-11-12: the runtime lives in `src/haibox/gui/` (fixed specification, eligibility preflight, private credentials, verified stop-before-reset, bounded relay with peer authentication, explicit limits) and `haibox gui start|attach|stop|status` exist, but every command refuses while the GUI image is experimental, so the feature is not enabled. 28 runtime, 8 CLI, and 26 adversarial unit tests pass without Docker, plus 5 opt-in Docker integration tests; the runtime was exercised against real Docker on a disposable engagement with the scanned GUI image (prepare, verify, rotation, foreign-server refusal without signalling, stop cleanup). Real Wayland input remains unverified and needs a real Wayland session with input devices. Evidence: `docs/superpowers/poc/2026-11-12-gui-runtime-verification.md` |
| GUI / desktop | Production feature not enabled: the `haibox gui` commands exist and refuse while the GUI image is experimental. The 2026-11-11 readiness prototype passed on Fedora 44 X11 and headless Wayland with an engagement-bound Unix-socket relay, but the GUI image scan has 4 CRITICAL and 61 HIGH findings and Wayland input is unverified. The 2026-11-12 hardening pass added fail-closed network/scope preflight, canonical scope-file comparison, exact network-membership checks, private password/socket handling, credential rotation and removal, bounded relay cleanup, and a verified session replacement that refuses to reset the runtime, replace the credential, or start a second server until the previous server is confirmed gone. Covered by fake-runtime unit tests and disposable real-Docker re-runs. No `haibox gui` command, GUI `ContainerSpec` field, or catalog image. See `docs/superpowers/poc/2026-11-11-xpra-gui-readiness.md`. |

## Related Documentation

- [User Guide](user-guide.md)
- [Image Catalog](image-catalog.md)
- [Image Validation Evidence](image-validation.md)
- [Vulnerability Risk Register](vulnerability-risk-register.md)
- [Host Docker Review](host-docker-review.md)
- [Roadmap](roadmap.md)
