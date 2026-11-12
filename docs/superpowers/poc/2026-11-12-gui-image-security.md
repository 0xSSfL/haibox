# GUI image security: research, remediation, and scan evidence

**Status:** A GUI image candidate with **zero** HIGH/CRITICAL findings is built
and verified; the production GUI is still not enabled.  
**Date:** 2026-11-12  
**Scope:** Phase 1 of the GUI production program — the image that the optional
GUI session runs in.  
**Related:** [ADR-0011](../../../adr/0011-gui-session-in-existing-runner.md),
[plan](../../../superpowers/plans/2026-11-12-gui-production-program.md),
[prototype evidence](../../../superpowers/poc/2026-11-11-xpra-gui-readiness.md)

## Summary

- The disposable Fedora 44 fixture carried **66 HIGH/CRITICAL findings**:
  50 in Pillow (5 CRITICAL, 45 HIGH) and 16 in PCRE2. Every one of them has a
  fix that exists upstream.
- Both clusters are closed by moving to a base whose packages carry the
  fixes: Pillow 13.0.0 and PCRE2 10.49. No ignore file, no
  `--ignore-unfixed`, and no self-approved exception was used.
- The rebuilt image scans clean through the hardened pipeline: Trivy reports
  `Unsupported os (fedora 46)`, the Grype fallback covers the OS, and the
  result is **0 HIGH/CRITICAL findings** with exit code 0.
- The base is **Fedora 46, which is still a pre-release snapshot** at the time
  of writing. The image must be rebuilt on the Fedora 46 stable release before
  it can be called production-qualifiable. This is the one qualification that
  the owner has to accept or reject.

## Findings on the previous fixture

Source: `haibox/gui-poc-validation:0.1.0` (Fedora 44, Xpra 6.5.4, 502 RPMs),
scanned with the hardened adapter on 2026-11-12.

| Severity | Count | Component | Finding | Fix | Status |
|---|---:|---|---|---|---|
| CRITICAL | 5 | `python3-pillow` 12.3.0 | CVE-2026-112403 (JPEG decoder writes a full-width scanline into a buffer sized for the requested draft scale), CVE-2026-112902, CVE-2026-96639, GHSA-8g5g-8vmr-9782, GHSA-v9pv-5gc8-w2m6 | 13.0.0 | Remediated by the base update |
| HIGH | 45 | `python3-pillow` 12.3.0 | Out-of-bounds reads and writes in the TIFF, GIF, PDF, MIC, APNG, and font decoders, use-after-free in the TIFF encoder, unbounded recursion and quadratic parsing in the PDF and GIF parsers, and a null-pointer dereference in `Image.merge()` | 13.0.0 | Remediated by the base update |
| HIGH | 16 | `pcre2` / `pcre2-syntax` 10.47-1.fc44.1 | CVE-2026-103111, CVE-2026-86145, CVE-2026-89156, CVE-2026-89157, CVE-2026-89158, CVE-2026-89160, CVE-2026-89161, CVE-2026-89162 | 10.49-1.fc44 | Remediated by the base update |

Exploitability note: the Pillow cluster is reachable from a GUI server. Xpra
decodes and encodes images on behalf of the client (window content, scaling,
and the image formats it negotiates), so the memory-safety issues in the
decoders are not theoretical for a server that accepts client-supplied image
data. The GUI session disables clipboard and file transfer, which removes the
most obvious path, but the fix is applied rather than argued away.

## Base and packaging research

| Base | Xpra server | Pillow | PCRE2 | Scanner coverage | Outcome |
|---|---|---|---|---|---|
| Debian 13 (catalog base) | **no package** | 11.1.0 | — | Trivy covers Debian | Rejected: no Xpra, and a source build of Xpra 6.5 needs a large -dev dependency set; Pillow would still be unfixed |
| Debian 12 (bookworm) | 3.1.3 (2021) | 9.x | — | Trivy covers Debian | Rejected: the Xpra 3.1 series predates the seamless server work, and Debian 12 left standard support in June 2026 |
| Ubuntu 24.04 LTS | 3.1.5 (2022) | 9.4 | — | Trivy covers Ubuntu | Rejected: the same ancient Xpra series, with a much older Pillow |
| Fedora 44 (stable) | 6.5.4 | 12.3.0 | 10.47 → 10.49 in updates | Grype fallback | Rejected: Pillow 13.0.0 is not in Fedora 44 |
| Fedora 45 (stable) | 6.5.4 (6.5.6 only in updates-testing) | 12.3.0 | 10.49 | Grype fallback | Rejected as the primary: Pillow 13.0.0 is not in Fedora 45 either |
| **Fedora 46** | **6.5.6** | **13.0.0** | **10.49** | Grype fallback | **Chosen**: every finding class is closed by distro packages |

Fedora is the only distribution that ships a supported Xpra server: the
upstream 6.5 series is packaged for Fedora 44, 45, and 46, while Debian and
Ubuntu are still on the 3.1 series from 2021/2022. That matters for more than
the version number — the file authentication module, the seamless server, and
the deny-by-default flags the GUI needs all exist in the 6.x series.

The scanner pipeline matters too. Trivy does not support Fedora and reports
`Unsupported os`; the hardened adapter already falls back to Grype and fails
closed when neither scanner can prove OS package coverage, and that fallback
was validated against a real Fedora image on 2026-11-11
([`image-validation.md`](../../../image-validation.md)). The GUI image
therefore scans through the same path as the existing catalog evidence.

## The candidate image

Definition: [`images/gui/Dockerfile`](../../../images/gui/Dockerfile) and
[`images/gui/manifest.yaml`](../../../images/gui/manifest.yaml), built with the
normal catalog tooling.

| Item | Value |
|---|---|
| Base | `fedora:46@sha256:78bb31de333664aa76c4bf54306791cd294c0bd4fbcfc4346e2286261de544c4` |
| Direct packages | `xpra-6.5.6-1.fc46`, `xterm-411-1.fc46`, `xorg-x11-server-Xvfb-21.1.26-1.fc46`, `socat-1.8.1.3-1.fc46` |
| Runtime user | UID/GID `1000:1000` (`haibox`), non-root |
| Installed RPMs | 376 (the previous fixture had 502) |
| Image size | 1.21 GB (the previous fixture had 1.40 GB) |
| Build | `uv run haibox image build gui` → `haibox/gui:0.1.0` |
| Verification | `uv run haibox image verify gui` → passed (manifest commands run as uid 65534 with no network) |
| Scan | `uv run haibox image scan gui` → **0 HIGH/CRITICAL**, exit 0 |
| Package inventory | [`images/gui/packages.lock`](../../../images/gui/packages.lock) |

The image is deliberately smaller than the prototype fixture: the GTK client
bindings (`python3-gobject`) are not needed on the server side, weak
dependencies are disabled, and the package manager caches are removed.

## Rejected alternative: rebuilding Pillow on a stable base

A stable-base alternative was built and rejected. On Fedora 45 the image would
carry the distro Pillow 12.3.0, so the fix would have to come from a package
that HAIBOX builds itself:

- the upstream Pillow 13.0.0 source distribution was fetched with a verified
  SHA-256 (`cdcd1ba2…be3510`) and packaged as an RPM by HAIBOX;
- the packaging path needed the Fedora RPM macros, a compiler toolchain, and
  the `pybind11` build dependency, and the first three attempts failed on
  missing build dependencies and on the `%pyproject_wheel` macro not accepting
  `--no-build-isolation`.

That path works, but it moves the Pillow security lifecycle from the Fedora
package maintainers to HAIBOX: every upstream Pillow release would need a
rebuild, and the image would carry a package no distribution signs. The
Fedora 46 base reaches the same fixed versions with signed distribution
packages. The rebuilt-Pillow route is recorded here so the decision can be
revisited when Fedora 46 is released or if a pre-release base is rejected.

## Qualifications that remain

| Qualification | State | Consequence |
|---|---|---|
| Fedora 46 is a pre-release snapshot | Open | The image is a candidate, not a production image. It must be rebuilt on the Fedora 46 stable release, and the scan repeated. |
| The base is a different distribution family from the Debian catalog | Accepted for the GUI | The GUI image cannot share `haibox/core:0.1.0` and is built from its own pinned base. |
| Trivy cannot scan Fedora | Accepted for the GUI | The Grype fallback covers the OS and is validated; the adapter still fails closed when neither scanner proves coverage. |
| Host client distribution | Open | The host Xpra client is not packaged; it is installed manually for now. |
| Image updates | Open | Fedora packages move; the image needs a rebuild and rescan on the normal catalog cadence. |

## What this does not do

- It does not enable the GUI. No `haibox gui` command ships with this change,
  and the image is not published.
- It does not change the container shape: the GUI image runs with the same
  deny-by-default `ContainerSpec` as every other runner.
- It does not close the M2 scope-enforcement milestone. A GUI session still
  requires the `isolated` profile and an empty external target scope.
- It does not claim that a pre-release base is production-quality.
