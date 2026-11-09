# Independent HAIBOX Core image.
#
# Build from the repository root:
#   uv run haibox image build core
#
# This image is the shared, pinned base for the other HAIBOX images. It keeps
# only the tools needed to inspect a target, move files, and run a shell.

ARG DEBIAN_IMAGE=debian:13-slim@sha256:a72b4433de1cf7d6bae0c4cee74d0547f58601a643b3375f070c51600d63b6b2
ARG DEBIAN_SNAPSHOT=20261108T000000Z

FROM ${DEBIAN_IMAGE}

ARG DEBIAN_SNAPSHOT

ENV DEBIAN_FRONTEND=noninteractive \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

# The slim base has no CA bundle yet, so the snapshot is fetched over HTTP.
# apt verifies the signed InRelease metadata before installing anything.
RUN set -eux; \
    rm -f /etc/apt/sources.list /etc/apt/sources.list.d/*; \
    printf '%s\n' \
        "deb [check-valid-until=no] http://snapshot-cloudflare.debian.org/archive/debian/${DEBIAN_SNAPSHOT}/ trixie main" \
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
        iputils-ping \
        jq \
        less \
        netcat-openbsd \
        nmap \
        openssl \
        procps \
        python3 \
        ripgrep \
        tar \
        tree \
        unzip \
        xz-utils; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    groupadd --gid 1000 haibox; \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash haibox; \
    install -d -o haibox -g haibox /workspace /opt/haibox

LABEL org.opencontainers.image.title="HAIBOX Core" \
      org.opencontainers.image.description="Minimal shared toolkit for the HAIBOX platform" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="MIT" \
      haibox.image.name="core" \
      haibox.image.version="0.1.0"

USER haibox
WORKDIR /workspace
ENTRYPOINT ["/bin/bash"]
CMD ["-l"]
