"""Opt-in Docker integration test for the GUI session preflight.

The GUI runtime refuses an engagement that is not eligible for a GUI session.
Those refusals are unit-tested with a fake runtime; this test repeats the
negative cases against a real Docker endpoint so that the container state the
checks read is the state Docker actually reports.

The tests are skipped unless ``HAIBOX_RUN_INTEGRATION=1`` and a dedicated
``haibox`` Docker context is available. They need the scanned GUI image
``haibox/gui:0.1.0`` to be present locally.
"""

from __future__ import annotations

import contextlib
import os
import uuid
from collections.abc import Iterator

import pytest

from haibox.engagement import EngagementManager
from haibox.errors import HAIBOXError
from haibox.gui import GuiSessionManager
from haibox.gui.errors import GuiPreflightError
from haibox.models import DockerSettings, Scope
from haibox.paths import Paths
from haibox.runtime.docker_cli import DockerCli
from haibox.runtime.spec import ContainerSpec

RUN_INTEGRATION = os.environ.get("HAIBOX_RUN_INTEGRATION") == "1"
GUI_IMAGE = os.environ.get("HAIBOX_GUI_TEST_IMAGE", "haibox/gui:0.1.0")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not RUN_INTEGRATION,
        reason="set HAIBOX_RUN_INTEGRATION=1 to run against a reviewed Docker endpoint",
    ),
]


@pytest.fixture
def runtime() -> Iterator[DockerCli]:
    context = os.environ.get("HAIBOX_DOCKER_CONTEXT", "haibox")
    cli = DockerCli(DockerSettings(context=context))
    try:
        cli.ensure_available()
    except HAIBOXError as exc:
        pytest.skip(f"dedicated Docker context {context!r} is unavailable: {exc}")
    yield cli


@pytest.fixture
def engagement(tmp_path) -> Iterator[tuple[EngagementManager, Paths, object]]:
    paths = Paths(data_dir=tmp_path / "data", config_dir=tmp_path / "config")
    manager = EngagementManager(paths)
    engagement_id = f"gui-it-{uuid.uuid4().hex[:8]}"
    created = manager.create(
        engagement_id,
        name="GUI integration",
        scope=Scope(),
        image=GUI_IMAGE,
        cpus=2.0,
        memory="2g",
        pids_limit=512,
    )
    try:
        yield manager, paths, created
    finally:
        with contextlib.suppress(HAIBOXError):
            manager.destroy(created.id, force=True)


def _running_container(runtime: DockerCli, paths: Paths, engagement) -> str:
    spec = ContainerSpec.from_engagement(engagement, paths)
    runtime.create_container(spec)
    runtime.start_container(spec.name)
    return spec.name


def test_gui_preflight_accepts_the_engagements_own_container(
    runtime: DockerCli, engagement
) -> None:
    manager, paths, created = engagement
    if not runtime.image_exists(GUI_IMAGE):
        pytest.skip(f"the GUI image {GUI_IMAGE!r} is not present locally")
    _running_container(runtime, paths, created)
    gui = GuiSessionManager(runtime, paths)

    status = gui.status(created.id)

    assert status.container == created.runtime.container_name
    assert status.running is False


def test_gui_preflight_refuses_an_extra_network(
    runtime: DockerCli, engagement
) -> None:
    manager, paths, created = engagement
    if not runtime.image_exists(GUI_IMAGE):
        pytest.skip(f"the GUI image {GUI_IMAGE!r} is not present locally")
    name = _running_container(runtime, paths, created)
    extra = f"{created.runtime.network_name}-extra"
    runtime.network_create(extra, created.id, network_profile="isolated")
    try:
        runtime.network_exists(extra)
        # Attach the container to the second network.
        import subprocess

        subprocess.run(
            ["docker", "--context", runtime.settings.context, "network", "connect", extra, name],
            check=False,
            capture_output=True,
        )
        gui = GuiSessionManager(runtime, paths)

        with pytest.raises(GuiPreflightError, match="attached to networks"):
            gui.status(created.id)
    finally:
        with contextlib.suppress(HAIBOXError):
            runtime.network_remove(extra, network_profile="isolated")


def test_gui_preflight_refuses_external_targets(
    runtime: DockerCli, engagement, tmp_path
) -> None:
    manager, paths, created = engagement
    if not runtime.image_exists(GUI_IMAGE):
        pytest.skip(f"the GUI image {GUI_IMAGE!r} is not present locally")
    _running_container(runtime, paths, created)
    scoped = created.model_copy(update={"scope": Scope(allowed=["192.0.2.10"])})
    gui = GuiSessionManager(runtime, paths)
    gui._engagement = lambda _engagement_id: scoped  # type: ignore[method-assign]

    with pytest.raises(GuiPreflightError, match="external targets"):
        gui.status(created.id)
