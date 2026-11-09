# Independent HAIBOX Full Toolkit image.
#
# Build from the repository root. The builder resolves and builds the declared
# dependencies first:
#   uv run haibox image build full
#
# Full starts from the pinned Web Security image and adds the Network Security,
# Active Directory, and OSINT package sets. It is intentionally a large image;
# use a focused variant when that is enough.

ARG BASE_IMAGE=haibox/web-security:0.1.0
ARG IMPACKET_VERSION=0.13.1
ARG DNSRECON_VERSION=0.10.1

FROM ${BASE_IMAGE}

USER root

ARG IMPACKET_VERSION
ARG DNSRECON_VERSION

ENV PIPX_HOME=/opt/pipx \
    PIPX_BIN_DIR=/usr/local/bin

RUN set -eux; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        arping \
        hping3 \
        iputils-ping \
        knot-dnsutils \
        krb5-user \
        ldap-utils \
        libimage-exiftool-perl \
        libsasl2-modules-gssapi-mit \
        masscan \
        netdiscover \
        pipx \
        samba-common-bin \
        smbclient \
        socat \
        tcpdump \
        traceroute \
        whois; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install \
        --pip-args='--no-cache-dir' "impacket==${IMPACKET_VERSION}"; \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install \
        --pip-args='--no-cache-dir' "dnsrecon==${DNSRECON_VERSION}"; \
    apt-get purge -y pipx python3-venv; \
    apt-get autoremove --purge -y; \
    rm -rf /opt/pipx/shared /opt/pipx/logs /root/.cache /tmp/*; \
    command -v impacket-GetNPUsers >/dev/null 2>&1 || command -v GetNPUsers.py >/dev/null; \
    dnsrecon --help >/dev/null

USER haibox
WORKDIR /workspace

LABEL org.opencontainers.image.title="HAIBOX Full Toolkit" \
      org.opencontainers.image.description="Combined HAIBOX toolkit for authorized engagements" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="MIT" \
      haibox.image.name="full" \
      haibox.image.version="0.1.0"
