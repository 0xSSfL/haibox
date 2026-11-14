#!/usr/bin/env bash
# Functional smoke test for the Go tools of the web-security image.
#
# Runs inside the image and exercises every rebuilt Go tool against a local
# HTTP server, so it needs no external network. It then reads the embedded
# module metadata back out of the shipped binaries and runs the same
# check-modules.sh the image build uses, so the shipped image is verified
# against the committed requirement set rather than a copy of it.
#
#   scripts/smoke-web-security.sh
#
# The image context is mounted read-only at /smoke so the script can read the
# committed requirement lists and the checker. Run it against the reviewed
# Docker context; review docs/host-docker-review.md first.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
context="${root}/images/web-security"
image="haibox/web-security:0.1.0"

if [[ ! -d "${context}" ]]; then
  echo "no image context: ${context}" >&2
  exit 2
fi

docker run --rm \
  --cap-drop ALL \
  --network none \
  --read-only \
  --tmpfs /tmp:rw,size=64m \
  --tmpfs /home/haibox/.config:rw,size=16m,uid=1000,gid=1000,mode=0770 \
  -v "${context}:/smoke:ro" \
  --entrypoint /bin/bash \
  "${image}" \
  /smoke/smoke.sh
