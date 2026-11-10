#!/usr/bin/env bash
# Install HAIBOX from a GitHub release.
#
# Usage:
#   curl -fsSL https://0xssfl.github.io/haibox/install.sh | bash
#   HAIBOX_VERSION=0.1.0 bash scripts/install.sh
#
# The wheel is pure Python. The installer bootstraps uv when needed, verifies
# the SHA-256 checksum published with the release, and runs `uv tool install`.

set -euo pipefail

REPO="${HAIBOX_REPO:-0xSSfL/haibox}"
VERSION="${HAIBOX_VERSION:-}"

log() { printf '%s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }

command -v curl >/dev/null 2>&1 || die "curl is required"
case "$(uname -s)" in
  Linux) ;;
  *) die "HAIBOX runs on Linux only (detected $(uname -s))" ;;
esac

if ! command -v uv >/dev/null 2>&1; then
  log "uv not found; installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="${HOME}/.local/bin:${PATH}"
fi
command -v uv >/dev/null 2>&1 \
  || die "uv installation failed; install it from https://docs.astral.sh/uv/"

if [ -z "$VERSION" ]; then
  log "Resolving the latest HAIBOX release..."
  release_json="$(curl -fsSL "https://api.github.com/repos/${REPO}/releases/latest")" \
    || die "cannot reach the GitHub release API"
  VERSION="$(printf '%s\n' "$release_json" \
    | sed -n 's/.*"tag_name"[[:space:]]*:[[:space:]]*"v\{0,1\}\([^"]*\)".*/\1/p' \
    | head -n 1)"
fi

case "$VERSION" in
  ''|*[!0-9A-Za-z.+-]*) die "invalid HAIBOX version: ${VERSION:-<empty>}" ;;
esac

TAG="v${VERSION}"
BASE_URL="https://github.com/${REPO}/releases/download/${TAG}"
WHEEL="haibox-${VERSION}-py3-none-any.whl"
SUMS="SHA256SUMS"

tmpdir="$(mktemp -d)"
cleanup() { rm -rf "$tmpdir"; }
trap cleanup EXIT INT TERM

log "Downloading ${WHEEL} (${TAG})..."
curl -fsSL --retry 3 -o "${tmpdir}/${WHEEL}" "${BASE_URL}/${WHEEL}" \
  || die "cannot download ${WHEEL} from ${BASE_URL}"
curl -fsSL --retry 3 -o "${tmpdir}/${SUMS}" "${BASE_URL}/${SUMS}" \
  || die "cannot download ${SUMS} from ${BASE_URL}"

command -v sha256sum >/dev/null 2>&1 \
  || die "sha256sum is required to verify the download"
(cd "$tmpdir" && grep -F "  ${WHEEL}" "$SUMS" | sha256sum -c -) \
  || die "checksum verification failed for ${WHEEL}"

if ! uv python find '>=3.11' >/dev/null 2>&1; then
  log "No Python >=3.11 found; installing a managed Python..."
  uv python install 3.11
fi

log "Installing HAIBOX ${VERSION}..."
uv tool install --force --python '>=3.11' "${tmpdir}/${WHEEL}"

log ""
log "HAIBOX ${VERSION} installed."
if command -v haibox >/dev/null 2>&1; then
  haibox --version
else
  log "Add $(uv tool dir --bin) to PATH, then run: haibox --version"
fi
log "Next: docker context create haibox --docker \"host=unix:///var/run/docker.sock\""
log "      haibox init && haibox doctor"
