#!/usr/bin/env bash
# Verify that an image's Trivy ignorefile suppresses only the intended findings.
#
# Runs the scan twice (raw and with --ignorefile), then checks:
#   1. HIGH/CRITICAL vulnerability findings are identical in both reports;
#   2. every secret finding removed by the ignorefile matches a suppression
#      path and rule ID declared in the ignorefile;
#   3. no secret findings remain in the filtered report.
#
# Usage: scripts/verify-trivy-suppressions.sh IMAGE [IGNOREFILE]
set -euo pipefail

image="${1:?usage: $0 IMAGE [IGNOREFILE]}"
ignorefile="${2:-images/web-security/trivyignore.yaml}"

if [[ ! -f "$ignorefile" ]]; then
  echo "ignorefile not found: $ignorefile" >&2
  exit 2
fi

trivy="${TRIVY_BIN:-trivy}"
if ! command -v "$trivy" >/dev/null 2>&1; then
  echo "trivy not found (set TRIVY_BIN)" >&2
  exit 2
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required" >&2
  exit 2
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

raw="$workdir/raw.json"
filtered="$workdir/filtered.json"

echo "Scanning $image (raw)"
"$trivy" image --quiet --severity HIGH,CRITICAL --format json \
  --output "$raw" "$image"

echo "Scanning $image (with $ignorefile)"
"$trivy" image --quiet --severity HIGH,CRITICAL \
  --ignorefile "$ignorefile" --format json \
  --output "$filtered" "$image"

# "target<TAB>id" lines, sorted, for set comparisons.
vuln_query='[ .Results[]? | select(.Vulnerabilities) | .Target as $t
  | .Vulnerabilities[] | "\($t)\t\(.VulnerabilityID)" ] | sort | .[]'
secret_query='[ .Results[]? | select(.Secrets) | .Target as $t
  | .Secrets[] | "\($t)\t\(.RuleID)" ] | sort | .[]'

jq -r "$vuln_query" "$raw" > "$workdir/raw-vulns"
jq -r "$vuln_query" "$filtered" > "$workdir/filtered-vulns"
jq -r "$secret_query" "$raw" > "$workdir/raw-secrets"
jq -r "$secret_query" "$filtered" > "$workdir/filtered-secrets"

raw_vuln_count=$(wc -l < "$workdir/raw-vulns")
filtered_vuln_count=$(wc -l < "$workdir/filtered-vulns")
raw_secret_count=$(wc -l < "$workdir/raw-secrets")
filtered_secret_count=$(wc -l < "$workdir/filtered-secrets")
removed_secret_count=$((raw_secret_count - filtered_secret_count))

echo
echo "HIGH/CRITICAL vulnerabilities: raw=$raw_vuln_count filtered=$filtered_vuln_count"
echo "Secret findings:               raw=$raw_secret_count filtered=$filtered_secret_count removed=$removed_secret_count"

status=0

if ! diff -q "$workdir/raw-vulns" "$workdir/filtered-vulns" >/dev/null; then
  echo "FAIL: the ignorefile changed vulnerability findings" >&2
  diff -u "$workdir/raw-vulns" "$workdir/filtered-vulns" >&2 || true
  status=1
else
  echo "OK: vulnerability findings are unchanged by the ignorefile"
fi

if [[ "$filtered_secret_count" -ne 0 ]]; then
  echo "FAIL: secret findings remain after filtering" >&2
  cat "$workdir/filtered-secrets" >&2
  status=1
else
  echo "OK: no secret findings remain after filtering"
fi

# Declared suppressions: "rule<TAB>path-glob" lines. The ignorefile is YAML,
# so use PyYAML rather than jq.
python3 - "$ignorefile" > "$workdir/suppressions" <<'PY'
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as handle:
    payload = yaml.safe_load(handle) or {}

for entry in payload.get("secrets") or []:
    rule = entry.get("id")
    for pattern in entry.get("paths") or []:
        if rule and pattern:
            print(f"{rule}\t{pattern}")
PY

LC_ALL=C comm -13 "$workdir/filtered-secrets" "$workdir/raw-secrets" \
  > "$workdir/removed-secrets"

while IFS=$'\t' read -r target rule; do
  [[ -n "$target" ]] || continue
  matched=0
  while IFS=$'\t' read -r allowed_rule pattern; do
    [[ "$allowed_rule" == "$rule" ]] || continue
    # shellcheck disable=SC2053 # glob match against the declared pattern
    if [[ "$target" == $pattern ]]; then
      matched=1
      break
    fi
  done < "$workdir/suppressions"
  if [[ "$matched" -ne 1 ]]; then
    echo "FAIL: suppressed finding is not covered by the ignorefile: $rule at $target" >&2
    status=1
  fi
done < "$workdir/removed-secrets"

if [[ "$removed_secret_count" -eq 0 ]]; then
  echo "NOTE: the ignorefile suppressed nothing; verify this is expected"
fi

if [[ "$status" -eq 0 ]]; then
  echo "PASS: suppressions are path- and rule-scoped"
fi
exit "$status"
