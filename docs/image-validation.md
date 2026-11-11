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

The Cloudflare snapshot mirror is used because `snapshot.debian.org` returned
`504 Gateway Timeout` for package indices during the first attempts. It serves
the same pinned snapshot; apt still verifies the signed `InRelease` metadata.

The apt packages are installed in two layers (base tools, then network tools).
Installing the full set in one BuildKit layer made `apt-get` grow past 6 GB
anonymous RSS and triggered a host OOM; the same set installs well under a
2 GB cap when split or run in a plain container. The Go stage sets
`GOMAXPROCS=2` and `-p=2` to limit parallel compile memory.

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

A scan also has to cover the image's OS packages. Trivy reports Fedora as
unsupported and does not detect Arch Linux as an OS; both cases still exit `0`.
HAIBOX parses the report instead of trusting the exit code:

- Trivy coverage requires `Metadata.OS.Family` and no `Unsupported os` warning.
- When Trivy is not covered and Grype is installed, the scan falls back to Grype.
- Grype coverage requires a non-empty `distro.name` and a valid vulnerability
  database.
- An empty, unparseable, or uncovered report fails the scan; it is never a pass.

### Scanner coverage validation (2026-11-11)

Run against a real Docker endpoint with Trivy 0.76.2 and Grype 0.121.3:

| Image | Trivy | Fallback | Result |
|---|---|---|---|
| `haibox/core:0.1.0` (Debian 13.7) | Covered | Not used | 138 HIGH/CRITICAL; gate red |
| `fedora:44` | `Unsupported os` | Grype `fedora 44` | 16 HIGH, 8 Medium; gate red on 16 HIGH |
| `archlinux:latest` | OS not detected | Grype `archlinux 20261108.0.623074` | Grype 2 High; Trivy still reported 24 HIGH/CRITICAL non-OS findings; gate red on 26 combined |

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
