"""Shared pytest fixtures.

Unit tests never talk to Docker.  The fake runtime is injected through the
CLI context or used directly by service tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from haibox.cli.app import app
from haibox.cli.context import AppContext
from haibox.engagement import EngagementManager
from haibox.models import HAIBOXConfig, Scope
from haibox.paths import Paths
from tests.fakes import FakeRuntime

# A deterministic non-root identity keeps tests independent of the account
# that runs pytest.  The fake runtime never uses the host UID.
TEST_UID = 1000
TEST_GID = 1000


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(data_dir=tmp_path / "data", config_dir=tmp_path / "config")


@pytest.fixture
def prepared_paths(paths: Paths) -> Paths:
    paths.ensure()
    return paths


@pytest.fixture
def fake_runtime() -> FakeRuntime:
    return FakeRuntime()


@pytest.fixture
def engagement(paths: Paths):
    return EngagementManager(paths).create(
        "demo",
        name="Demo engagement",
        scope=Scope(allowed=["10.10.20.5"], allowed_ports=[443]),
        uid=TEST_UID,
        gid=TEST_GID,
    )


@pytest.fixture
def second_engagement(paths: Paths):
    return EngagementManager(paths).create(
        "second",
        name="Second engagement",
        scope=Scope(allowed=["10.10.20.6"]),
        uid=TEST_UID,
        gid=TEST_GID,
        set_current=False,
    )


@pytest.fixture
def app_context(paths: Paths, fake_runtime: FakeRuntime) -> AppContext:
    paths.ensure()
    return AppContext(
        paths=paths,
        config=HAIBOXConfig(),
        runtime_factory=lambda config, on_command: fake_runtime,
    )


@pytest.fixture
def cli_runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch, fake_runtime: FakeRuntime) -> FakeRuntime:
    """Route every CLI-created runtime to the fake."""

    def factory(settings, on_command=None, *, network_profile=None, runner=None):
        del settings, runner, on_command, network_profile
        return fake_runtime

    monkeypatch.setattr("haibox.cli.context.DockerCli", factory)
    return fake_runtime


def invoke(cli_runner: CliRunner, paths: Paths, *args: str, input_text: str | None = None):
    return cli_runner.invoke(
        app,
        [
            "--data-dir",
            str(paths.data_dir),
            "--config-dir",
            str(paths.config_dir),
            *args,
        ],
        input=input_text,
    )
