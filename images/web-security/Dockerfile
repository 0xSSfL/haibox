# Independent HAIBOX Web Security image.
#
# Build from the repository root:
#   uv run haibox image build web-security
#
# The base image and every tool version are pinned. Debian packages come from a
# snapshot so a rebuild does not silently pick up a different package set.
#
# The Go tools are rebuilt from their pinned upstream releases with the
# vulnerable transitive dependencies replaced by their fixed versions.  The
# upstream releases pin the vulnerable versions in their own go.mod, so the
# patched module requirements are committed under gomod/ and are the pinned
# build input.  The sources come from the Go module proxy, which is immutable
# and verified against the Go checksum database.

ARG DEBIAN_IMAGE=debian:13-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
ARG DEBIAN_SNAPSHOT=20261108T000000Z

FROM golang:1.26-bookworm@sha256:23ce71337b726608afb1bc00986e630a05034a87a87ea1fc2cd1ae5cf33387eb AS gobuilder

ARG FFUF_VERSION=v2.3.0
ARG GOBUSTER_VERSION=v3.8.2
ARG NUCLEI_VERSION=v3.11.1
ARG HTTPX_VERSION=v1.12.0
ARG SUBFINDER_VERSION=v2.17.0
ARG KATANA_VERSION=v1.8.0
ARG DALFOX_VERSION=v2.13.0

ENV CGO_ENABLED=0 \
    GOTOOLCHAIN=local \
    GOMAXPROCS=2 \
    GOFLAGS="-trimpath -buildvcs=false -p=2"

# The patched module requirements live in gomod/.  They pin every direct and
# indirect dependency of the tool, so the build resolves the same versions
# every time.  "go mod tidy" must not run here: it would drop the upgrades
# again because the tools do not import the affected modules directly.
COPY gomod/ /build/gomod/

# build_tool <name> <module> <version> <package-path>
#
# The module proxy serves the upstream source for the pinned release, and the
# committed go.mod/go.sum replace the upstream requirement set with the fixed
# versions.  The build then asserts the resulting binary's module metadata:
# every fixed version must be present, and no vulnerable version may remain.
#
# "go version -m" prints the module version with its "v" prefix, so the
# assertions compare the bare version against both spellings.
RUN set -eux; \
    build_tool() { \
        name="$1"; module="$2"; version="$3"; path="$4"; \
        mkdir -p /tmp/download && cd /tmp/download; \
        if [ ! -f go.mod ]; then go mod init haibox.local/download; fi; \
        src="$(go mod download -json "${module}@${version}" \
              | sed -n 's/^[[:space:]]*"Dir":[[:space:]]*"\(.*\)",$/\1/p')"; \
        if [ -z "${src}" ] || [ ! -d "${src}" ]; then \
            echo "FATAL: ${module}@${version} was not downloaded"; exit 1; \
        fi; \
        rm -rf "/tmp/src/${name}"; \
        mkdir -p "/tmp/src/${name}"; \
        cp -a "${src}/." "/tmp/src/${name}/"; \
        chmod -R u+w "/tmp/src/${name}"; \
        cp "/build/gomod/${name}.go.mod" "/tmp/src/${name}/go.mod"; \
        cp "/build/gomod/${name}.go.sum" "/tmp/src/${name}/go.sum"; \
        cd "/tmp/src/${name}"; \
        go build -mod=mod -trimpath -buildvcs=false -p=2 -o "/go/bin/${name}" "${path}"; \
        go version -m "/go/bin/${name}" > "/tmp/${name}.modinfo"; \
        grep -E "^[[:space:]]*dep[[:space:]]" "/tmp/${name}.modinfo"; \
    }; \
    assert_fixed() { \
        name="$1"; module="$2"; version="$3"; \
        if ! awk -v m="$module" -v v="$version" \
                '$1=="dep" && $2==m && ($3==v || $3=="v" v) {f=1} END{exit !f}' \
                "/tmp/${name}.modinfo"; then \
            echo "FATAL: ${name} does not embed ${module} ${version}"; \
            grep -E "^[[:space:]]*dep[[:space:]]+${module}[[:space:]]" \
                "/tmp/${name}.modinfo" || true; \
            exit 1; \
        fi; \
        echo "OK: ${name} embeds ${module} ${version}"; \
    }; \
    assert_absent() { \
        name="$1"; module="$2"; version="$3"; \
        if awk -v m="$module" -v v="$version" \
                '$1=="dep" && $2==m && ($3==v || $3=="v" v) {f=1} END{exit !f}' \
                "/tmp/${name}.modinfo"; then \
            echo "FATAL: ${name} still embeds vulnerable ${module} ${version}"; \
            exit 1; \
        fi; \
        echo "OK: ${name} does not embed ${module} ${version}"; \
    }; \
    build_tool ffuf      github.com/ffuf/ffuf/v2                "${FFUF_VERSION}"      . ; \
    build_tool gobuster  github.com/OJ/gobuster/v3               "${GOBUSTER_VERSION}"  . ; \
    build_tool nuclei    github.com/projectdiscovery/nuclei/v3   "${NUCLEI_VERSION}"    ./cmd/nuclei ; \
    build_tool httpx     github.com/projectdiscovery/httpx        "${HTTPX_VERSION}"     ./cmd/httpx ; \
    build_tool subfinder github.com/projectdiscovery/subfinder/v2 "${SUBFINDER_VERSION}" ./cmd/subfinder ; \
    build_tool katana    github.com/projectdiscovery/katana       "${KATANA_VERSION}"    ./cmd/katana ; \
    build_tool dalfox    github.com/hahwul/dalfox/v2              "${DALFOX_VERSION}"    . ; \
    \
    assert_fixed dalfox github.com/labstack/echo/v4 4.16.1 ; \
    assert_absent dalfox github.com/labstack/echo/v4 4.15.2 ; \
    assert_fixed katana github.com/jackc/pgx/v5 5.9.0 ; \
    assert_absent katana github.com/jackc/pgx/v5 5.7.2 ; \
    assert_fixed nuclei github.com/getkin/kin-openapi 0.149.0 ; \
    assert_fixed nuclei github.com/go-git/go-git/v5 5.19.2 ; \
    assert_fixed nuclei github.com/go-jose/go-jose/v4 4.1.6 ; \
    assert_fixed nuclei google.golang.org/grpc 1.84.0 ; \
    assert_absent nuclei google.golang.org/grpc 1.82.1 ; \
    assert_fixed nuclei golang.org/x/net 0.62.0 ; \
    assert_fixed nuclei golang.org/x/crypto 0.59.0 ; \
    assert_fixed nuclei golang.org/x/text 0.44.0 ; \
    assert_fixed nuclei golang.org/x/mod 0.42.0 ; \
    assert_fixed nuclei golang.org/x/sys 0.50.0 ; \
    assert_fixed nuclei github.com/klauspost/compress 1.20.2 ; \
    assert_fixed nuclei github.com/andybalholm/brotli 1.2.7 ; \
    assert_fixed nuclei github.com/yuin/goldmark 1.7.17 ; \
    assert_fixed httpx golang.org/x/net 0.62.0 ; \
    assert_fixed httpx golang.org/x/crypto 0.59.0 ; \
    assert_fixed httpx golang.org/x/text 0.44.0 ; \
    assert_fixed httpx golang.org/x/sys 0.50.0 ; \
    assert_fixed httpx github.com/klauspost/compress 1.20.2 ; \
    assert_fixed httpx github.com/andybalholm/brotli 1.2.7 ; \
    assert_fixed httpx github.com/yuin/goldmark 1.7.17 ; \
    assert_fixed subfinder golang.org/x/net 0.62.0 ; \
    assert_fixed subfinder golang.org/x/crypto 0.59.0 ; \
    assert_fixed subfinder golang.org/x/text 0.44.0 ; \
    assert_fixed subfinder golang.org/x/sys 0.50.0 ; \
    assert_fixed subfinder github.com/klauspost/compress 1.20.2 ; \
    assert_fixed subfinder github.com/andybalholm/brotli 1.2.7 ; \
    assert_fixed subfinder github.com/yuin/goldmark 1.7.17 ; \
    assert_fixed katana golang.org/x/net 0.62.0 ; \
    assert_fixed katana golang.org/x/crypto 0.59.0 ; \
    assert_fixed katana golang.org/x/text 0.44.0 ; \
    assert_fixed katana golang.org/x/sys 0.50.0 ; \
    assert_fixed katana github.com/klauspost/compress 1.20.2 ; \
    assert_fixed katana github.com/andybalholm/brotli 1.2.7 ; \
    assert_fixed katana github.com/yuin/goldmark 1.7.17 ; \
    assert_fixed gobuster golang.org/x/net 0.62.0 ; \
    assert_fixed gobuster golang.org/x/crypto 0.59.0 ; \
    assert_fixed gobuster golang.org/x/sys 0.50.0 ; \
    assert_fixed ffuf golang.org/x/net 0.62.0 ; \
    assert_fixed ffuf github.com/andybalholm/brotli 1.2.7 ; \
    \
    forbidden="github.com/labstack/echo/v4 4.15.2 \
github.com/jackc/pgx/v5 5.7.2 \
google.golang.org/grpc 1.82.1 \
github.com/klauspost/compress 1.18.2 \
github.com/klauspost/compress 1.18.5 \
github.com/klauspost/compress 1.18.7 \
github.com/andybalholm/brotli 1.0.5 \
github.com/andybalholm/brotli 1.2.0 \
github.com/yuin/goldmark 1.7.4 \
github.com/yuin/goldmark 1.7.13 \
software.sslmate.com/src/go-pkcs12 0.6.0 \
golang.org/x/crypto 0.41.0 \
golang.org/x/crypto 0.50.0 \
golang.org/x/crypto 0.53.0 \
golang.org/x/crypto 0.58.0 \
golang.org/x/net 0.7.0 \
golang.org/x/net 0.43.0 \
golang.org/x/net 0.53.0 \
golang.org/x/net 0.56.0 \
golang.org/x/net 0.58.0 \
golang.org/x/net 0.59.0 \
golang.org/x/text 0.28.0 \
golang.org/x/text 0.36.0 \
golang.org/x/text 0.39.0 \
golang.org/x/text 0.42.0 \
golang.org/x/mod 0.34.0 \
golang.org/x/mod 0.37.0 \
golang.org/x/sys 0.35.0 \
golang.org/x/sys 0.49.0" ; \
    for pair in ${forbidden}; do \
        module="${pair% *}"; version="${pair#* }"; \
        for info in /tmp/*.modinfo; do \
            if awk -v m="$module" -v v="$version" \
                    '$1=="dep" && $2==m && ($3==v || $3=="v" v) {f=1} END{exit !f}' \
                    "$info"; then \
                echo "FATAL: ${info} still embeds vulnerable ${module} ${version}"; \
                exit 1; \
            fi; \
        done; \
    done; \
    echo "OK: no binary embeds a previously vulnerable module version"; \
    \
    ffuf -V >/dev/null; \
    gobuster --version >/dev/null; \
    nuclei -version >/dev/null; \
    httpx -version >/dev/null; \
    subfinder -version >/dev/null; \
    katana -version >/dev/null; \
    dalfox version >/dev/null

FROM ${DEBIAN_IMAGE}

ARG DEBIAN_SNAPSHOT
ARG ARJUN_VERSION=2.2.7
ARG DIRSEARCH_VERSION=0.5.0
ARG SQLMAP_VERSION=1.10.11
ARG NUCLEI_TEMPLATES_COMMIT=79fb682760ab3d5b0e22afbb44709353cbebf023

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin \
    PIPX_HOME=/opt/pipx \
    PIPX_BIN_DIR=/usr/local/bin \
    NUCLEI_TEMPLATES=/opt/nuclei-templates

# The slim base has no CA bundle yet, so the snapshot is fetched over HTTP.
# apt still verifies the signed InRelease metadata before installing anything.
# Use Debian's official Cloudflare snapshot mirror: snapshot.debian.org
# intermittently returns 504 Gateway Timeout for package indices, which made
# builds hang for tens of minutes. The mirror serves the same pinned timestamp.
# Debian classifies nikto as non-free; that component is enabled only on the
# main snapshot line. Review its license before redistributing this image.
RUN set -eux; \
    rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*; \
    printf '%s\n' \
        "deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/ trixie main non-free" \
        "deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian-security/${DEBIAN_SNAPSHOT}/ trixie-security main" \
        > /etc/apt/sources.list; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get -o Acquire::Retries=5 upgrade -y --no-install-recommends \
        -o Dpkg::Options::=--force-confold; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        file \
        git \
        iproute2 \
        jq \
        less \
        netcat-openbsd \
        openssl \
        procps \
        python3 \
        ripgrep \
        tar \
        tree \
        unzip \
        xz-utils; \
    rm -rf /var/lib/apt/lists/*

# Network tooling is a separate layer. Installing it together with the base
# packages made apt balloon past 6 GB RSS inside BuildKit and triggered a host
# OOM. The same set installs well under 2 GB when split; see
# docs/image-validation.md.
#
# BIND's dnsutils and wget are intentionally absent. bind9-libs pulls
# liblmdb0 and libxml2, whose HIGH/CRITICAL findings have no fixed Debian
# version; wget is redundant with curl. Both removals are recorded in
# docs/image-validation.md.
RUN set -eux; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        dirb \
        nikto \
        nmap \
        pipx \
        whatweb; \
    rm -rf /var/lib/apt/lists/*

COPY --from=gobuilder /go/bin/ /usr/local/bin/

RUN set -eux; \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install --pip-args='--no-cache-dir' "arjun==${ARJUN_VERSION}"; \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install --pip-args='--no-cache-dir' "dirsearch==${DIRSEARCH_VERSION}"; \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install --pip-args='--no-cache-dir' "sqlmap==${SQLMAP_VERSION}"; \
    /opt/pipx/venvs/dirsearch/bin/python -m pip install --no-cache-dir --quiet \
        "cryptography==50.0.0" "pyopenssl==26.4.0"; \
    apt-get purge -y pipx python3-venv; \
    apt-get autoremove --purge -y; \
    rm -rf /opt/pipx/shared /opt/pipx/logs; \
    arjun --help >/dev/null; \
    dirsearch --help >/dev/null; \
    sqlmap --version >/dev/null; \
    rm -rf /root/.cache /tmp/*

RUN set -eux; \
    git init /opt/nuclei-templates; \
    cd /opt/nuclei-templates; \
    git remote add origin https://github.com/projectdiscovery/nuclei-templates.git; \
    git fetch --depth 1 origin "${NUCLEI_TEMPLATES_COMMIT}"; \
    git checkout --detach FETCH_HEAD; \
    rm -rf .git

RUN set -eux; \
    groupadd --gid 1000 haibox; \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash haibox; \
    install -d -o haibox -g haibox /workspace /opt/haibox

LABEL org.opencontainers.image.title="HAIBOX Web Security" \
      org.opencontainers.image.description="Independent web security toolkit for the HAIBOX platform" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="MIT" \
      haibox.image.name="web-security" \
      haibox.image.version="0.1.0"

USER haibox
WORKDIR /workspace
ENTRYPOINT ["/bin/bash"]
CMD ["-l"]
