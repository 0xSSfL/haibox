# Independent HAIBOX Active Directory Security image.
#
# Build from the repository root (the Core dependency is built first):
#   uv run haibox image build ad-security
#
# The image bundles Kerberos, LDAP, SMB, and Impacket tooling for authorized
# Active Directory assessments. It does not start a listener or a responder.

ARG BASE_IMAGE=haibox/core:0.1.0
ARG IMPACKET_VERSION=0.13.1

FROM ${BASE_IMAGE}

USER root

ARG IMPACKET_VERSION

ENV PIPX_HOME=/opt/pipx \
    PIPX_BIN_DIR=/usr/local/bin

RUN set -eux; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        krb5-user \
        ldap-utils \
        libsasl2-modules-gssapi-mit \
        pipx \
        samba-common-bin \
        smbclient; \
    rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    PIPX_HOME=/opt/pipx PIPX_BIN_DIR=/usr/local/bin pipx install \
        --pip-args='--no-cache-dir' "impacket==${IMPACKET_VERSION}"; \
    apt-get purge -y pipx python3-venv; \
    apt-get autoremove --purge -y; \
    rm -rf /opt/pipx/shared /opt/pipx/logs /root/.cache /tmp/*; \
    command -v impacket-GetNPUsers >/dev/null 2>&1 || command -v GetNPUsers.py >/dev/null

USER haibox
WORKDIR /workspace

LABEL org.opencontainers.image.title="HAIBOX Active Directory Security" \
      org.opencontainers.image.description="Authorized Active Directory assessment toolkit for the HAIBOX platform" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="MIT" \
      haibox.image.name="ad-security" \
      haibox.image.version="0.1.0"
