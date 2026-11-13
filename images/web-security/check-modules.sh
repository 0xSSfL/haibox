#!/bin/sh
# Verify the module metadata of the Go tools built into the web-security image.
#
# usage: check-modules.sh <modinfo-dir> <requirements-file> <forbidden-file>
#
# The requirements file lists "<tool> <module> <version>" triples: the named
# tool must embed that module version.  The forbidden file lists
# "<module> <version>" pairs: no binary may embed one of them.
#
# Each entry is read line by line and split on whitespace, so a module path
# and its version stay paired even when the list has many entries.
set -eu

if [ "$#" -ne 3 ]; then
    echo "usage: check-modules.sh <modinfo-dir> <requirements-file> <forbidden-file>" >&2
    exit 2
fi

modinfo_dir="$1"
requirements="$2"
forbidden="$3"

if [ ! -d "$modinfo_dir" ]; then
    echo "FATAL: no module metadata directory: ${modinfo_dir}" >&2
    exit 1
fi
for list in "$requirements" "$forbidden"; do
    if [ ! -f "$list" ]; then
        echo "FATAL: no such list: ${list}" >&2
        exit 1
    fi
done

fail=0

# "<tool> <module> <version>" -> the tool must embed that module version.
while read -r tool module version || [ -n "${tool:-}" ]; do
    [ -n "${tool:-}" ] || continue
    case "$tool" in '#'*) continue ;; esac
    info="${modinfo_dir}/${tool}.modinfo"
    if [ ! -f "$info" ]; then
        echo "FATAL: no module metadata for ${tool} (${info})" >&2
        fail=1
        continue
    fi
    if ! awk -v m="$module" -v v="$version" \
            '$1=="dep" && $2==m && ($3==v || $3=="v" v) {f=1} END{exit !f}' "$info"; then
        echo "FATAL: ${tool} does not embed ${module} ${version}" >&2
        awk -v m="$module" '$1=="dep" && $2==m {print "  found " $2 " " $3}' "$info" >&2
        fail=1
    fi
done < "$requirements"

# "<module> <version>" -> no binary may embed that module version.
while read -r module version || [ -n "${module:-}" ]; do
    [ -n "${module:-}" ] || continue
    case "$module" in '#'*) continue ;; esac
    for info in "${modinfo_dir}"/*.modinfo; do
        [ -f "$info" ] || continue
        if awk -v m="$module" -v v="$version" \
                '$1=="dep" && $2==m && ($3==v || $3=="v" v) {f=1} END{exit !f}' "$info"; then
            echo "FATAL: $(basename "$info") still embeds vulnerable ${module} ${version}" >&2
            fail=1
        fi
    done
done < "$forbidden"

if [ "$fail" -ne 0 ]; then
    echo "module metadata check failed" >&2
    exit 1
fi

echo "OK: module metadata matches the committed requirement set"
