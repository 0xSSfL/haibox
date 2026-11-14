# Image catalog

HAIBOX images are independent definitions. Each directory under `images/`
contains a `Dockerfile` and a `manifest.yaml`; the manifest is the source of
truth for the base digest, Debian snapshot, build arguments, tool versions, and
verification commands.

The catalog is intentionally smaller than a general-purpose pentest
distribution. Every tool must have a pinned version and a non-interactive
verification command, and every image inherits the same deny-by-default
container shape from the engagement profile.

## Dependency graph

```text
core
├── network-security
└── ad-security

web-security
└── osint

full
├── core
├── network-security
├── web-security
├── ad-security
└── osint
```

`full` starts from the pinned Web Security image and adds the Network Security,
Active Directory, and OSINT package sets. The dependency list is declarative:
`haibox image build full` builds each local base in order, builds diamond
dependencies once, and rejects cycles before invoking Docker.

The builder does not silently pull `haibox/*` tags from a registry. A local
base must either be built by the same command or already exist in the reviewed
Docker context.

## Variants

| Image | Status | Base | Purpose | Tools |
|---|---|---|---|---|
| `core` | Active | Debian 13 snapshot | Minimal shell, file, and network triage | bash, curl, file, git, iproute2, jq, less, netcat, nmap, openssl, ping, procps, python3, ripgrep, tar, tree, unzip, xz |
| `network-security` | Active | `haibox/core:0.1.0` | Discovery, DNS, capture, and service triage | nmap, tcpdump, netcat, socat, hping3, masscan, netdiscover, arping, ping, traceroute, whois, kdig |
| `web-security` | Active | Debian 13 snapshot | HTTP, content discovery, and template scanning | ffuf, gobuster, nuclei, httpx, subfinder, katana, dalfox, arjun, dirsearch, sqlmap, nikto, whatweb, dirb, nmap, pinned nuclei templates |
| `ad-security` | Experimental | `haibox/core:0.1.0` | Authorized Active Directory assessment | Impacket, smbclient, ldapsearch, kinit, nmap |
| `osint` | Experimental | `haibox/web-security:0.1.0` | Public-source, DNS, and metadata collection | dnsrecon, exiftool, whois, subfinder, httpx, nuclei |
| `full` | Experimental | `haibox/web-security:0.1.0` | Combined toolkit | Union of the Web, Network, AD, and OSINT sets |
| `gui` | Experimental | Fedora 46 (pre-release) | Optional Xpra seamless server for a GUI session | xpra, python3-gobject, xterm, Xvfb, socat |

“Active” means the image definition and build path are part of the validated
milestone. It does not mean the image has no vulnerabilities; the scan gate is
recorded separately in [`image-validation.md`](image-validation.md).

### Build and scan evidence

| Image | Build | Verification | Trivy scan (HIGH / CRIT) | Digest (manifest list) |
|---|---|---|---|---|
| `core` | Passed 2026-11-09 | Passed: all 18 tools as uid/gid 65534 | 82 (82 H, 0 C) | `sha256:962ce7034da59a7d92c6cb9eca20e2348d73c92c560bc002de094cd77d68c5fc` |
| `network-security` | Passed 2026-11-09 | Passed: all 12 tools as uid/gid 65534 | 87 (84 H, 3 C) | `sha256:75a634b43746eab3709915113f0be65a5e0149b0c686a5f628eeba0d64effcd3` |
| `web-security` | Passed 2026-11-13 (Go-tool rebuild) | Passed: all 15 tools as uid/gid 65534 | 147 (147 H, 0 C) | `sha256:6bb9ed2617f538392d327fafba62f49b4bbc54dbd961bf33c842980acded9314` |
| `ad-security` | Passed 2026-11-09 | Passed: Impacket, SMB, LDAP, Kerberos, and nmap as uid/gid 65534 | 98 (94 H, 4 C) | `sha256:8cef90b5d751e0c7eab0bc2aea9be1e7395608420ceb541a6cc37075effaf3d9` |
| `osint` | Passed 2026-11-09 | Passed: dnsrecon, exiftool, whois, subfinder, httpx, nuclei as uid/gid 65534 | 165 (162 H, 3 C) | `sha256:baf5381595542a24427bf8dc83ae1eb98ccd9a1ed692cc788ecc3ba6c000d3c5` |
| `full` | Passed 2026-11-09 | Passed: 31 tools as uid/gid 65534 | 181 (174 H, 7 C) | `sha256:bfac7833bd56127b2583e2d7b0a311af07b3974851ab7e693f009259be69dd2b` |
| `gui` | Passed 2026-11-12 | Passed: xpra, python3-gobject, xterm, Xvfb, and socat as uid/gid 65534 | 0 (0 H, 0 C) — Grype fallback, Trivy cannot scan Fedora | `sha256:c504dfb334f5661084abf770f3ded63aace6ec5c4ca26dbad18c3646cc271c39` |

All seven images build, verify, and have a recorded scan baseline. Web
Security, OSINT, and Full include scoped `trivyignore.yaml` files for the 25
upstream test fixtures in `nuclei-templates`. The `gui` image is a Fedora
image, so Trivy reports `Unsupported os` and the Grype fallback covers the OS;
it is the only image with no HIGH/CRITICAL findings, and it is still
experimental while its base is a pre-release snapshot. Detailed finding matrices and
reachability analyses are maintained in
[`docs/vulnerability-risk-register.md`](vulnerability-risk-register.md) and
[`docs/image-validation.md`](image-validation.md).

The 2026-11-13 Web Security rebuild removed every finding in the seven Go
binaries, so its row is current. OSINT and Full are built from
`haibox/web-security:0.1.0` and inherit the rebuilt tools on their next
build; their recorded rows still carry the Go-module findings of the previous
base until then.

## Build and verification

```bash
# Core and the network variant (the dependency is built first)
uv run haibox image build core
uv run haibox image build network-security
uv run haibox image verify core
uv run haibox image verify network-security

# Web Security remains the reference image for scan evidence
uv run haibox image build web-security
uv run haibox image verify web-security
uv run haibox image scan web-security

# Experimental variants
uv run haibox image build ad-security
uv run haibox image build osint
# Full can reuse already-built local bases; rebuild them explicitly when a
# dependency manifest or base digest changes.
uv run haibox image build full --reuse-dependencies
```

`--reuse-dependencies` only skips a dependency whose exact `haibox/<name>:<version>`
tag already exists locally. It never pulls from a registry and it does not
change the target image's own build.

`haibox image list` shows the declared dependency list and tool count.
`haibox image inspect NAME` prints the full manifest.

`image verify` runs every `verify` command in an ephemeral container as
uid/gid `65534`, with `--network none`, and fails on the first non-zero command.
It also asserts that the verification process is not root. `image scan` uses
Trivy first, falls back to Grype when Trivy cannot scan the image OS, passes
only the image-local `trivyignore.yaml`, and exits non-zero on any
HIGH/CRITICAL finding, scanner failure, or report that does not cover OS
packages.

## Pinning policy

- The Debian base is a digest, not a floating tag.
- Debian packages come from a timestamped snapshot. The snapshot timestamp is a
  manifest build argument and is also recorded in the Dockerfile.
- Go tools are built from the source of their pinned upstream release, with the
  patched requirement sets in `images/web-security/gomod/`; the build checks the
  resulting module metadata against `module-requirements.txt` and
  `forbidden-modules.txt` and fails if a vulnerable version is embedded. Python
  tools use `pipx install package==version`; the Nuclei template set is a
  pinned commit.
- A new upstream release is a reviewed change: update the manifest, rebuild,
  rerun verification, and rescan. Do not use `@latest`.
- The scan gate is not made green by adding suppressions. An ignore file is
  accepted only for narrowly scoped secret fixtures in the pinned Nuclei
  template checkout.

## Security model

All variants use the same engagement profile rules:

- `network: isolated` in every built-in profile; no variant adds a default
  route, host gateway, published port, or host network mode.
- `--cap-drop ALL`; a profile may add only `NET_RAW` or `NET_BIND_SERVICE`.
- `--security-opt no-new-privileges:true`, read-only root, `tmpfs` for `/tmp`
  and `/run`, non-root UID/GID.
- Only the engagement workspace is writable. The scope file is read-only.
  Secrets, evidence, reports, and audit logs are host-only.
- There is no arbitrary Docker flag pass-through. A variant changes packages
  and tools, not the container security shape.

`network-security` requests `NET_RAW` and `NET_BIND_SERVICE` in its profile so
`nmap`, `masscan`, `tcpdump`, and `netdiscover` can work. Those capabilities
remain scoped to the isolated engagement bridge; they do not grant host network
access. `ad-security` and `osint` request no capabilities.

## Licensing notes

- The images are MIT-licensed HAIBOX definitions.
- `web-security` enables Debian `non-free` only for `nikto`. Review the `nikto`
  license before redistributing the built image.
- `masscan`, `hping3`, `netdiscover`, `knot-dnsutils`, `impacket`, `dnsrecon`,
  `exiftool`, `smbclient`, `ldap-utils`, and `krb5-user` retain their upstream
  licenses. A redistributed image must include the notices those licenses
  require. This catalog does not relicense third-party tools.
- `theHarvester` is not bundled. The PyPI project named `theHarvester` is a
  placeholder, and the upstream project is distributed as a Git checkout; a
  pinned package is not available. `dnsrecon` and `subfinder` cover the DNS and
  subdomain workflow without an unpinned build step.

## Adding a variant

1. Create `images/<name>/Dockerfile` and `manifest.yaml`.
2. Pin the base digest or declare a local `depends_on` base.
3. Pin every tool version and add a non-interactive `verify` command.
4. Add a matching profile under `src/haibox/data/profiles/` with
   `network: isolated` and only the capabilities the tools need.
5. Run `uv run haibox image build <name>`, `image verify <name>`, and
   `image scan <name>`.
6. Record the result in `docs/image-validation.md` or a new per-image record.
   A definition without a build/verify result is not “active”.
