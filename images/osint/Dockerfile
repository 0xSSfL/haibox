# Independent HAIBOX OSINT image.
#
# Build from the repository root (the Web Security dependency is built first):
#   uv run haibox image build osint
#
# The image adds public-source collection and metadata tooling to the pinned
# Web Security image. It deliberately does not bundle scrapers that are only
# distributed as an unpinned Git checkout.

ARG BASE_IMAGE=haibox/web-security:0.1.0
ARG DNSRECON_VERSION=0.10.1

FROM ${BASE_IMAGE}

USER root

ARG DNSRECON_VERSION

ENV PIPX_HOME=/opt/pipx \
    PIPX_BIN_DIR=/usr/local/bin

RUN set -eux; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        libimage-exiftool-perl \
        pipx \
        whois; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install \
        --pip-args='--no-cache-dir' "dnsrecon==${DNSRECON_VERSION}"; \
    apt-get purge -y pipx python3-venv; \
    apt-get autoremove --purge -y; \
    rm -rf /opt/pipx/shared /opt/pipx/logs /root/.cache /tmp/*; \
    dnsrecon --help >/dev/null

USER haibox
WORKDIR /workspace

LABEL org.opencontainers.image.title="HAIBOX OSINT" \
      org.opencontainers.image.description="Public-source and metadata toolkit for the HAIBOX platform" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="MIT" \
      haibox.image.name="osint" \
      haibox.image.version="0.1.0"
