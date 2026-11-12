# HAIBOX GUI production program — baseline and plan

**Status:** Program started; the GUI image gate is still closed.  
**Date:** 2026-11-12  
**Baseline:** `main` at `73aa4cf` (PR #11 merged)  
**Decision record:** [ADR-0011](../../adr/0011-gui-session-in-existing-runner.md)

This plan continues the GUI work from the merged Xpra prototype towards an
optional, production-quality GUI capability. It does not enable the GUI, does
not publish an image, and does not merge anything on its own. Each phase lands
on its own branch with a Draft pull request and recorded evidence.

## Phase 0 — Baseline (this document)

| Item | Observed value |
|---|---|
| Baseline commit | `73aa4cf` — merge of PR #11 (`design/xpra-gui-readiness`) |
| PR #11 state | Merged 2026-11-12, merge commit `73aa4cf` |
| Last correction in the merge | `84e2f2e` — refuse unknown session states and align credential docs |
| Local gate | `make check`: **392 passed, 2 skipped** (integration tests are opt-in), `ruff check .` clean, `mypy src` clean on 40 source files |
| Docker | Engine 29.9.2 client and server, dedicated `haibox` context on `unix:///var/run/docker.sock` |
| Host | Fedora Linux 44 x86_64, X11 `:0`, dwm, `XDG_RUNTIME_DIR=/run/user/1000` |
| Host Xpra client | 6.5.4, extracted from the Fedora RPM into `/tmp` (no host package installed) |
| Scanners | Trivy 0.76.2 and Grype 0.121.3 (Grype installed to `~/.local/bin` from the recorded tarball) |
| GUI fixture image | `haibox/gui-poc-validation:0.1.0`, disposable, not cataloged, not published |
| Fixture scan | 4 CRITICAL and 61 HIGH (Grype, Fedora 44); Trivy reports `Unsupported os` for Fedora and needs the Grype fallback |

### Environment notes

- The repository checkout at `/home/souaib/Work/haibox` had a stale `.venv`
  whose interpreter pointed at another project (`/home/souaib/Work/redoubt`).
  `uv sync --locked --extra dev` did not repair it because the package set was
  already present; removing `.venv` and re-syncing restored the gate. This is a
  local environment defect, not a repository defect.
- The dedicated `haibox` Docker context points at the same local daemon as
  `default`. Only HAIBOX-managed containers and disposable GUI engagements are
  created there; an unrelated `admin_ui` container is left untouched.

### Missing qualifications at the baseline

| Qualification | State | Effect on the program |
|---|---|---|
| GUI image vulnerability gate | **Blocked** — 4 CRITICAL / 61 HIGH on the Fedora 44 fixture | Phase 1 must remediate or produce an explicit blocked report; no production image may be exposed |
| Real Wayland input | **Not tested** — only a headless Weston surface was proven | Phase 4 cannot claim Wayland support; needs a real Fedora Workstation Wayland session |
| M2 scope enforcement | **Not implemented** — the `scoped` profile is a prototype | GUI sessions stay restricted to `isolated` with an empty external scope |
| Host-client packaging | **Undecided** — no Debian/Ubuntu client distribution | Phase 4 documents manual installation only |
| Audit integration for GUI lifecycle | **Missing** — the prototype does not write audit entries | Phase 2/3 must add audit events before any GUI command ships |
| Resource limits for the GUI server | **Missing** — the prototype inherits the runner limits only | Phase 2 must define explicit CPU, memory, process, and session limits |

### Documentation corrections in this phase

- `AGENTS.md` claimed that "the gate is open for every one" of the six catalog
  images. The gate decision is recorded for every image, but every image still
  carries unresolved HIGH/CRITICAL findings, so the release gate is red. The
  sentence now says that, so it cannot be read as "the images pass".

## Phase 1 — GUI image security (priority: critical)

Goal: a maintainable, minimal, digest-pinned GUI image whose remaining
findings are understood, triaged, and either remediated or explicitly reported
as blocked.

1. Research supported bases and Xpra packaging, upstream releases, and scanner
   coverage for each candidate.
2. Compare the candidates without assuming either is safer.
3. Build the candidate in the disposable environment and scan it with the
   hardened `haibox image scan` pipeline.
4. Remediate by updating, replacing, or removing dependencies where feasible.
5. Record every remaining finding with severity, component, fix availability,
   exploitability, and status. No blanket ignores, no `--ignore-unfixed`, no
   self-approved exceptions.

Exit: a verified image with zero policy-blocking findings, or an explicit
blocked report that names the owner decision required.

## Phase 2 — Production GUI runtime

Move the validated prototype into `src/haibox/gui/`: fixed validated session
specifications, engagement-bound lifecycle, Unix-domain relay, peer
authentication, password generation/rotation/revocation, verified
stop-before-reset, foreign-server refusal, bounded handling, explicit
resource limits, and structured errors with audit events. The canonical scope
comparison and exact Docker network membership checks from PR #11 are
preserved.

## Phase 3 — CLI

`haibox gui start|attach|stop|status` with exact engagement identity, isolated
network, empty external scope, and an approved GUI image identity. If Phase 1
or Phase 2 is blocked, the commands stay explicitly disabled with no
experimental bypass.

## Phase 4 — Compatibility and packaging

Native Xpra windows on a supported Fedora X11 desktop, real Fedora Workstation
Wayland input (keyboard, pointer, focus, resizing, reconnect), the supported
host/server version matrix, `haibox doctor` diagnostics, and Debian/Ubuntu
host-client packaging notes.

## Phase 5 — Adversarial testing

Malformed, oversized, truncated, delayed, and hostile protocol streams;
authentication failures, credential reuse, revocation, and rotation;
cross-engagement isolation and label manipulation; forwarding-feature bypass
attempts; network isolation and unauthorized destinations; crashes, freezes,
disconnects, timeouts, and concurrency; resource exhaustion and cleanup after
unexpected termination; and secret leakage through processes, logs, runtime
directories, or audit events. Every negative test must be executable, and
real-Docker evidence is required where it applies.

## Phase 6 — Independent review and acceptance

Full regression suite, Ruff, mypy, image build/inventory/scan reproducibility, a
fresh independent security review of the exact final code, resolution of all
confirmed findings, and documentation that separates prototype results from
production-qualified behaviour.

## Phase 7 — Delivery

A consolidated report: phases completed, pull requests and commit SHAs, test
totals and skipped-test explanations, Docker and desktop evidence, remaining
vulnerability findings and their dispositions, independent review results, the
dependency on the M2 scope-enforcement milestone, the unresolved blockers with
their precise next action, and a recommendation for owner review.
