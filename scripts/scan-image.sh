#!/usr/bin/env bash
# Scan a built HAIBOX image with the host scanner adapter.
#
# Run this against the reviewed Docker context. Direct Fedora use is supported;
# review docs/host-docker-review.md first. A KVM VM is optional.
set -euo pipefail

name="${1:-web-security}"
if [[ $# -gt 0 ]]; then
  shift
fi

if [[ ! "$name" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
  echo "invalid image name: $name" >&2
  exit 2
fi

exec uv run haibox image scan "$name" "$@"
