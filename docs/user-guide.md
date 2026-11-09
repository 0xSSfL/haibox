# HAIBOX user guide

This guide explains what HAIBOX is, how the pieces fit together, and how to use
the CLI and the interactive menu. It describes the current source tree, not a
future release. Where a capability is a placeholder, the text says so.

---

## 1. What HAIBOX is

HAIBOX is an isolation-first, manual-first penetration-testing platform. It
runs a disposable toolkit container per engagement and keeps the operator's
secrets, evidence, reports, and audit log on the host.

It is not a wrapper around another pentest distribution. The CLI, container
specification, image build system, engagement model, evidence store, audit
chain, and (future) VPN/AI adapters are independent code.

### Design rules

1. **One engagement, one container, one network.** An engagement cannot address
   another engagement's container, workspace, secrets, or evidence.
2. **The host is the trusted computing base.** Host-only data is never mounted
   into a runner.
3. **Deny by default.** Every container option is constructed by
   `ContainerSpec`; there is no pass-through of arbitrary Docker flags.
4. **The manual lane works without AI.** The AI broker, when added, is an
   optional client of the runtime, never the owner of the Docker socket.
5. **Fail closed.** An empty scope denies everything. An unknown profile, an
   unmanaged container, or a missing dedicated Docker context is an error.

### Trust boundary

```text
operator account
└── haibox CLI
    └── Docker Engine (rootful)
        ├── haibox-<engagement>       runner container
        ├── haibox-<engagement>-net   isolated bridge, no host address
        └── host-only data: secrets, evidence, reports, audit

optional: KVM VM or dedicated server around the whole block
```

Rootful Docker is root-equivalent. On a general-purpose workstation the host is
inside the trust boundary. Use the optional VM or a dedicated server for hostile
targets.

---

## 2. Requirements

- Linux with Docker Engine 28 or newer (the isolated gateway mode requires it).
- A dedicated Docker context named `haibox` (recommended), or a reviewed
  `docker.host`/`docker.context` in the configuration.
- Python 3.11+ and `uv` for development, or an installed `haibox` package.

Create the context once:

```bash
docker context create haibox --docker "host=unix:///var/run/docker.sock"
```

Do not point HAIBOX at the `default` context. The configuration rejects it by
default because sharing a daemon with unrelated workloads widens the boundary.

---

## 3. First run

```bash
uv sync --extra dev
uv run haibox init          # write ~/.config/haibox/config.yaml
uv run haibox doctor        # check directories, profiles, endpoint, daemon
uv run haibox info          # show the effective environment
```

`haibox doctor` exits non-zero if any check fails. `haibox info --json` emits
the same data as JSON for scripts.

### Quick start: one engagement

```bash
# 1. Create an engagement with a frozen profile and an explicit scope.
uv run haibox engagement init my-lab \
  --name "Home lab" \
  --profile web-security \
  --target 192.0.2.10 \
  --allowed-port 443

# 2. Start the runner and open a shell.
uv run haibox shell

# 3. Run a one-off command (everything after -- goes to the container).
uv run haibox run -- nmap -sV 192.0.2.10

# 4. Inspect, stop, and clean up.
uv run haibox container ps
uv run haibox container stop
uv run haibox engagement destroy my-lab --yes
```

The current engagement is stored in `~/.local/share/haibox/current`. Commands
that take an engagement id fall back to the current engagement when the argument
is omitted.

---

## 4. Core concepts

| Concept | What it means |
|---|---|
| **Engagement** | The unit of isolation. It owns a profile snapshot, scope, workspace, evidence directory, reports, secrets, and audit chain. |
| **Profile** | Declarative YAML with image, network mode, resource limits, capabilities, environment, and tool list. Six built-ins ship: `core`, `network-security`, `web-security`, `ad-security`, `osint`, `full`. The Web, Core, and Network Security images are active; the others are experimental. |
| **Scope** | Allowed targets, exclusions, allowed ports, and notes. The matcher is fail-closed: an empty scope denies everything. |
| **Runner** | The engagement container. It is created from `ContainerSpec`, not from user-supplied Docker flags. |
| **Workspace** | Per-engagement host directory mounted at `/workspace`. It is the only writable host bind. |
| **Evidence** | Host-side files with a SHA-256 manifest. Files are copied in; the runner never mounts the evidence directory. |
| **Secret** | Host-side key/value store, mode 0600, plaintext at rest. Values are never printed by the CLI. |
| **Audit** | Hash-chained JSONL. Every mutation and Docker command is appended; `audit verify` checks the chain. |
| **Image definition** | `images/<name>/Dockerfile` plus `manifest.yaml` with a pinned base digest, snapshot, tool versions, and verification commands. |

### Engagement lifecycle

```text
engagement init
  ├── validate profile (Pydantic, extra="forbid")
  ├── create <data>/engagements/<id>/
  │     ├── engagement.yaml
  │     ├── scope.json
  │     ├── workspace/       (0700)
  │     ├── evidence/
  │     ├── reports/
  │     ├── secrets.json     (0600)
  │     └── audit.jsonl
  └── set current (unless --no-current)

container create/start
  ├── create per-engagement internal bridge
  │     └── isolated gateway mode: no host address
  ├── create runner from ContainerSpec
  │     ├── --cap-drop ALL
  │     ├── --security-opt no-new-privileges:true
  │     ├── read-only root, tmpfs /tmp and /run
  │     ├── non-root uid/gid
  │     └── only workspace + read-only scope mounted
  └── post-create inspection; mismatch => remove

shell / run
  ├── ensure container exists and is running
  ├── execute inside the runner
  └── audit shell.opened/closed or command.executed (argv redacted)

engagement archive/destroy
  ├── archive: move data, keep it
  └── destroy: remove container, network, workspace, evidence, reports,
               secrets, audit; refuse unmanaged resources
```

---

## 5. Interactive menu (TUI)

```bash
uv run haibox tui
```

The menu is a thin dispatcher over the same CLI commands, so all validation and
audit behaviour is identical. It offers:

- **Engagements** — list, create, show, select.
- **Containers** — list, start, stop, logs, and the shell command to run.
- **Images** — list, inspect, build, verify, scan.
- **Evidence** — list, add, verify.
- **Audit** — verify, tail.
- **Scope** — show, check.
- **Doctor** and **Environment information**.

Interactive shell sessions are not run inside the menu; the menu prints the
exact `haibox shell <id>` command so the terminal is handed to Docker directly.
`--yes` makes the menu non-interactive for confirmations; `--quiet` hides the
banner and status panel.

---

## 6. Global options

These options come before the command:

| Option | Effect |
|---|---|
| `--data-dir PATH` | Override the XDG data directory. |
| `--config-dir PATH` | Override the XDG configuration directory. |
| `--config PATH` | Use a specific configuration file. |
| `-v`, `--verbose` | Verbose diagnostics. Repeatable. |
| `-q`, `--quiet` | Suppress non-error output. Errors still print. |
| `--color` | Force colour output. |
| `--no-color` | Disable colour output. Also honours `NO_COLOR`. |
| `--json` | Prefer machine-readable JSON where a command supports it. |
| `-y`, `--yes` | Assume yes for confirmation prompts. |
| `--debug` | Show tracebacks for unexpected errors. |
| `-V`, `--version` | Print the version and exit. |
| `--install-completion` | Install shell completion for the current shell. |
| `--show-completion` | Print the completion script. |

Colour is semantic: success is green, warnings yellow, errors red, headings
magenta, muted text dim. `NO_COLOR=1` and `--no-color` are equivalent for
disabling it.

---

## 7. Command reference

### 7.1 Top level

| Command | Purpose |
|---|---|
| `version` | Print the version. |
| `init [--force]` | Write the default configuration. |
| `doctor [--json]` | Check directories, profiles, endpoint policy, daemon. |
| `info [--json]` | Show version, paths, Docker endpoint, profiles, images, current engagement. |
| `tui` | Interactive menu. |
| `shell` | Open an interactive shell in the current engagement runner. |
| `run -- CMD...` | Run a one-off command in the runner. |
| `config init/show/path` | Configuration helpers. |

### 7.2 `engagement`

| Command | Purpose |
|---|---|
| `init [ID] [options]` | Create an engagement. Options: `--name`, `--profile`, `--target` (repeatable), `--exclude` (repeatable), `--allowed-port` (repeatable), `--scope-notes`, `--image`, `--cpus`, `--memory`, `--pids-limit`, `--uid`, `--gid`, `--notes`, `--allow-empty-scope`, `--no-current`. |
| `list` | List engagements with status and profile. |
| `show [ID] [--json]` | Show one engagement. |
| `use ID` | Set the current engagement. |
| `current` | Print the current engagement. |
| `archive [ID]` | Archive without deleting data. |
| `destroy [ID] [--force] [--yes]` | Delete the engagement and its local data. |

### 7.3 `container`

| Command | Purpose |
|---|---|
| `create [ID]` | Create the runner without starting it. |
| `start [ID]` | Start the runner. |
| `stop [ID]` | Stop the runner. |
| `restart [ID]` | Restart the runner. |
| `rm [ID] [--force] [--yes]` | Remove the runner. |
| `ps [--all/--running]` | List HAIBOX-managed containers. |
| `inspect [ID]` | Print container info as JSON. |
| `logs [ID] [-n N]` | Show container logs. |

### 7.4 `image`

| Command | Purpose |
|---|---|
| `list` | List image definitions, status, image reference, tool count. |
| `inspect NAME` | Print the manifest. |
| `build NAME [--no-cache] [--platform] [--reuse-dependencies]` | Build from the pinned manifest; local `depends_on` bases are built first unless explicitly reused. |
| `verify NAME [--timeout]` | Run manifest verification commands as a non-root user. |
| `scan NAME [--timeout]` | Run Trivy/Grype with the image-local ignore file. Exits non-zero on HIGH/CRITICAL findings. |

### 7.5 `scope`

| Command | Purpose |
|---|---|
| `show [--engagement ID]` | Print the scope file. |
| `check TARGET [--port N] [--engagement ID]` | Evaluate a target; exits non-zero if denied. |

### 7.6 `evidence`

| Command | Purpose |
|---|---|
| `add PATH [--note] [--tag] [--engagement ID]` | Copy a file into the host-side evidence store and record its SHA-256. |
| `list [--engagement ID]` | List entries. |
| `verify [--engagement ID]` | Verify every file against the manifest. |
| `rm ID [--yes]` | Remove a file and its manifest entry. |

### 7.7 `secret`

| Command | Purpose |
|---|---|
| `set NAME [--engagement ID]` | Store a secret without echoing it. |
| `list [--engagement ID]` | List names and timestamps; values are never printed. |
| `rm NAME [--yes]` | Remove a secret. |

### 7.8 `audit`

| Command | Purpose |
|---|---|
| `verify [--engagement ID]` | Verify the hash chain. |
| `tail [-n N] [--engagement ID]` | Print recent entries. |

### 7.9 `vpn`

| Command | Purpose |
|---|---|
| `add NAME --config PATH [--vpn-type] [--description] [--force]` | Validate and store a host-only profile. |
| `list` / `show NAME` | Metadata only; secret material is never printed. |
| `remove NAME [--yes]` | Remove a profile. |
| `up NAME` / `down NAME` | Start/stop the separate gateway container. |
| `status [--json]` | Gateway state and the current routing limitation. |

The VPN gateway image is not built in M1. `vpn up` fails cleanly; transparent
routing and the kill switch are not implemented.

---

## 8. Images

An image definition is a directory under `images/`:

```text
images/web-security/
  Dockerfile
  manifest.yaml
  trivyignore.yaml   (optional, scoped suppressions only)
```

The manifest is the source of truth for the base digest, Debian snapshot, build
args, pinned tool versions, and verification commands. The builder labels the
image with a digest of the tool list, so drift is detectable.

```bash
uv run haibox image list
uv run haibox image build web-security
uv run haibox image verify web-security
uv run haibox image scan web-security
```

`image verify` runs every `verify` command from the manifest in an ephemeral
container as uid/gid `65534`, with no network. It fails on the first non-zero
command.

`image scan` uses Trivy when present, then Grype. It passes only the image-local
`trivyignore.yaml`; there is no global suppression file and no
`--ignore-unfixed`. A non-zero exit means HIGH/CRITICAL findings remain or the
scanner failed.

### Current image status

| Image | Status | Notes |
|---|---|---|
| `web-security` | Active, built | Debian 13 snapshot, 15 pinned tools. |
| `core` | Active, built | Shared Debian 13 snapshot base, 18 tools. |
| `network-security` | Active, built | Core plus capture, DNS, and discovery tools. |
| `ad-security` | Experimental, built | Impacket, Kerberos, LDAP, and SMB tooling; verification passed. |
| `osint` | Experimental, built | DNS, metadata, and public-source tooling; verification passed. |
| `full` | Experimental, built | Combined Web + Network + AD + OSINT package set; verification passed. |

Image definitions declare local dependencies. `haibox image build full`
builds the declared bases in order and rejects dependency cycles;
`--reuse-dependencies` skips an exact local tag that is already present. All
six images build and verify. Only Web Security has a recorded Trivy scan, so the
other variants must not be treated as vulnerability-cleared. The Web Security
image is pinned to a Debian snapshot and a base digest. Its verification and
scan results are recorded in [`image-validation.md`](image-validation.md),
[`image-catalog.md`](image-catalog.md), and the top-level `README.md`.

---

## 9. Security model in practice

- The runner network is a per-engagement internal bridge with Docker's
  `isolated` gateway mode. The host has no address on the bridge, and the runner
  has no default route.
- `--cap-drop ALL`; a profile may add only `NET_RAW` or `NET_BIND_SERVICE`.
- `--security-opt no-new-privileges:true`; read-only root; `tmpfs` for `/tmp`
  and `/run`; non-root uid/gid.
- Only the workspace is writable. The scope file is read-only. Secrets,
  evidence, reports, and audit logs are host-only.
- Container creation is followed by an inspection that compares the actual
  shape to `ContainerSpec`; a mismatch removes the container.
- HAIBOX refuses to operate on containers and networks that lack its managed
  labels.
- The scope matcher never resolves hostnames, exclusions always win, and a port
  allowlist requires a port. This makes ambiguous targets deny, not allow.

The isolated profile blocks host services, the host LAN, Docker bridges, public
IPv4/IPv6, DNS, HTTP, and the metadata address. Container-to-container traffic on
the same engagement network still works.

### What the scope file is not

The scope file is a safety control, not a legal authorisation. It does not
enforce reachability at the network layer yet; a tool that ignores the file can
still attempt an out-of-scope connection. Network-enforced scope is M2 work
(ADR-0010).

---

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| `doctor` fails on Docker | `docker context ls`; the context must exist and the daemon must answer. |
| `image build` runs out of memory | BuildKit apt layers are split; keep `GOMAXPROCS=2` and `-p=2`. Close other builds. |
| `image scan` exits 1 | Read the table; findings are real. Check `docs/vulnerability-risk-register.md` before changing pins. |
| Container is removed after creation | The post-create inspection found a shape mismatch. Run with `-v` and inspect the Docker command in the audit log. |
| `scope check` denies a valid target | The matcher does not resolve hostnames. Use an IP/CIDR, and remember exclusions win. |
| Shell exits 127 | The image has no `/bin/bash`; the CLI falls back to `/bin/sh`. |
| TUI shows no profiles | The built-ins are counted from the package; a missing package data directory is an installation error. |

Logs:

- global audit: `~/.local/share/haibox/logs/audit.jsonl`
- per-engagement audit: `~/.local/share/haibox/engagements/<id>/audit.jsonl`
- Docker command records: `docker.command` entries in the same chain

---

## 11. Development and verification

```bash
uv sync --extra dev
uv run ruff check .
uv run mypy src
uv run pytest -q tests/unit
HAIBOX_RUN_INTEGRATION=1 uv run pytest -q tests/integration/test_docker_smoke.py
```

The integration tests create a real container and network, then remove them.
They are skipped unless `HAIBOX_RUN_INTEGRATION=1` and the `haibox` context is
available. Set `HAIBOX_TEST_IMAGE` to test the container shape with an
already-present image.

Image checks:

```bash
uv run haibox image build web-security
uv run haibox image verify web-security
uv run haibox image scan web-security
TRIVY_BIN=trivy bash scripts/verify-trivy-suppressions.sh \
  haibox/web-security:0.1.0 images/web-security/trivyignore.yaml
```

See [`architecture.md`](architecture.md), [`threat-model.md`](threat-model.md),
[`roadmap.md`](roadmap.md), and the ADRs for the design rationale.
