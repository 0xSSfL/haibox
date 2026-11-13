#!/bin/bash
# Functional smoke tests for the rebuilt web-security tools.
#
# The script runs inside the candidate image and exercises every rebuilt Go
# tool against a local HTTP server, so it needs no external network.
set -u

WORKDIR=$(mktemp -d)
cd "$WORKDIR"

echo "=== prepare the local target ==="
mkdir -p "$WORKDIR/site/.git"
cat > "$WORKDIR/site/index.html" <<'HTML'
<html><head><title>haibox smoke</title></head><body><h1>haibox smoke</h1></body></html>
HTML
cat > "$WORKDIR/site/.git/config" <<'GIT'
[core]
	repositoryformatversion = 0
	filemode = true
[credentials]
	url = https://user:pass@example.invalid/
GIT
printf 'index.html\nadmin\n.git/config\n' > "$WORKDIR/words.txt"

# A tiny server that reflects the query string so dalfox has something to test.
python3 - "$WORKDIR" <<'PY' >"$WORKDIR/site.log" 2>&1 &
import http.server
import socketserver
import sys
import urllib.parse

root = f"{sys.argv[1]}/site"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=root, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if "q" in query:
            body = (
                "<html><head><title>haibox smoke</title></head>"
                f"<body>q={query['q'][0]}</body></html>"
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, *args):
        pass


with socketserver.TCPServer(("127.0.0.1", 18080), Handler) as httpd:
    httpd.serve_forever()
PY
SERVER_PID=$!
sleep 2
if curl -fsS http://127.0.0.1:18080/ >/dev/null; then
    echo "target is up"
else
    echo "TARGET FAILED"
    exit 1
fi

failures=0

run() {
    name="$1"
    shift
    printf '%-22s ' "$name"
    if timeout 120 "$@" > "$WORKDIR/$name.out" 2> "$WORKDIR/$name.err"; then
        echo "exit 0"
    else
        code=$?
        echo "exit $code"
        failures=$((failures + 1))
        head -3 "$WORKDIR/$name.err"
    fi
}

check() {
    label="$1"
    pattern="$2"
    file="$3"
    printf '%-22s ' "$label"
    if grep -qi -- "$pattern" "$file" 2>/dev/null; then
        echo "OK"
    else
        echo "NO MATCH"
        failures=$((failures + 1))
        head -3 "$file" 2>/dev/null
    fi
}

echo "=== version checks ==="
run ffuf-version ffuf -V
run gobuster-version gobuster --version
run nuclei-version nuclei -version
run httpx-version httpx -version
run subfinder-version subfinder -version
run katana-version katana -version
run dalfox-version dalfox version

echo "=== functional checks against the local target ==="
run ffuf-scan ffuf -u http://127.0.0.1:18080/FUZZ -w "$WORKDIR/words.txt" -mc all -fs 404 -s
run gobuster-dir gobuster dir -u http://127.0.0.1:18080 -w "$WORKDIR/words.txt" -q --no-error
run nuclei-scan nuclei -u http://127.0.0.1:18080 -t http/exposures/configs/git-config.yaml -silent
run httpx-scan httpx -u http://127.0.0.1:18080 -silent -title
run katana-scan katana -u http://127.0.0.1:18080 -silent -d 1
run dalfox-scan dalfox url "http://127.0.0.1:18080/?q=1" --silence

echo "=== output checks ==="
check "ffuf matched"      "index.html"      "$WORKDIR/ffuf-scan.out"
check "gobuster matched"  "index.html"      "$WORKDIR/gobuster-dir.out"
check "nuclei matched"    "git-config"      "$WORKDIR/nuclei-scan.out"
check "httpx matched"     "haibox smoke"    "$WORKDIR/httpx-scan.out"
check "katana crawled"    "127.0.0.1"       "$WORKDIR/katana-scan.out"
check "dalfox reflected"  "q="              "$WORKDIR/dalfox-scan.out"

echo "=== module metadata of the shipped binaries ==="
for tool in ffuf gobuster nuclei httpx subfinder katana dalfox; do
    path=$(command -v "$tool")
    printf '%-12s %s\n' "$tool" "$path"
done

# Read the module metadata back out of the shipped binaries.  The build asserts
# it, but this reads it independently from the image that is actually shipped.
if [ -f /smoke/module-requirements.txt ]; then
    echo "=== embedded module versions ==="
    while read -r tool module version; do
        [ -n "${tool:-}" ] || continue
        case "$tool" in '#'*) continue ;; esac
        printf '%-12s %-40s %-10s ' "$tool" "$module" "$version"
        if grep -a -q -P "\t${module}\tv?${version}\t" "/usr/local/bin/${tool}"; then
            echo "OK"
        else
            echo "MISSING"
            failures=$((failures + 1))
        fi
    done < /smoke/module-requirements.txt
fi

kill "$SERVER_PID" 2>/dev/null
wait "$SERVER_PID" 2>/dev/null

if [ "$failures" -ne 0 ]; then
    echo "SMOKE FAILED: $failures check(s) did not pass"
    exit 1
fi
echo "=== smoke complete: all checks passed ==="
