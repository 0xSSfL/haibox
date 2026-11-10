# AGENTS.md — HAIBOX

HAIBOX is a Python 3.11+ Typer CLI plus a catalog of Docker pentest images.
The package and import name is **`haibox`**.

## Source of truth

- CLI entrypoint: `src/haibox/cli/app.py` (`haibox = "haibox.cli.app:main"`).
- Runtime seam: `src/haibox/runtime/base.py`; Docker adapter: `runtime/docker_cli.py`.
- Container shape: `src/haibox/runtime/spec.py` — deny-by-default, no flag pass-through.
- Built-in profiles: `src/haibox/data/profiles/`. The top-level `profiles/`
  directory is stale; do not edit it as the source of truth.
- Image definitions: `images/<name>/manifest.yaml` plus its `Dockerfile`.
- Architecture: `docs/architecture.md`; trust model: `docs/threat-model.md`;
  recorded results: `docs/verification-status.md`.

## Commands

```bash
uv sync --locked --extra dev          # setup
make check                            # ruff -> mypy -> pytest
uv run pytest tests/unit/test_scope.py -q
uv run pytest -q -k <test_name>
uv run haibox info
uv run haibox doctor
```

- Development work uses the in-repo `.worktree/` directory, inside the project
  path; never use an external worktree path. Run `uv`, `make`, and tests from
  that worktree root; do not assume the primary checkout is on the active
  branch.
- Run Python/CLI commands through `uv run`; do not rely on a globally installed
  `haibox`.
- `make install` runs `uv sync --extra dev` without `--locked`; prefer the
  locked command for reproducible environments.
- `make check` is the local gate. There is no CI or pre-commit config.
- The CLI expects a dedicated `haibox` Docker context and refuses `default`;
  Docker Engine 28+ is required for the isolated gateway mode.
- Root options such as `--json`, `--data-dir`, and `--config-dir` go before the
  subcommand (`uv run haibox --json info`).

## Testing quirks

- Unit tests must not require Docker; they use `tests/fakes.py::FakeRuntime`.
- CLI tests inject the fake via `AppContext.runtime_factory` or by patching
  `haibox.cli.context.DockerCli`. Use `tests.conftest.invoke` with
  `--data-dir`/`--config-dir` to isolate XDG state.
- Integration tests are opt-in and mutate real Docker state:
  `HAIBOX_RUN_INTEGRATION=1 uv run pytest -m integration -vv`.
- Integration prerequisites: a dedicated `haibox` Docker context (the
  `DockerSettings` default) or `HAIBOX_DOCKER_CONTEXT`; `HAIBOX_TEST_IMAGE`
  overrides the image. Do not enable these by default.
- `mypy` checks `src` only; tests are not type-checked. Ruff line length is 100.
- Runtime state is XDG (`~/.local/share/haibox`, `~/.config/haibox`); override
  with `HAIBOX_DATA_DIR` / `HAIBOX_CONFIG_DIR` or `--data-dir` / `--config-dir`.

## Security invariants

- Never add `privileged`, host `pid`/`ipc`/network, devices, published ports, or
  arbitrary host bind mounts. New runtime options belong in `ContainerSpec`
  with validation and tests.
- Host-only data (secrets, evidence, reports, audit) must never be mounted into
  a runner. Only `workspace/` is writable; the scope file is read-only.
- Destructive operations require the `haibox.managed=true` label. Engagement IDs
  are validated before any path is built.
- The default network profile is `isolated` (Docker isolated gateway mode). The
  legacy `internal` profile is removed; do not reintroduce it.
- As of this tree, `scoped` is a prototype, not working scope enforcement:
  nftables only hooks `forward`, so host services and Docker embedded DNS are
  not covered, and there are no negative integration tests. Do not claim
  network-enforced scope until those exist.
- Every state-changing command needs an audit entry and a test. Do not claim a
  feature works until it has run against a real Docker endpoint and the result
  is recorded in `README.md` and `docs/verification-status.md`.
- Do not modify the Docker daemon, host firewall, SELinux policy, or unrelated
  host services. Use the CLI for container/network cleanup so managed-label
  checks and audit entries run.

## Image workflow

- `manifest.yaml` is the source of truth for the base digest, Debian snapshot,
  build args, tool versions, `depends_on`, and verify commands. Update it and
  the Dockerfile together.
- Six variants exist: `core`, `network-security`, `web-security`,
  `ad-security`, `osint`, `full`; local tags are `haibox/<name>:0.1.0`.
- `uv run haibox image build <name>` builds `depends_on` first. Add
  `--reuse-dependencies` to avoid rebuilding an already-scanned base; rebuilding
  changes the digest and invalidates scan evidence.
- `image verify` runs manifest commands as uid `65534` with no network.
  `image scan` uses Trivy then Grype and exits 1 on HIGH/CRITICAL.
- All six images have recorded Trivy baselines in `docs/image-catalog.md`, and
  the gate is open for every one. `images/README.md` and `docs/user-guide.md`
  still say only Web Security was scanned; trust the catalog matrix.
- Do not add `--ignore-unfixed`, global ignores, or suppress package/Go-module
  findings. `web-security`, `osint`, and `full` have scoped
  `images/*/trivyignore.yaml` files only for the pinned Nuclei secret fixtures;
  prove they stay path/rule scoped with
  `scripts/verify-trivy-suppressions.sh` (needs `jq`, and honours `TRIVY_BIN`).
- Keep `GOMAXPROCS=2` and `-p=2` in Go build layers and keep apt layers split;
  BuildKit has previously exceeded 6 GB RSS. Do not bump the Debian snapshot or
  base digest without updating the manifest and validation docs.
- The image catalog resolves `images/` from the source checkout; set
  `HAIBOX_IMAGES_DIR` when running from another location.

## Docs and commits

- Trust-boundary or invariant changes require `docs/architecture.md`,
  `docs/threat-model.md`, and an ADR under `docs/adr/`.
- Record verification in `docs/verification-status.md` and
  `docs/image-validation.md`; update `docs/roadmap.md` for milestone state and
  `docs/user-guide.md` for user-facing commands.
- Use Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), one
  focused change per commit.

## PR workflow

After a feature or fix is complete and `make check` passes:

1. Branch from `main` (for example `feat/<short-name>`); do not commit feature
   work directly to `main`.
2. Commit with Conventional Commits and push the branch to `origin`.
3. Open a PR against `main`:
   `gh pr create --base main --head <branch> --title "<type>: <summary>" --body-file <file>`.
4. The PR description must be clean and include:
   - a short summary of the behaviour change and why it is needed;
   - affected modules and paths;
   - verification commands and results (`make check`, integration tests, image
     build/verify/scan where relevant);
   - a task checklist using `- [x]` for completed work and `- [ ]` for
     follow-ups;
   - links to the relevant ADR or issue.
5. Merge/push to `main` only after the checks pass and the description is
   complete. Never merge unverified or failing work.
