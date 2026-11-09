# Integration tests

These tests talk to a real Docker daemon. They are skipped by default. They can
run on Fedora through the local socket, on a dedicated Linux server, or inside
the optional KVM VM. Review `docs/host-docker-review.md` before the first run.

## Prerequisites

- Docker Engine with a dedicated context named `haibox` (or set
  `HAIBOX_DOCKER_CONTEXT`).
- A non-root user that can use that context.
- Either the Web Security image built and verified:

  ```bash
  haibox image build web-security
  haibox image verify web-security
  ```

  or an already-present image for the container-shape smoke test, for example:

  ```bash
  HAIBOX_TEST_IMAGE=postgres:16-alpine \
    HAIBOX_RUN_INTEGRATION=1 uv run pytest -m integration -vv
  ```

  The test overrides the image only; the container name, UID/GID, network,
  mounts, capabilities, and resource limits still come from `ContainerSpec`.

## Run

```bash
HAIBOX_RUN_INTEGRATION=1 uv run pytest -m integration -vv
```

Each test creates an engagement under a temporary data directory, creates one
container and one internal network, checks the isolation invariants, and
removes both in a `finally` block. The engagement directory is deleted even if
the test fails.

## What is checked

- the container runs as the configured non-root UID;
- the engagement network is internal and carries the engagement label;
- `/workspace` is writable;
- the scope file is mounted read-only;
- evidence, reports, and secrets directories are not present in the container.

The integration suite does not prove that the network policy blocks every
egress path. That requires the future default-deny network design described in
`docs/threat-model.md`; until then, the internal bridge is only one layer.
