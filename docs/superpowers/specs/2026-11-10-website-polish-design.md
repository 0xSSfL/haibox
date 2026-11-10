# HAIBOX Website Polish Design

## Intent

Make the existing HAIBOX documentation site readable, accurate, and consistent
across screen sizes. Keep its navy and mint visual identity, animated cube,
illustrative terminal, and User Guide layout while fixing the reported rendering,
navigation, Quick Start, and footer issues.

## Goals

- Replace literal Jinja expressions in `docs/index.md` with local SVG icons.
- Organize all currently navigated documents under five native Material
  navigation groups: Home, Getting Started, Toolkits, Security, and Development.
- Keep the current documentation files and their output URLs.
- Make all six homepage toolkit cards accurately reflect their manifest status
  and only show tools present in each image, including inherited base-image
  tools where appropriate.
- Add a regression test that compares homepage card tools and status badges with
  `images/*/manifest.yaml`.
- Make Quick Start a consistent three-card layout with short, copyable commands,
  working links to setup guidance, and a compact, visible alpha warning.
- Replace the oversized documentation CTA with a small text-forward link.
- Add an accessible, responsive HAIBOX footer to every page using a minimal
  Material partial override, configured copyright, and disabled generator
  notice.
- Remove the animation pause button and its JavaScript; retain the CSS
  `prefers-reduced-motion` behavior. The cube and terminal remain unchanged.
- Keep the terminal labeled as illustrative and retain explicit warnings about
  dependency findings, default network isolation, incomplete VPN routing and
  kill switch, experimental scoped enforcement, and unimplemented AI and
  graphical workstation features.

## Non-goals and anti-goals

- No changes to the CLI, Docker images, runtime, networking, firewall, or
  installation workflow.
- No changes to the User Guide content or layout.
- No claim that images are vulnerability-free or fully security-verified.
- No removal of documentation, URL migrations, external JavaScript, CDN assets,
  or decorative footer animation.
- No redesign of the hero, cube, terminal, typography, or color palette.

## Constraints

- Use the existing locked MkDocs Material dependency and native navigation.
- Keep all new assets local to the documentation site.
- Use the existing `content.code.copy` feature for Quick Start command blocks.
- Preserve the documented alpha and authorization boundaries.
- Work on a dedicated branch in the project-local `.worktree/` directory.

## Approaches

1. **Local SVG sprite (selected).** Reference static symbols from one local SVG
   sprite in the homepage markup. This works in the current raw HTML without
   expanding Markdown parsing across the page, avoids Jinja in Markdown, and
   adds no runtime dependency.
2. **Material icon shortcodes.** Enable Markdown parsing on selected HTML
   wrappers and place icon shortcodes there. This uses Material's built-in
   icon set but requires careful Markdown-in-HTML boundaries around existing
   raw markup. Local SVGs were selected for simpler, predictable output.

For the footer, Material's `copyright` and `extra.generator` settings cover the
copyright line and stock generator notice. They do not provide the requested
brand, tagline, and labeled links, so a single `overrides/partials/footer.html`
will provide that layout while leaving the rest of the theme intact.

## Implementation decisions

- `mkdocs.yml` will contain exactly five top-level groups. Existing source paths
  stay unchanged, so generated URLs remain stable.
- Homepage cards will be semantically marked with their manifest image names.
  Tests will parse card tool tags and status labels and compare them to each
  manifest plus any tools inherited through the image's base image.
- Quick Start installation remains the existing release-script workflow. Docker
  setup and engagement commands will be split across short, copyable lines.
- The homepage alpha callout will state the current limitations plainly. The
  architecture section heading will avoid implying all security findings are
  resolved.
- The footer links will use the current site base URL for documentation pages
  and the repository URL for GitHub and the MIT license.
- Responsive fixes will constrain grid tracks, let headings and badges wrap,
  wrap Quick Start code, and keep the existing terminal's small-screen behavior.
- Verification will include strict MkDocs output checks, repository tests and
  lint, static link/asset checks, and browser screenshots if the browser surface
  is available. If it is unavailable, visual verification will be reported as
  incomplete.

## Files expected to change

- `mkdocs.yml`
- `docs/index.md`
- `docs/assets/icons.svg`
- `docs/stylesheets/extra.css`
- `docs/stylesheets/landing-animation.css`
- `docs/javascripts/landing-animation.js` (remove after its control is removed)
- `overrides/partials/footer.html`
- `tests/unit/test_docs_site.py`

No production Python module or Docker image file will change.
