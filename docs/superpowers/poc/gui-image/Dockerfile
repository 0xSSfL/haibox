# Disposable Xpra validation image for the HAIBOX desktop design review.
#
# This is NOT a HAIBOX catalog image and must not be published, tagged as
# `haibox/<variant>`, or included in the terminal-only image set. It exists only
# to reproduce the 2026-11-10 Xpra proof of concept and to record scanner
# evidence for the optional GUI image design.
#
# Build from this directory:
#   docker --context haibox build -t haibox/gui-poc-validation:0.1.0 .
#
# The Fedora image digest and package versions below are the ones used for the
# recorded validation. A production GUI image would need its own manifest,
# dependency review, and accepted scan gate; see
# ../2026-11-10-gui-image-validation.md.

ARG FEDORA_IMAGE=fedora:44@sha256:15da97ed9aa94dd3d92c3925eb89520f6c80e07ea7ee24cba848d1f8b6912b3e

FROM ${FEDORA_IMAGE}

RUN set -eux; \
    dnf -y install \
        xpra-6.5.4-1.fc44 \
        xterm-411-1.fc44 \
        xorg-x11-server-Xvfb-21.1.25-2.fc44 \
        socat-1.8.1.3-1.fc44 \
        python3-gobject-3.56.3-1.fc44.x86_64; \
    dnf -y clean all; \
    rm -rf /var/cache/dnf /var/cache/libdnf5 /tmp/*

RUN set -eux; \
    groupadd --gid 1000 haibox; \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash haibox; \
    install -d -o haibox -g haibox /workspace /opt/haibox

LABEL org.opencontainers.image.title="HAIBOX Xpra validation fixture" \
      org.opencontainers.image.description="Disposable GUI validation image; not a catalog or production image" \
      org.opencontainers.image.version="0.0.0-poc" \
      haibox.poc="xpra-seamless" \
      haibox.production="false"

USER 1000:1000
WORKDIR /workspace
ENTRYPOINT ["/bin/bash"]
CMD ["-l"]
