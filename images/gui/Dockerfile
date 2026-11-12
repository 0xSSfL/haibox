# HAIBOX GUI image.
#
# Build from the repository root:
#   uv run haibox image build gui
#
# The image provides the Xpra server for an optional GUI session inside an
# existing engagement runner.  It is a separate definition from the Debian
# catalog images because no Debian or Ubuntu release ships a supported Xpra
# server: Debian 13 has no Xpra package at all and Ubuntu 24.04 still carries
# the 3.1 series from 2022.  Fedora ships the current 6.5 series, which is the
# only maintained distribution packaging with the seamless server, the file
# authentication module, and the deny-by-default flags the GUI needs.
#
# The base is pinned by digest and the direct packages are pinned by version.
# The scanner pipeline covers the OS through the Grype fallback because Trivy
# does not support Fedora; see
# ../../docs/superpowers/poc/2026-11-12-gui-image-security.md.

ARG FEDORA_IMAGE=fedora:46@sha256:78bb31de333664aa76c4bf54306791cd294c0bd4fbcfc4346e2286261de544c4

FROM ${FEDORA_IMAGE}

ENV LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    PATH=/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin

# The base image is updated to the current Fedora packages before the pinned
# direct packages are installed, so the image carries the fixed library
# versions (pcre2 10.49, python3-pillow 13.0.0) that close the findings the
# previous Fedora 44 fixture carried.
#
# python3-gobject is required by the Xpra server itself: without the GObject
# introspection bindings the server exits with "the python gobject
# introspection bindings are missing" before it binds its display.  That was
# found by running the server in the container, not by reading the manifest.
RUN set -eux; \
    dnf -y upgrade --refresh; \
    dnf -y install --setopt=install_weak_deps=False \
        xpra-6.5.6-1.fc46 \
        python3-gobject-3.58.1-6.fc46 \
        xterm-411-1.fc46 \
        xorg-x11-server-Xvfb-21.1.26-1.fc46 \
        socat-1.8.1.3-1.fc46; \
    dnf -y clean all; \
    rm -rf /var/cache/dnf /var/cache/libdnf5 /tmp/* /var/log/*

RUN set -eux; \
    groupadd --gid 1000 haibox; \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash haibox; \
    install -d -o haibox -g haibox /workspace

LABEL org.opencontainers.image.title="HAIBOX GUI" \
      org.opencontainers.image.description="Xpra seamless server for the HAIBOX GUI" \
      org.opencontainers.image.version="0.1.0" \
      org.opencontainers.image.licenses="MIT" \
      haibox.image.name="gui" \
      haibox.image.version="0.1.0"

USER haibox
WORKDIR /workspace
ENTRYPOINT ["/bin/bash"]
CMD ["-l"]
