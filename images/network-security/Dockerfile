# Independent HAIBOX Network Security image.
#
# Build from the repository root (the Core dependency is built first):
#   uv run haibox image build network-security
#
# The image adds packet capture, DNS, and host-discovery tooling to Core. It
# does not add a default route or change the engagement network profile.

ARG BASE_IMAGE=haibox/core:0.1.0

FROM ${BASE_IMAGE}

USER root

RUN set -eux; \
    apt-get -o Acquire::Retries=5 update; \
    apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        arping \
        hping3 \
        iputils-ping \
        knot-dnsutils \
        masscan \
        netdiscover \
        socat \
        tcpdump \
        traceroute \
        whois; \
    rm -rf /var/lib/apt/lists/*

USER haibox
WORKDIR /workspace

LABEL org.opencontainers.image.title="HAIBOX Network Security" \
      org.opencontainers.image.description="Network discovery and capture toolkit for the HAIBOX platform" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="MIT" \
      haibox.image.name="network-security" \
      haibox.image.version="0.1.0"
