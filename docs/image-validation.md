# Image validation: Web Security

This document records how the Web Security image is built, verified, scanned,
and probed. Results are appended for each validated build; do not treat a
procedure as a result.

## Build inputs

| Input | Value |
|---|---|
| Image | `haibox/web-security:0.1.0` |
| Base | `debian:13-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2` |
| Debian snapshot | `20261108T000000Z` via `snapshot-cloudflare.debian.org` |
| Go builder | `golang:1.26-bookworm@sha256:23ce71337b726608afb1bc00986e630a05034a87a87ea1fc2cd1ae5cf33387eb` |
| Nuclei templates | commit `79fb682760ab3d5b0e22afbb44709353cbebf023` |
| Go module requirements | `images/web-security/gomod/<tool>.go.mod` and `.go.sum`, committed |

The Cloudflare snapshot mirror is used because `snapshot.debian.org` returned
`504 Gateway Timeout` for package indices during the first attempts. It serves
the same pinned snapshot; apt still verifies the signed `InRelease` metadata.

The apt packages are installed in two layers (base tools, then network tools).
Installing the full set in one BuildKit layer made `apt-get` grow past 6 GB
anonymous RSS and triggered a host OOM; the same set installs well under a
2 GB cap when split or run in a plain container. The Go stage sets
`GOMAXPROCS=2` and `-p=2` to limit parallel compile memory.

### Go tool build inputs

The Go tools are built from source, not from the upstream release archives. The
upstream releases pin vulnerable transitive module versions in their own
`go.mod`, so `images/web-security/gomod/` holds the patched requirement set for
each tool and is the pinned build input:

| Tool | Release | Module | Bumped requirements |
|---|---|---|---|
| ffuf | `v2.3.0` | `github.com/ffuf/ffuf/v2` | `golang.org/x/net v0.62.0`, `brotli v1.2.7` |
| gobuster | `v3.8.2` | `github.com/OJ/gobuster/v3` | `golang.org/x/net v0.62.0`, `x/crypto v0.59.0`, `x/sys v0.50.0` |
| nuclei | `v3.11.1` | `github.com/projectdiscovery/nuclei/v3` | `x/net v0.62.0`, `x/crypto v0.59.0`, `x/text v0.44.0`, `x/mod v0.42.0`, `x/sys v0.50.0`, `compress v1.20.2`, `brotli v1.2.7`, `goldmark v1.7.17`, `kin-openapi v0.149.0`, `go-git/v5 v5.19.2`, `go-jose/v4 v4.1.6`, `grpc v1.84.0` |
| httpx | `v1.12.0` | `github.com/projectdiscovery/httpx` | `x/net v0.62.0`, `x/crypto v0.59.0`, `x/text v0.44.0`, `x/sys v0.50.0`, `compress v1.20.2`, `brotli v1.2.7`, `goldmark v1.7.17` |
| subfinder | `v2.17.0` | `github.com/projectdiscovery/subfinder/v2` | `x/net v0.62.0`, `x/crypto v0.59.0`, `x/text v0.44.0`, `x/sys v0.50.0`, `compress v1.20.2`, `brotli v1.2.7`, `goldmark v1.7.17` |
| katana | `v1.8.0` | `github.com/projectdiscovery/katana` | `x/net v0.62.0`, `x/crypto v0.59.0`, `x/text v0.44.0`, `x/sys v0.50.0`, `compress v1.20.2`, `brotli v1.2.7`, `goldmark v1.7.17`, `pgx/v5 v5.9.0` |
| dalfox | `v2.13.0` | `github.com/hahwul/dalfox/v2` | `x/net v0.62.0`, `x/crypto v0.59.0`, `x/text v0.44.0`, `x/mod v0.42.0`, `x/sys v0.50.0`, `echo/v4 v4.16.1` |

The source comes from the Go module proxy, which is immutable and verified
against the Go checksum database. The build copies the committed requirement
files over the upstream ones and then asserts the module metadata of the
resulting binary: every fixed version must be present, and the vulnerable
version must be absent. The build fails rather than shipping a binary that
does not satisfy the assertion.

`go mod tidy` must never run in the image build. The tools do not import the
bumped modules directly, so tidy drops the upgrades and silently restores the
vulnerable versions.

## Build and verify

```bash
uv run haibox image build web-security
uv run haibox image verify web-security
```

`image verify` runs each manifest `verify` command in a restricted ephemeral
container: read-only root filesystem, `--cap-drop ALL`, no network, non-root
user. A missing tool or a version mismatch fails the command.

## Network isolation probe

The integration test creates a real engagement container and network, then
attempts real connections:

```bash
HAIBOX_RUN_INTEGRATION=1 uv run pytest -q tests/integration/test_docker_smoke.py
```

It checks, from inside the runner:

- no default route and no global IPv6 address;
- external DNS resolution fails;
- TCP/22, TCP/5432, and TCP/5355 on the host LAN address fail;
- TCP/22 and TCP/5432 on every global IPv4 address on the Docker host fail;
- the link-local metadata address fails;
- `1.1.1.1:443`, `8.8.8.8:53`, and a public IPv6 destination fail;
- an HTTP request to a public host fails at DNS;
- the network reports `gateway_mode_ipv4=isolated`,
  `gateway_mode_ipv6=isolated`, and no IPAM gateway;
- the host has no IPv4 address on the bridge interface;
- container-to-container TCP and Docker name resolution on the engagement
  network still work.

The last item is the authorized lab-target path. The test does not claim scope
enforcement: a tool can still contact any target on the engagement bridge.

## Scan and suppression verification

```bash
uv run haibox image scan web-security
```

`haibox image scan` runs Trivy with `--severity HIGH,CRITICAL` and the
image-local `images/<name>/trivyignore.yaml`. It exits non-zero on any remaining
finding.

A scan also has to prove it covered the image's OS packages. Trivy reports
Fedora as unsupported and does not detect Arch Linux as an OS; both cases still
exit `0`. HAIBOX parses the report instead of trusting the exit code:

- Trivy coverage requires a complete OS identity and an `os-pkgs` result with a
  package-manager type and a non-empty package inventory (`--list-all-pkgs`). An
  empty report is not accepted as proof that the image is package-free.
- When Trivy is not covered and Grype is installed, the scan falls back to
  Grype. Trivy findings and operational errors survive the fallback and cannot be
  cleared by a clean Grype report.
- Grype coverage requires a `matches` list, an image source target with identity,
  layers, and content size, an identified distro name and version, a valid
  vulnerability database with no reported error, and structurally complete
  matches.
- Exit codes must agree with the report: Trivy accepts `0`/`1`, Grype accepts
  `0`/`2`. A code that contradicts the findings, or any unexpected code, fails
  the scan even when it was previously treated as success.
- An empty, unparseable, uncovered, or contradictory report fails the scan; it is
  never a pass.

### Scanner coverage validation (2026-11-11)

Run against a real Docker endpoint with Trivy 0.76.2 and Grype 0.121.3:

| Image | Trivy | Fallback | Result |
|---|---|---|---|
| `haibox/core:0.1.0` (Debian 13.7) | Covered | Not used | 138 HIGH/CRITICAL; gate red |
| `fedora:44` | `Unsupported os` | Grype `fedora 44` | 16 HIGH, 8 Medium; gate red on 16 HIGH |
| `archlinux:latest` | OS not detected | Grype `archlinux 20261108.0.623074` | Grype 2 High; Trivy still reported 24 HIGH/CRITICAL non-OS findings; gate red on 26 combined |

Rerunning the adapter after the fail-closed validation change reproduced the
same results, so the stricter checks did not hide or invent findings. Unit
regressions additionally reject an OS-only Trivy report, an empty or malformed
package inventory, a Grype report without target/database evidence, a malformed
match, and exit codes that contradict the parsed findings.

### GUI image scan (2026-11-12)

The GUI image is a Fedora image, so Trivy reports `Unsupported os` and the
Grype fallback covers the OS.

| Image | Trivy | Fallback | Result |
|---|---|---|---|
| `haibox/gui:0.1.0` (Fedora 46) | `Unsupported os` | Grype `fedora 46` | 0 HIGH/CRITICAL; gate green |

The previous Fedora 44 GUI fixture reported 66 HIGH/CRITICAL findings (50 in
Pillow, 16 in PCRE2). Every one of them is fixed upstream, and the rebuilt
image carries the fixed packages (`python3-pillow` 13.0.0, `pcre2` 10.49), so
no ignore file, no `--ignore-unfixed`, and no exception was needed. The
remediation and the rejected alternatives are recorded in
[`superpowers/poc/2026-11-12-gui-image-security.md`](superpowers/poc/2026-11-12-gui-image-security.md).

The image is still **experimental**: Fedora 46 is a pre-release snapshot at the
time of the scan, so the image must be rebuilt on the stable release before it
can be called production-qualifiable.

The Fedora and Arch runs confirm that the fallback covers the OS and that the
gate fails on real findings instead of passing on an empty Trivy report. Trivy
still scans language packages when it cannot scan OS packages, so the fallback
keeps those findings; the combined count can overlap but never clears a finding.
These base-image findings are not suppressed; they are the current blocker for
a Fedora or Arch desktop image.

Findings that cannot be fixed with the current upstream inputs are analysed
individually in
[`docs/vulnerability-risk-register.md`](vulnerability-risk-register.md). They
are not added to the ignorefile; the gate stays red until a newer Debian
snapshot or upstream tool release removes them.

To verify the suppressions against raw and filtered output:

```bash
scripts/verify-trivy-suppressions.sh haibox/web-security:0.1.0
```

Set `TRIVY_BIN` if `trivy` is not on `PATH`.

The script scans twice (raw and with `--ignorefile`), then fails unless all of
the following hold:

- HIGH/CRITICAL vulnerability findings are identical in both reports;
- no secret findings remain in the filtered report;
- every removed secret finding matches a rule ID and path declared in the
  ignorefile.

A negative test copies a fixture key to a non-fixture path; that copy must
still be reported, proving the suppression is path-scoped and not rule-wide.
The script itself is checked against synthetic reports: a suppressed fixture
path passes, a non-fixture path fails, and a changed vulnerability set fails.

## Results

### 2026-11-13 Web Security Go-tool rebuild

The upstream Go releases pin the vulnerable transitive module versions in their
own `go.mod`, so a tool version bump cannot remove the findings. This rebuild
compiles every Go tool from its pinned upstream release with the affected
modules replaced by their fixed versions, using the committed requirement sets
described in [Go tool build inputs](#go-tool-build-inputs).

| Check | Result |
|---|---|
| Build | Passed; `haibox/web-security:0.1.0` |
| Image ID / manifest-list digest | `sha256:c9c80a11a699417519d532c450c1d9f14536c3834b84d3de872689458e191d0a` |
| Build assertions | Passed; 89 module-metadata assertions plus a sweep that rejects 30 previously vulnerable module versions |
| `image verify` | Passed; all 15 pinned tools run successfully in a restricted non-root container |
| In-image smoke test | Passed; 7 version checks and 6 functional checks against a local target |
| Trivy HIGH/CRITICAL, baseline image | 227 findings: 3 CRITICAL, 224 HIGH |
| Trivy HIGH/CRITICAL, rebuilt image | 147 findings: 0 CRITICAL, 147 HIGH |
| Grype HIGH/CRITICAL, baseline image | 271 (39 CRITICAL, 232 HIGH) of 675 matches |
| Grype HIGH/CRITICAL, rebuilt image | 218 (28 CRITICAL, 190 HIGH) of 590 matches |
| Go binaries with a Trivy finding | 7 of 7 before, 0 of 7 after |
| Grype advisories removed | 46 distinct advisories removed, 0 added |
| `haibox image scan` | Exit 1; 147 HIGH/CRITICAL remain, so the gate stays red |

The comparison is a like-for-like one: the previous image was preserved as
`haibox/web-security:0.1.0-baseline-p0` (`2543840d4ade`) and both images were
scanned back to back with the same scanner database, so the difference is the
image and not the advisory feed.

Trivy findings per target:

| Target | Baseline | Rebuilt |
|---|---:|---:|
| Debian 13.7 packages | 145 | 145 |
| `usr/local/bin/dalfox` | 26 | 0 |
| `usr/local/bin/gobuster` | 18 | 0 |
| `usr/local/bin/nuclei` | 15 | 0 |
| `usr/local/bin/ffuf` | 10 | 0 |
| `usr/local/bin/katana` | 5 | 0 |
| `usr/local/bin/httpx` | 3 | 0 |
| `usr/local/bin/subfinder` | 3 | 0 |
| `dirsearch` `native/Cargo.lock` | 2 | 2 |
| **Total** | **227** | **147** |

The Debian layer is unchanged, so the 145 remaining OS findings are the same
dependency debt as before; every finding that the rebuild could remove is
gone. The three CRITICAL findings were removed, not suppressed:
`CVE-2026-118264` (`github.com/labstack/echo/v4` in `dalfox`),
`CVE-2026-33815` and `CVE-2026-33816` (`github.com/jackc/pgx/v5` in `katana`),
plus `CVE-2026-84304` and `CVE-2026-84445` (`google.golang.org/grpc` in
`nuclei`) and 75 further HIGH findings disappear from the raw report because
the rebuilt binaries no longer contain the affected module versions.

Grype confirms the same direction from its own database: 675 → 590 matches,
271 → 218 HIGH/CRITICAL, and the OS layer is identical in both runs (579
matches). The two scanners do not agree on the severity of every finding, so
the counts are not comparable to each other; only each scanner's own
before/after pair is. Three advisories remain in the rebuilt binaries and have
no fix available: `github.com/labstack/echo/v4` (the fix ships only on the
`v5` module path), the deprecated `golang.org/x/crypto/openpgp` package, and
the Go standard library `go1.26.10` (fixed in `go1.26.11`). They are analysed
in [`docs/vulnerability-risk-register.md`](vulnerability-risk-register.md).

`osint` and `full` are built `FROM haibox/web-security:0.1.0`, so they inherit
the rebuilt tools on their next build. Their recorded scan baselines predate
this rebuild and stay stale for the Go modules until then.

### 2026-11-08 rebuild (Debian 13 trixie, snapshot 20261108)

| Check | Result |
|---|---|
| Build | Passed; `haibox/web-security:0.1.0` |
| Image ID / manifest-list digest | `sha256:5dfddb51e8dbfb716c8a9d341434f9da9b2c099a4873440d01e39c96f520b9aa` |
| `image verify` | Passed; all 15 pinned tools run successfully in a restricted non-root container |
| Integration: container shape | **PASSED** |
| Integration: network isolation | **PASSED** |
| Trivy HIGH/CRITICAL | **FAILED (open)** — 165 findings: 3 CRITICAL, 162 HIGH; 83 OS-package, 82 Go/Cargo-module |
| Suppressed findings | 25 secret findings removed, 0 remaining; 0 vulnerability findings removed |
| Suppression scope check | **PASSED** — all removed secrets matched a declared rule and fixture path; a copied key at `/real/leaked.key` was still reported |
| Network isolation probe | **PASSED** for the `isolated` profile; the legacy `internal` profile was removed (ADR-0009) |

The image was rebuilt while resolving the OSINT dependency. The digest above is
the current local artifact. A fresh raw/filtered scan confirmed the same 165
findings (3 CRITICAL, 162 HIGH), with 25 secret findings removed by the scoped
ignore file. Future dependent builds should use `--reuse-dependencies` when the
scanned Web Security tag is already present, so the evidence digest does not
change.

This rebuild moved from snapshot `20261101T000000Z` to `20261108T000000Z`,
which provides `ruby3.3 3.3.13-0+deb13u1` and removes 24 findings. It also:

- removed `dnsutils`/`bind9-dnsutils`, which pulled `liblmdb0` and `libxml2`
  (13 findings, including 4 CRITICAL, with no fixed Debian version);
- removed `wget`, which duplicated `curl` and carried 2 findings;
- upgraded `dalfox` from `v2.9.2` to `v2.13.0`;
- pinned `cryptography==50.0.0` and `pyopenssl==26.4.0` in the `dirsearch`
  virtual environment;
- purged `pipx` and `python3-venv` after the Python tool installs.

`dig` is no longer bundled. Use `getent hosts`, `nslookup` from a tool that
ships its own resolver, or a dedicated network image when DNS tooling is needed.

Vulnerability concentration (filtered report):

- OS packages (83): `libpython3.13-minimal`/`libpython3.13-stdlib`/`python3.13`
  (20 combined), the `util-linux` family (`bsdutils`, `libblkid1`, `libmount1`,
  `libsmartcols1`, `libuuid1`, `login`, `mount`, `util-linux`), `libexpat1`,
  `libsqlite3-0`, `curl`/`libcurl`, and `libpcap0.8t64`;
- Go/Cargo modules (82): `golang.org/x/net` (31), `golang.org/x/crypto` (22),
  `github.com/labstack/echo/v4` (6), `github.com/getkin/kin-openapi` (5),
  `golang.org/x/mod`, `golang.org/x/text`, `github.com/klauspost/compress`,
  `github.com/jackc/pgx/v5` (2 CRITICAL), and build metadata in the
  `dirsearch` `Cargo.lock` (`pyo3`, `quinn-proto`).

The three remaining CRITICAL findings are:

- `CVE-2026-118264` in `github.com/labstack/echo/v4` inside `dalfox`
  (installed `v4.15.2`, fixed `4.16.1`);
- `CVE-2026-33815` and `CVE-2026-33816` in `github.com/jackc/pgx/v5` inside
  `katana` (installed `v5.7.2`, fixed `5.9.0`).

These are embedded in the latest upstream releases and are not fixed by a tool
version bump. They are analysed in
[`docs/vulnerability-risk-register.md`](vulnerability-risk-register.md) and are
not suppressed. The scan gate therefore remains red. Remediation requires a
newer Debian snapshot or package set (for the OS findings) and upstream Go
module upgrades (for the embedded-module findings). `docs/roadmap.md` records
this as the remaining M1 blocker.

### Catalog scan and verification matrix (2026-11-09)

| Check | Core | Network Security | Web Security | AD Security | OSINT | Full |
|---|---|---|---|---|---|---|
| Build | Passed | Passed | Passed | Passed | Passed | Passed |
| Manifest-list digest | `sha256:962ce703…d68c5fc` | `sha256:75a634b4…effcd3` | `sha256:5dfddb51…520b9aa` | `sha256:8cef90b5…effaf3d9` | `sha256:baf53815…c000d3c5` | `sha256:bfac7833…be69dd2b` |
| `image verify` | Passed (18 tools) | Passed (12 tools) | Passed (15 tools) | Passed (5 tools) | Passed (6 tools) | Passed (31 tools) |
| Trivy HIGH/CRITICAL | 82 (82 HIGH, 0 CRIT) | 87 (84 HIGH, 3 CRIT) | 165 (162 HIGH, 3 CRIT) | 98 (94 HIGH, 4 CRIT) | 165 (162 HIGH, 3 CRIT) | 181 (174 HIGH, 7 CRIT) |
| Debian OS findings | 82 (82 HIGH, 0 CRIT) | 87 (84 HIGH, 3 CRIT) | 83 (83 HIGH, 0 CRIT) | 98 (94 HIGH, 4 CRIT) | 83 (83 HIGH, 0 CRIT) | 99 (95 HIGH, 4 CRIT) |
| Language module findings | 0 | 0 | 82 (79 HIGH, 3 CRIT) | 0 | 82 (79 HIGH, 3 CRIT) | 82 (79 HIGH, 3 CRIT) |
| Scoped secret suppressions | 0 | 0 | 25 removed (0 remaining) | 0 | 25 removed (0 remaining) | 25 removed (0 remaining) |
| Gate status | Open (Debian debt) | Open (liblmdb0) | Open (Go modules) | Open (liblmdb0, libxml2) | Open (Go modules) | Open (combined) |

The Web Security column of this 2026-11-09 matrix is superseded by the
[2026-11-13 Go-tool rebuild](#2026-11-13-web-security-go-tool-rebuild):
147 HIGH, 0 CRITICAL, and no language-module finding left. The other five
columns are unaffected by that rebuild.

All six images use the same Debian snapshot (`20261108T000000Z`) and base digest as Web Security.
Core installs only shell, file, and network triage packages. Network Security
adds capture, DNS, discovery, and service-triage packages on top of Core.
AD Security adds Kerberos, LDAP, SMB, and Impacket on top of Core. OSINT adds
DNS, public-source, and metadata tools on top of Web Security. Full is the union
of all toolsets. None of the images adds a default route, a host gateway, a
published port, or a capability to the container specification; capabilities come
from the engagement profile.

All six images build, verify, and now have recorded Trivy scan baselines.
Scoped `trivyignore.yaml` files are present for Web Security, OSINT, and Full,
each suppressing only the 25 upstream test fixtures in nuclei-templates.
Findings across all variants are tracked in
[`docs/vulnerability-risk-register.md`](vulnerability-risk-register.md).

### Prior bookworm image (historical)

The previous Debian 12 image was built and scanned but is not the current
artifact. It reported **232 HIGH/CRITICAL** vulnerability findings (22
CRITICAL) plus 25 secret findings under `/opt/nuclei-templates`. The scoped
suppression file removed all 25 secret findings and no vulnerability findings.
Those package and Go-module findings remain open and are why the base moved to
Debian 13 and the scan is not yet green.
