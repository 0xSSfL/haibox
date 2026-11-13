#!/usr/bin/env bash
# Functional smoke test for the Go tools of the web-security image.
#
# Runs inside the image and exercises every rebuilt Go tool against a local
# HTTP server, so it needs no external network. It also reads the embedded
# module metadata back out of the shipped binaries, independently of the
# assertions the build makes.
#
#   scripts/smoke-web-security.sh [image]
#
# The image context is mounted read-only at /smoke so the script can read the
# committed module-requirements.txt. Run it against the reviewed Docker
# context; review docs/host-docker-review.md first.
set -euo pipefail

name="${1:-web-security}"
if [[ $# > 0 ]]; then
  shift
fi

if [[ ! "$name" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "invalid image name: $name" >&2
  exit 2
fi

image="haibox/${name}:0.1.0"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
context="${root}/images/${name}"

if [[ ! -d "${context}" ]]; then
  echo "no image context: ${context}" >&2
  exit 2
fi

docker run --rm \
  -v "${context}:/smoke:ro" \
  --entrypoint /bin/bash \
  "${image}" \
  /smoke/smoke-web-security.sh
