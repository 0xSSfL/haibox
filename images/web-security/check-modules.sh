#!/bin/sh
# Verify the module metadata of the Go tools built into the web-security image.
#
# usage: check-modules.sh <modinfo-dir> <requirements-file> <forbidden-file>
#        check-modules.sh compare <file> <pinned-copy>
#
# The requirements file lists "<tool> <module> <version>" triples: the named
# tool must embed that module version.  The forbidden file lists
# "<module> <version>" pairs: no binary may embed one of them.
#
# Each entry is read line by line and split on whitespace, so a module path
# and its version stay paired even when the list has many entries.
#
# The compare mode fails when a file differs from the copy that was pinned
# before the build, so a build that rewrites a committed requirement file is
# rejected instead of shipping it.
set -eu

usage() {
    echo "usage: check-modules.sh <modinfo-dir> <requirements-file> <forbidden-file>" >&2
    echo "       check-modules.sh compare <file> <pinned-copy>" >&2
}

if [ "$#" -lt 1 ]; then
    usage
    exit 2
fi

if [ "$1" = "compare" ]; then
    if [ "$#" -ne 3 ]; then
        usage
        exit 2
    fi
    file="$2"
    pinned="$3"
    if [ ! -f "$file" ] || [ ! -f "$pinned" ]; then
        echo "FATAL: cannot compare ${file} with ${pinned}" >&2
        exit 1
    fi
    if cmp -s "$file" "$pinned"; then
        echo "OK: $(basename "$file") is unchanged"
        exit 0
    fi
    echo "FATAL: $(basename "$file") was modified during the build" >&2
    diff -u "$pinned" "$file" 2>/dev/null | head -20 >&2 || true
    exit 1
fi

if [ "$#" -ne 3 ]; then
    usage
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
