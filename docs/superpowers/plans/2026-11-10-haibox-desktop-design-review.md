# HAIBOX Desktop design-review release plan

> **For agentic workers:** This plan publishes a review package. It does not
> implement the production GUI feature. Use checkbox (`- [ ]`) tracking and do
> not start implementation tasks before the design gates are accepted.

**Goal:** Publish an evidence-backed design review for optional native Linux
application windows in HAIBOX, with a clear security verdict, a disposable image
validation record, and explicit production gates.

**Architecture:** Keep the proposal, research, proof of concept, security review,
and image validation under the internal `docs/superpowers/` tree. The production
CLI, runtime, catalog, and image definitions remain unchanged.

**Spec:** `docs/superpowers/specs/2026-11-10-haibox-desktop-architecture.md`

**Branch:** `design/haibox-desktop`, based on `main`.

## Global constraints

- Do not add `haibox gui` commands or GUI fields to `ContainerSpec` in this
  branch.
- Do not add a GUI image to `images/`, the image catalog, or a production tag.
- Do not mount a host X11/Wayland socket, Xauthority file, Docker socket, device,
  or arbitrary host path into any container.
- Do not publish ports or use privileged mode, host namespaces, or host network.
- Keep GUI sessions on the `isolated` network. Do not claim scope enforcement.
- Treat the Xpra proof of concept and disposable Fedora fixture as untrusted
  experimental evidence, not as a supported feature.
- Record every claim with a command, observed result, and limitation.
- Run `uv`, `make`, and tests from
  `/home/souaib/Work/haibox/.worktree/design/haibox-desktop`.
- Do not merge the pull request; it is a design-review request.

## Review focus

- Security review maps the proposal to the HAIBOX invariants, threat model, and
  managed-label rules, and names production blockers.
- Image validation demonstrates whether the GUI image can satisfy the existing
  scanner gate. It must not turn an unsupported-OS result into a clean scan.
- Acceptance gates distinguish a disposable PoC from a production feature.
- Public documentation says GUI is not implemented and does not imply support.

---

### Task 1: Record the architecture proposal and vendor research

**Files:**
- Create: `docs/superpowers/specs/2026-11-10-haibox-desktop-architecture.md`
- Create: `docs/superpowers/research/2026-11-10-desktop-vendor-research.md`

- [x] **Step 1: Record the candidate architecture, alternatives, threats, and blocked production plan**

The proposal selects Xpra seamless mode with an isolated per-engagement headless
display, a loopback relay over Docker Exec, no published ports, and no host
display socket. It keeps all production work behind a review gate.

- [x] **Step 2: Record primary-source vendor facts and local prior art**

The research covers Docker isolated networks and Exec streams, Xpra, Waypipe,
KasmVNC/noVNC, Fedora packaging, Exegol, and PortSwigger licensing. It separates
confirmed facts from transport inferences.

### Task 2: Record the Xpra proof of concept

**Files:**
- Create: `docs/superpowers/poc/2026-11-10-xpra-seamless.md`

- [x] **Step 1: Record transport, window, authentication, and lifecycle results**

The PoC connected a Fedora 44 Xpra 6.5.4 client to a container Xpra 6.5.4 server
through a localhost relay and non-TTY Docker Exec, rendered two xterm windows,
and passed detach/reconnect, stop/restart, workspace persistence, container
hardening, host-service, and cross-engagement negative checks.

- [x] **Step 2: Record limits and cleanup**

The record states that the relay was a hard-coded test harness, the image was
unscanned, only Fedora 44 X11/dwm was tested, and Burp/browser testing did not
occur. It also records that containers, networks, the image, and temporary files
were removed.

### Task 3: Complete the security review

**Files:**
- Create: `docs/superpowers/reviews/2026-11-10-haibox-desktop-security-review.md`

- [x] **Step 1: Review the design against HAIBOX invariants and the threat model**

The review covers display, container, network, identity, session, lifecycle, and
supply-chain boundaries.

- [x] **Step 2: Record blocking findings and required decisions**

The production blockers are scanner coverage, host-client/display-server attack
surface, relay authorization and lifecycle, forwarding-feature enforcement, and
unfinished scope enforcement. The verdict allows further isolated prototyping
but not production implementation.

### Task 4: Validate the disposable GUI image path

**Files:**
- Create: `docs/superpowers/poc/gui-image/Dockerfile`
- Create: `docs/superpowers/poc/2026-11-10-gui-image-validation.md`

- [x] **Step 1: Build a reproducible disposable Fedora 44 fixture**

The fixture pins the Fedora base digest and the direct Xpra package versions used
by the PoC, runs as UID/GID 1000, and is labelled as non-production.

- [x] **Step 2: Measure size, package count, and direct versions**

The rebuilt image is `sha256:41d34aad54acd6282598d5656f6ee91967fb60b13537dffdd2e3e99acb220c43`,
1,399,669,162 bytes, 502 RPMs, with Xpra 6.5.4 and the expected X11 tools.

- [x] **Step 3: Attempt the existing HIGH/CRITICAL Trivy gate**

Trivy 0.76.2 reports `Unsupported os family="fedora"` and returns exit 0 with no
results. The validation record explicitly classifies this as not scanned and
blocks the production image gate.

- [x] **Step 4: Check the Debian catalog base**

The recorded Debian 13 snapshot has no `xpra` package candidate. A production
Debian image needs a reviewed third-party source or a source build.

- [x] **Step 5: Remove the disposable image after recording evidence**

The image was removed after the size, version, and scanner evidence was captured.
The Dockerfile remains so the result can be reproduced.

### Task 5: Update public status without claiming the feature

**Files:**
- Modify: `README.md`
- Modify: `docs/verification-status.md`

- [x] **Step 1: State that GUI forwarding is not implemented**

The README warning says there is no supported GUI feature and no `haibox gui`
command; the limitations table records the narrow Fedora X11 PoC.

- [x] **Step 2: Record the PoC verification result and limits**

The verification table records the passing narrow checks, the unscanned image,
and the absence of production CLI or image changes.

### Task 6: Verify the review package

**Files:**
- Verify: all files changed in Tasks 1–5

- [x] **Step 1: Check whitespace and scope**

Run from the worktree root:

```bash
git diff --check
git status --short
git diff --stat
```

Result: no whitespace errors. The changes are limited to README, verification
status, internal review records, and the disposable fixture. No production CLI,
runtime, catalog, or image files changed.

- [x] **Step 2: Run repository tests, lint, and type checks**

Run:

```bash
make check
```

Result: Ruff passed, mypy found no issues in 40 source files, and pytest reported
294 passed and 2 integration tests skipped.

- [x] **Step 3: Build the public documentation strictly**

Run:

```bash
uv run mkdocs build --strict
```

Result: pass; the internal `docs/superpowers/` records remained excluded from the
public site.

- [x] **Step 4: Verify links and evidence references**

Result: a relative-link check over the modified public pages and all
`docs/superpowers/*.md` records found no missing targets. No public page claims
GUI support or a passing GUI image scan.

### Task 7: Commit, push, and open the review PR

**Files:**
- Create: a temporary PR body outside the repository

- [ ] **Step 1: Commit the review package with Conventional Commits**

Suggested commits:

```bash
git add docs/superpowers/specs/2026-11-10-haibox-desktop-architecture.md \
  docs/superpowers/research/2026-11-10-desktop-vendor-research.md
git commit -m "docs: propose isolated desktop architecture"

git add docs/superpowers/poc/2026-11-10-xpra-seamless.md \
  docs/superpowers/poc/2026-11-10-gui-image-validation.md \
  docs/superpowers/poc/gui-image/Dockerfile
git commit -m "docs: record desktop proof of concept and image validation"

git add docs/superpowers/reviews/2026-11-10-haibox-desktop-security-review.md \
  docs/superpowers/plans/2026-11-10-haibox-desktop-design-review.md
git commit -m "docs: review desktop security and acceptance gates"

git add README.md docs/verification-status.md
git commit -m "docs: record desktop design-review status"
```

- [ ] **Step 2: Push the branch and open a PR against `main`**

```bash
git push -u origin design/haibox-desktop
gh pr create --base main --head design/haibox-desktop \
  --title "docs: review isolated desktop design and image validation" \
  --body-file <file>
```

The PR body must include the summary and rationale, affected paths, exact
verification commands and results, completed and follow-up checklists, the
security verdict, and links to the architecture, PoC, security review, and image
validation records. Do not merge.

## Production acceptance gates (not part of this PR)

- [ ] Design review accepted by the maintainer.
- [ ] Host-client matrix includes Fedora X11, at least one Wayland session, and a
      second distribution.
- [ ] Production relay implements fixed engagement resolution, local-client
      authentication, backpressure, cancellation, child cleanup, and negative
      cross-engagement tests.
- [ ] Deny-by-default feature checks cover clipboard, file transfer, audio,
      camera, printing, notifications, tray, DBus, and remote command start.
- [ ] GUI sessions stay isolated; external targets wait for the M2 scope gate.
- [ ] Optional image has a pinned manifest, passes `image verify`, and records
      Trivy and Grype HIGH/CRITICAL results without suppressions.
- [ ] `image scan` rejects unsupported-OS and empty-result reports with tests.
- [ ] CLI actions resolve engagement IDs, check managed labels, and audit every
      state change.
- [ ] `docs/architecture.md`, `docs/threat-model.md`, an ADR, the user guide, and
      verification status are updated for the accepted production design.
