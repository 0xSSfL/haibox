# Image definitions

Each image lives in its own directory with a `Dockerfile` and a
`manifest.yaml`.

```text
images/
  core/
    Dockerfile
    manifest.yaml
  network-security/
    Dockerfile
    manifest.yaml
  web-security/
    Dockerfile
    manifest.yaml
    trivyignore.yaml
  ad-security/
    Dockerfile
    manifest.yaml
  osint/
    Dockerfile
    manifest.yaml
  full/
    Dockerfile
    manifest.yaml
```

The manifest is the source of truth for:

- image name and version,
- base image digest or local base image,
- Dockerfile and build context,
- supported platforms,
- pinned build arguments,
- local `depends_on` images,
- tools and verification commands.

`depends_on` is a build-order declaration, not a registry dependency. The
builder loads each local manifest and builds it first, so a Dockerfile can use
`FROM haibox/core:0.1.0` without an untracked tag. Diamond dependencies are
built once; cycles are rejected before Docker runs. `--reuse-dependencies`
skips a dependency whose exact version tag already exists locally.

| Image | Base | Role |
|---|---|---|
| `core` | Debian 13 snapshot | Shared minimal shell, file, and network triage |
| `network-security` | `haibox/core:0.1.0` | Capture, DNS, discovery, service triage |
| `web-security` | Debian 13 snapshot | HTTP, content discovery, template scanning |
| `ad-security` | `haibox/core:0.1.0` | Kerberos, LDAP, SMB, Impacket |
| `osint` | `haibox/web-security:0.1.0` | DNS, metadata, public-source collection |
| `full` | `haibox/web-security:0.1.0` | Combined package set |

> **Build status.** All six images are built and verified. Only Web Security
> has a recorded Trivy scan; the other images still need scan records.
> Verification and scanning results are recorded in the top-level `README.md`,
> `docs/image-catalog.md`, and `docs/image-validation.md`.

Build, verify, and scan from the repository root:

```bash
uv run haibox image build core
uv run haibox image build network-security
uv run haibox image build web-security
uv run haibox image build full --reuse-dependencies
uv run haibox image verify web-security
uv run haibox image scan web-security
```

`haibox image scan` passes the image-local `trivyignore.yaml` to Trivy. The
Web Security policy suppresses only the upstream `nuclei-templates` fixtures
that look like credentials; the suppressions are scoped to exact fixture paths
and are not a general secret-scan bypass. The scan can still report package or
embedded Go-module findings; those are not suppressed by this file.

Review `docs/host-docker-review.md` before building. A KVM VM is optional.

## Licensing note

`nikto` is packaged in Debian's `non-free` component, so the Web Security
Dockerfile enables that component on the pinned main snapshot. Review the
`nikto` license before redistributing the built image. The rest of the
requested packages come from Debian `main`. Third-party tools in the other
images retain their own licenses; see `docs/image-catalog.md`.
