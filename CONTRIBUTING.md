# Contributing

## Development setup

Development runs directly on Fedora with Docker, or on any Linux host with a
reviewed Docker endpoint. A KVM VM is optional. Review
`docs/host-docker-review.md` before running Docker workloads.

```bash
uv sync --extra dev
uv run pytest
uv run ruff check .
uv run mypy src
```

The project targets Python 3.11+. The CLI is installed as `haibox` by
`uv sync`.

## Design rules

- Keep the container specification deny-by-default. New runtime options must be
  added to `ContainerSpec` with validation and tests, not passed through from
  user input.
- Do not add a `privileged`, `pid`, `ipc`, `device`, or arbitrary `volume`
  escape hatch without an ADR and a security review.
- Keep host-only data (secrets, evidence, reports, audit logs) out of container
  mounts.
- Prefer a small, explicit interface over a broad wrapper. The runtime protocol
  is the seam used by the manual CLI today and by the future broker.
- Every command that changes state must be covered by the audit log and by a
  test.
- Do not claim that a feature works until it has run against a real Docker
  endpoint. Update the verification table in `README.md` with the result.

## Commit style

Use Conventional Commits (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`,
`chore:`). Keep commits focused.

## Tests

- Unit tests must not require Docker. They use `tests/fakes.py`.
- Integration tests are marked `integration` and require a dedicated Docker
  context. See `tests/integration/README.md`.
- Security regressions belong in:
  - `tests/unit/test_container_spec.py` (container shape);
  - `tests/unit/test_runtime.py` (Docker adapter and verification);
  - `tests/unit/test_scope.py` (fail-closed matching);
  - `tests/unit/test_evidence.py` (symlinks, duplicate IDs, manifests);
  - `tests/unit/test_audit.py` (hash chain and redaction);
  - `tests/unit/test_secrets.py` (permissions and symlinks);
  - `tests/unit/test_engagement.py` (path traversal and frozen runtime);
  - `tests/unit/test_cli.py` (command wiring and exit codes).
- New CLI commands need a unit test with the fake runtime.
- New network-enforcement code needs negative integration tests, not only a
  positive smoke test.

## Documentation

- Update `docs/architecture.md` and `docs/threat-model.md` when a trust boundary
  or invariant changes.
- Add or supersede an ADR for a decision that affects isolation, secrets,
  scope, or the runtime seam.
- Keep the optional VM runbook in sync with the actual guest configuration.
