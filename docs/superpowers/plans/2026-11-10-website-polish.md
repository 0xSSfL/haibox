# HAIBOX Website Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix HAIBOX homepage rendering, navigation, toolkit accuracy, Quick Start responsiveness, and site footer without changing the product's visual identity or runtime behavior.

**Architecture:** Keep MkDocs Material and its native navigation. Render homepage icons from a local SVG sprite, group existing pages into five nav categories, and use one minimal Material footer partial for the HAIBOX brand links. Keep homepage content in its existing Markdown file and make the cards responsive with the current CSS layers.

**Tech Stack:** Python 3.11+, PyYAML, pytest, MkDocs Material, Markdown, HTML, CSS, SVG.

**Spec:** `docs/superpowers/specs/2026-11-10-website-polish-design.md`

## Global Constraints

- Keep the current HAIBOX navy and mint visual identity, animated 3D cube, illustrative terminal, typography, and User Guide layout.
- Use local SVG assets; do not add external JavaScript or CDN dependencies.
- Use exactly five top-level navigation groups: Home, Getting Started, Toolkits, Security, and Development.
- Preserve all documentation files and existing generated page URLs.
- Keep toolkit badges and displayed tools consistent with `images/*/manifest.yaml`, including tools inherited through the image's base image.
- Keep the Quick Start journey: install HAIBOX, configure Docker, and launch an offline engagement. Preserve the existing installation workflow.
- Keep visible warnings about unresolved HIGH/CRITICAL findings, default network isolation, incomplete VPN routing and kill switch, experimental scoped enforcement, and unimplemented AI and graphical workstation features.
- Keep the terminal explicitly illustrative; do not imply it executes commands or displays real results.
- Remove the animation pause control while preserving the CSS `prefers-reduced-motion` behavior.
- Do not change the CLI, Docker images, runtime, networking, firewall, or User Guide layout/content.
- Run `uv`, `make`, and tests from `/home/souaib/Work/haibox/.worktree/feat/site-polish`.
- Do not run Docker integration tests or modify security architecture.

## Review Focus

- A toolkit card shows a tool only when that tool exists in the manifest or its base image; `test_homepage_toolkit_cards_match_manifests` checks every card, tool tag, and status badge.
- Every homepage icon symbol resolves to a local SVG and the Markdown contains no literal Jinja include; `test_homepage_icons_use_local_svg_sprite` checks the icon IDs and source.
- Navigation keeps all current user-facing pages available and current URLs stable; `uv run mkdocs build --strict` checks configured pages and internal references, followed by an output link inventory. Internal `docs/superpowers/` plan records are excluded from the public site.
- Grid tracks, badges, and long Quick Start commands fit smaller viewports; inspect rendered screenshots at desktop, tablet, and mobile sizes when browser access is available.
- Alpha claims and motion accessibility remain accurate; Task 4 adds `test_homepage_preserves_security_disclosures_and_reduced_motion` before changing copy or controls, then checks warning text, illustrative demo label, and the reduced-motion stylesheet rule.

---

### Task 1: Commit the approved design record and implementation plan

**Files:**
- Create: `docs/superpowers/specs/2026-11-10-website-polish-design.md`
- Create: `docs/superpowers/plans/2026-11-10-website-polish.md`

- [x] **Step 1: Commit the approved design and plan**

```bash
git add docs/superpowers/specs/2026-11-10-website-polish-design.md docs/superpowers/plans/2026-11-10-website-polish.md
git commit -m "docs: plan HAIBOX website polish"
```

### Task 2: Fix homepage icons and manifest-backed toolkit cards with regression tests

**Files:**
- Create: `tests/unit/test_docs_site.py`
- Create: `docs/assets/icons.svg`
- Modify: `docs/index.md`
- Read: `images/*/manifest.yaml`

**Interfaces:**
- Tests treat each homepage toolkit card as an `<article class="toolkit-card" data-image="<manifest-name>">`.
- Tool tags use `<span class="toolkit-tag">`; the badge text/class maps to the manifest `status`.
- SVG references use `<svg><use href="assets/icons.svg#<symbol-id>"></use></svg>`.

- [x] **Step 1: Install the locked development and docs dependencies**

Run from the worktree root: `uv sync --locked --extra dev --extra docs`

Expected: sync completes from `uv.lock`; `uv run mkdocs --version` and `uv run pytest --version` both succeed.

- [x] **Step 2: Write `test_homepage_toolkit_cards_match_manifests`**

Parse all six image manifests with PyYAML, follow each `haibox/<base>` reference for inherited tools, then parse homepage cards. Assert the card names equal the manifest names, each displayed tag is present in the image's direct or inherited tool set, and badge class/text matches `active` or `experimental` status.

- [x] **Step 3: Write `test_homepage_icons_use_local_svg_sprite`**

Assert `docs/index.md` has no `{% include` expression, every `<use>` references a symbol ID declared in `docs/assets/icons.svg`, and the page contains a rendered SVG element for each icon-bearing feature, toolkit, Quick Start card, warning, and documentation link.

- [x] **Step 4: Run the new tests and confirm they fail for the expected current defects**

Run: `uv run pytest tests/unit/test_docs_site.py -q`

Expected: FAIL because the current page contains raw Jinja, mismatched tool tags, and lacks the new SVG sprite contract.

- [x] **Step 5: Commit the regression tests while they are red**

```bash
git add tests/unit/test_docs_site.py
git commit -m "test: cover HAIBOX website content accuracy"
```

- [x] **Step 6: Add the local SVG symbol sprite**

Define the required icons with `currentColor` fills, consistent `viewBox` dimensions, and no animation or external references.

- [x] **Step 7: Replace Jinja snippets with accessible SVG references**

Use decorative SVGs (`aria-hidden="true"`, `focusable="false"`) and local `use` references; remove all `{% include %}` expressions from the Markdown page.

- [x] **Step 8: Add semantic manifest identifiers and correct card content**

Remove Core `socat`; replace Network Security `tshark` and `bind9-dnsutils` with manifest tools; replace unsupported AD tools with `smbclient`, `ldapsearch`, `kinit`, and `nmap`; replace unsupported OSINT tools with `dnsrecon`, `exiftool`, `whois`, `subfinder`, and `httpx`; correct Full's selected tags. Preserve manifest status labels.

- [x] **Step 9: Run the regression tests and confirm they pass**

Run: `uv run pytest tests/unit/test_docs_site.py -q`

Expected: PASS for six cards, all displayed tools and statuses, and every local icon symbol.

- [x] **Step 10: Commit the icon and toolkit correction**

```bash
git add docs/index.md docs/assets/icons.svg
git commit -m "fix: render homepage icons and correct toolkit details"
```

### Task 3: Group navigation and add the branded footer

**Files:**
- Create: `overrides/partials/footer.html`
- Modify: `mkdocs.yml`
- Modify: `docs/index.md` (repair two raw HTML links to published URLs)
- Modify: `docs/stylesheets/extra.css`

**Interfaces:**
- `mkdocs.yml` has five top-level native navigation groups and retains every current page path.
- The footer links to the User Guide, homepage toolkit section, Threat Model, repository, and repository MIT license.
- `copyright` is the source for the footer bottom line; `extra.generator: false` suppresses the stock generator label.

- [x] **Step 1: Write navigation and footer regression tests**

Add `test_navigation_uses_five_groups_without_dropping_documents` to assert the five requested top-level labels, that every current user-facing Markdown page is listed, and each listed source path exists. Exclude the root README and internal `docs/superpowers/` planning records from that public page inventory. Add `test_footer_has_branded_links_and_copyright` to assert the five labeled footer links, normalized `base_url` paths, config-based copyright, custom theme directory, and disabled generator notice. Check homepage raw HTML links use published URLs rather than `.md` source paths.

- [x] **Step 2: Run the new tests and confirm they fail for the current navigation/footer**

Run: `uv run pytest tests/unit/test_docs_site.py -q`

Expected: FAIL because current navigation has many top-level pages and no branded footer override.

- [x] **Step 3: Reorganize the `nav` tree into the five requested categories**

Keep all current user-facing page paths and group detailed architecture, threat model, validation, verification, reports, runbooks, and ADRs under the appropriate category. Exclude the new internal `docs/superpowers/` planning records with MkDocs `exclude_docs` so they remain in the repository without becoming public site pages.

- [x] **Step 4: Configure and create the minimal footer override**

Set HAIBOX copyright text, disable the generator notice, set `theme.custom_dir: overrides`, and create an accessible branded footer with the tagline and five labeled links. Use `base_url` for local links and `repo_url` for repository links.

- [x] **Step 5: Add responsive footer styling in the existing stylesheet**

Use the current navy and mint palette, clear focus states, readable contrast, a compact mobile stack, and no animation.

- [x] **Step 6: Build strictly and inspect representative output pages**

Run: `uv run mkdocs build --strict`; inspect generated links and assets across Home, User Guide, and 404 output.

Expected: PASS; generated Home and User Guide pages contain the new footer; all five nav groups render; previous page URLs remain under their original paths.

- [x] **Step 7: Commit navigation and footer changes**

```bash
git add mkdocs.yml overrides/partials/footer.html docs/stylesheets/extra.css tests/unit/test_docs_site.py
git commit -m "docs: group navigation and brand the site footer"
```

### Task 4: Refine Quick Start and responsive layouts

**Files:**
- Modify: `docs/index.md`
- Modify: `docs/stylesheets/extra.css`
- Modify: `docs/stylesheets/landing-animation.css`
- Delete: `docs/javascripts/landing-animation.js`
- Modify: `mkdocs.yml`
- Test: `tests/unit/test_docs_site.py`

**Interfaces:**
- Quick Start remains three cards with copyable shell code blocks using the existing Material code-copy feature.
- The install card retains the existing release-script command; Docker and engagement commands are split into readable lines.
- No pause/resume control or animation JavaScript remains; CSS animation runs normally and stops under `prefers-reduced-motion: reduce`.

- [x] **Step 1: Write `test_homepage_preserves_security_disclosures_and_reduced_motion`**

Assert the homepage states alpha status, unresolved HIGH/CRITICAL findings, offline default, incomplete VPN routing/kill switch, experimental scoped enforcement, unimplemented AI/graphical workstation features, and illustrative terminal status. Assert the landing stylesheet retains its `prefers-reduced-motion` rule.

- [x] **Step 2: Run the new test and confirm it fails for missing warning copy**

Run: `uv run pytest tests/unit/test_docs_site.py::test_homepage_preserves_security_disclosures_and_reduced_motion -q`

Expected: FAIL because several alpha limitations are not stated on the homepage yet.

- [x] **Step 3: Replace the current Quick Start content with three consistently structured cards**

Use the local numbered SVG icons, links to detailed setup guidance, and fenced code blocks. Keep the install, Docker context, and offline engagement sequence intact.

- [x] **Step 4: Compact the security notice and replace the oversized CTA**

Keep visible alpha and authorization warnings, explicitly state the current scan/network/VPN/scope/AI/GUI limits, and use a modest text-forward User Guide link.

- [x] **Step 5: Remove the pause button and its JavaScript wiring**

Remove the homepage button and `extra_javascript` entry, delete the no-longer-needed script, and keep the existing reduced-motion CSS behavior.

- [x] **Step 6: Fix narrow viewport sizing and wrapping**

Use shrinkable grid tracks, allow toolkit headings and badges to wrap, prevent card/code overflow, wrap Quick Start code, maintain button spacing, and keep the existing terminal responsive behavior.

- [x] **Step 7: Build strictly and run the homepage regression tests**

Run: `uv run mkdocs build --strict && uv run pytest tests/unit/test_docs_site.py -q`

Expected: PASS; generated Quick Start contains three fenced shell blocks and uses the enabled Material `content.code.copy` feature; no raw Jinja, all six accurate toolkit cards, compact warning, and no pause control. The browser host was unavailable, so runtime copy buttons and visual layout were not inspected.

- [x] **Step 8: Commit the Quick Start and responsive fixes**

```bash
git add docs/index.md docs/stylesheets/extra.css docs/stylesheets/landing-animation.css mkdocs.yml tests/unit/test_docs_site.py
git rm docs/javascripts/landing-animation.js
git commit -m "fix: improve HAIBOX quick start responsiveness"
```

### Task 5: Verify the complete site and prepare the pull request

**Files:**
- Verify: all files changed in Tasks 1–4
- Create: a temporary PR body outside the repository

- [x] **Step 1: Run the strict docs build and inspect generated HTML**

Run: `uv run mkdocs build --strict`. Search every generated HTML page for `{% include`; inspect the home page for SVG/use elements and the footer; inspect all generated nav links and copied local assets.

Expected: no literal Jinja, all local SVG references resolve, the footer and nav appear on Home and documentation pages, and the generated page paths match the existing source URLs.

- [x] **Step 2: Run the repository test, lint, and type-check gate**

Run: `make check`

Expected: Ruff, mypy, and all unit tests pass. Do not run integration tests or Docker commands.

- [x] **Step 3: Attempt rendered browser checks or record the browser limitation**

Capture the requested Home hero, Quick Start, footer, desktop navigation, mobile navigation, and User Guide screenshots; inspect widths around 1280 px, 768 px, and 375 px, both palette modes, and reduced-motion preference.

The CUA browser host was unavailable. No rendered screenshots were captured and no visual PASS is claimed; generated HTML and responsive CSS received static checks only.

- [x] **Step 4: Confirm scope and working tree**

Run: `git diff --check`, `git status --short`, and `git diff --stat`.

Expected: only the planned website, test, spec, and plan files changed; no CLI, image, runtime, or security architecture changes.

- [ ] **Step 5: Push the feature branch and open a focused PR against `main`**

Use a Conventional Commit summary for the PR title. The body must cover behavior and rationale, affected paths, exact verification results, completed/follow-up checklist, and a link to this design record. Do not merge.
