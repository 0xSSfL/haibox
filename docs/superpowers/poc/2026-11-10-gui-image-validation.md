# GUI image validation plan and evidence

**Status:** Disposable fixture built and measured; production image gate is
blocked.  
**Date:** 2026-11-11  
**Scope:** Determine whether an optional Xpra GUI image can meet HAIBOX's
existing build, verification, and vulnerability-scan requirements. This is a
design-review artifact, not a catalog image.

## Summary

- A reproducible disposable Fedora 44 fixture was added at
  [`gui-image/Dockerfile`](gui-image/Dockerfile). It installs the same direct
  Xpra package versions used by the 2026-11-10 proof of concept.
- The rebuilt image is functional at the package level, but the installed Trivy
  0.76.2 does **not support Fedora** and produced no vulnerability results. The
  scan is not clean; it is absent. This is a production blocker.
- Debian 13, the HAIBOX catalog base, has no `xpra` package candidate in the
  recorded snapshot. A Debian-based GUI image needs a reviewed third-party
  package source or a source build.
- The current `haibox image scan` adapter treats a zero exit code as success and
  does not reject unsupported-OS or empty reports. A Fedora-based image could
  therefore appear to pass without scan data. Fixing the adapter is a separate
  change and is not part of this branch.

## Fixture

| Item | Value |
|---|---|
| Path | `docs/superpowers/poc/gui-image/Dockerfile` |
| Base | `fedora:44@sha256:15da97ed9aa94dd3d92c3925eb89520f6c80e07ea7ee24cba848d1f8b6912b3e` |
| Direct packages | `xpra-6.5.4-1.fc44`, `xterm-411-1.fc44`, `xorg-x11-server-Xvfb-21.1.25-2.fc44`, `socat-1.8.1.3-1.fc44`, `python3-gobject-3.56.3-1.fc44.x86_64` |
| Build command | `docker --context haibox build -t haibox/gui-poc-validation:0.1.0 .` |
| Runtime user | UID/GID `1000:1000` |
| Labels | `haibox.poc=xpra-seamless`, `haibox.production=false` |
| Catalog status | Not cataloged; not published; not a production tag |

The direct package versions are pinned, but transitive dependencies resolve
from the Fedora 44 repositories at build time. The fixture is reproducible only
while those repositories retain the pinned versions; a production manifest would
need a full dependency lock or recorded package set.

## Measured evidence

| Check | Result |
|---|---|
| Build | Completed 2026-11-11 on Fedora 44 x86_64, Docker Engine 29.9.2 through the dedicated `haibox` context |
| Image ID | `sha256:41d34aad54acd6282598d5656f6ee91967fb60b13537dffdd2e3e99acb220c43` |
| Image size | 1,399,669,162 bytes |
| Installed RPMs | 502 |
| Direct versions | `xpra v6.5.4`, `XTerm(411)`, Xvfb 21.1.25, socat 1.8.1.3, Python GObject 3.56.3 |
| Original PoC image | `sha256:6bad2d1c3afba55fb66fc55f7786bd86f8576520427170fc6c101dfbe6c84816`, 1,163,045,221 bytes, 233 packages added |
| Display and isolation behavior | See [`2026-11-10-xpra-seamless.md`](2026-11-10-xpra-seamless.md); not re-tested during the rebuild |

The rebuilt image is larger than the original PoC image because the Fedora base
and transitive dependency set moved between builds. It is evidence for scanner
behavior, not a byte-for-byte reproduction of the PoC.

## Scanner evidence

Command:

```bash
trivy image --severity HIGH,CRITICAL --exit-code 1 --format json \
  --output /tmp/opencode/gui-poc-trivy.json \
  haibox/gui-poc-validation:0.1.0
```

Observed output:

```text
INFO    Detected OS    family="fedora" version="44"
WARN    Unsupported os family="fedora"
WARN    [report] Supported files for scanner(s) not found. scanners=[vuln]
```

Result: exit `0`, no `Results` entries, zero reported vulnerabilities. The
Trivy vulnerability database used was version 2, updated 2026-11-09.

**Interpretation:** this is an unsupported-OS result, not a clean scan. Do not
record the image as scanned or vulnerability-free. Grype was not installed, so
the fallback path was not evaluated.

### Why this matters for the HAIBOX gate

`ImageScanner.scan` prefers Trivy when present, checks only the process exit
code, and stores the output. Trivy returns success for an unsupported OS with no
findings. A Fedora-based GUI image can therefore pass the current adapter
without any vulnerability data. The adapter needs a separate fix and regression
test before any non-Debian image is trusted. This branch does not change it.

## Debian packaging check

Command:

```bash
docker --context haibox run --rm --entrypoint sh \
  debian:13-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2 -c '
    printf "%s\n" \
      "deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian/20261108T000000Z/ trixie main" \
      "deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian-security/20261108T000000Z/ trixie-security main" \
      > /etc/apt/sources.list
    apt-get update
    apt-cache policy xpra
  '
```

Observed:

```text
xpra:
  Installed: (none)
  Candidate: (none)
  Version table:
```

Debian 13 trixie does not ship the package in this snapshot. An optional GUI
image therefore cannot simply extend the current Debian catalog base with
`apt-get install xpra`.

## Options and gates

| Option | Benefit | Cost and risk | Decision |
|---|---|---|---|
| Debian 13 + xpra.org apt repository | Keeps the Debian scanner base | Adds a third-party signing key and repository; package vulnerability coverage is not proven; needs a pinned snapshot and review | Candidate, not approved |
| Debian 13 + Xpra source build | Keeps Debian base packages scannable | Build provenance, compiler dependencies, and a maintained patch stream; scanners cannot map the source build to distro advisories | Candidate, not approved |
| Fedora 44 + distro Xpra | Matches the tested functional pair | Trivy does not support Fedora; the current adapter can silently pass; catalog would need a scanner-compatible path | Blocked |
| No GUI image | Preserves the terminal-only default and current scan gate | No native-window feature | Valid default |

### Production image acceptance gates

- [ ] **G1:** Use a base and package source that the installed scanner supports,
      or extend scanner coverage with a reviewed, tested replacement.
- [ ] **G2:** Make `haibox image scan` fail on unsupported OS, empty results, and
      scanner errors instead of treating exit 0 as a pass; add regression tests.
- [ ] **G3:** Add a manifest with the base digest, Debian/Fedora snapshot or
      repository snapshot, direct versions, build args, and verify commands.
- [ ] **G4:** Record Trivy and Grype results for HIGH/CRITICAL findings, without
      `--ignore-unfixed`, global ignores, or package/Go-module suppressions.
- [ ] **G5:** Keep the image optional and separate from the terminal-only
      variants; do not add a production tag until G1–G4 pass.
- [ ] **G6:** Review image size, dependency closure, Xpra client/server version
      pairing, and startup/resource limits.
- [ ] **G7:** Close the security-review findings that require image or protocol
      testing, including disabled forwarding features and hostile streams.

The gate remains open. A successful window test or a package-level version check
does not change that status.

## Reproduction and cleanup

```bash
cd docs/superpowers/poc/gui-image
docker --context haibox build -t haibox/gui-poc-validation:0.1.0 .
trivy image --severity HIGH,CRITICAL --exit-code 1 \
  haibox/gui-poc-validation:0.1.0
```

The disposable image was removed after recording the evidence. The fixture
remains so the build and scanner result can be reproduced. Do not push the image
to a registry or add it to `images/`.

## Related records

- [Architecture proposal](../specs/2026-11-10-haibox-desktop-architecture.md)
- [Xpra seamless proof of concept](2026-11-10-xpra-seamless.md)
- [Security review](../reviews/2026-11-10-haibox-desktop-security-review.md)
- [Vendor research](../research/2026-11-10-desktop-vendor-research.md)
