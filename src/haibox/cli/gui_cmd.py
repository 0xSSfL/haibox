"""Optional GUI session commands.

The commands are prepared but stay disabled until the GUI image is accepted:
the gate is the catalog status of the GUI image, which is an owner decision
recorded in ``images/gui/manifest.yaml``.  There is no user-facing flag that
enables the GUI.  The gate belongs to whoever controls the catalog the CLI
resolves, which is the same trust level as changing the image definition
itself.
"""

from __future__ import annotations

import json
import signal
from pathlib import Path
from typing import Any

import typer
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from haibox.cli import ui
from haibox.cli.context import AppContext, get_context
from haibox.engagement import EngagementManager
from haibox.errors import HAIBOXError
from haibox.gui import APPROVED_GUI_IMAGE, GuiRelay, GuiSessionManager, GuiSessionSpec
from haibox.gui.errors import GuiError
from haibox.images.catalog import ImageCatalog

gui_app = typer.Typer(help="Manage optional GUI sessions in an engagement runner.")
console = Console()


class GuiNotEnabled(HAIBOXError):
    """The GUI capability is not enabled for this installation."""

    exit_code = 2


def gui_enabled() -> tuple[bool, str]:
    """Return whether the GUI may run, and why not when it may not.

    The GUI is enabled only when its image is an *active* catalog image.  The
    image is experimental while its base is a pre-release snapshot, so the
    owner has to promote it in ``images/gui/manifest.yaml`` before any GUI
    session can start.
    """

    try:
        manifest = ImageCatalog().load("gui")
    except HAIBOXError as exc:
        return False, f"the GUI image definition is unavailable: {exc}"
    if manifest.status != "active":
        return False, (
            f"the GUI image {manifest.image_ref} is {manifest.status}, not active; "
            "promote it in images/gui/manifest.yaml after the image gate is accepted"
        )
    if manifest.image_ref != APPROVED_GUI_IMAGE:
        return False, (
            f"the GUI image definition points at {manifest.image_ref}, not the "
            f"approved {APPROVED_GUI_IMAGE}"
        )
    return True, ""


def _require_enabled(obj: AppContext, engagement: str | None = None) -> None:
    enabled, reason = gui_enabled()
    if not enabled:
        if obj is not None:
            obj.audit(
                "gui.session_refused",
                engagement=engagement,
                data={"reason": f"the GUI is not enabled: {reason}"},
            )
        raise GuiNotEnabled(f"the GUI is not enabled: {reason}")


def _manager(obj: AppContext) -> GuiSessionManager:
    return GuiSessionManager(
        obj.get_runtime(),
        obj.paths,
        audit=lambda event, engagement, data: obj.audit(
            event, engagement=engagement, data=dict(data)
        ),
    )


def _engagement_id(obj: AppContext, engagement_id: str | None) -> str:
    engagement = EngagementManager(obj.paths).resolve(engagement_id)
    return engagement.id


def _emit(obj: AppContext, payload: dict[str, Any], render) -> None:
    if obj.json_output:
        ui.console.print_json(json.dumps(payload, sort_keys=True))
        return
    render(payload)


def _status_table(payload: dict[str, Any]) -> None:
    table = Table(box=box.SIMPLE_HEAD)
    table.add_column("Field")
    table.add_column("Value")
    for key in sorted(payload):
        value = payload[key]
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value) or "-"
        table.add_row(escape(str(key)), escape(str(value)))
    console.print(table)


@gui_app.command("start")
def gui_start(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Start a GUI session for an engagement."""

    obj = get_context(ctx)
    _require_enabled(obj, engagement_id)
    engagement = _engagement_id(obj, engagement_id)
    manager = _manager(obj)
    try:
        status = manager.prepare(engagement)
    except HAIBOXError as exc:
        obj.audit("gui.session_refused", engagement=engagement, data={"reason": str(exc)})
        raise
    payload = status.to_dict()
    _emit(obj, payload, lambda data: _status_table(data))


@gui_app.command("attach")
def gui_attach(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
    socket_path: Path | None = typer.Option(
        None,
        "--socket",
        help="Socket path inside an owner-controlled 0700 directory.",
    ),
) -> None:
    """Serve the GUI session on a local Unix-domain socket."""

    obj = get_context(ctx)
    _require_enabled(obj, engagement_id)
    engagement = _engagement_id(obj, engagement_id)
    manager = _manager(obj)
    status = manager.status(engagement)
    if not status.running:
        raise GuiError(
            f"no GUI session is running for engagement {engagement!r}; "
            "start one with 'haibox gui start'"
        )
    runtime = obj.get_runtime()
    engagement_model = EngagementManager(obj.paths).load(engagement)
    spec = GuiSessionSpec.from_engagement(engagement_model)
    target = socket_path or (obj.paths.logs_dir / "gui" / f"{engagement}.sock")
    relay = GuiRelay(runtime, spec, target)
    obj.audit(
        "gui.relay_started",
        engagement=engagement,
        data={"socket": str(target)},
    )

    def _request_stop(*_args: object) -> None:
        relay.request_stop()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, _request_stop)
    console.print(f"GUI relay listening on {target}")
    client = " ".join(
        [
            "xpra",
            "attach",
            f"socket://{target}",
            f"--password-file={status.credential_file}",
            *spec.client_args(),
        ]
    )
    console.print(f"Attach with: {client}")
    try:
        relay.serve_forever()
    finally:
        obj.audit("gui.relay_stopped", engagement=engagement, data={"socket": str(target)})


@gui_app.command("stop")
def gui_stop(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Stop the GUI session of an engagement."""

    obj = get_context(ctx)
    # Stopping is never gated: an operator must always be able to revoke a
    # session, even after the GUI image was demoted.
    engagement = _engagement_id(obj, engagement_id)
    manager = _manager(obj)
    try:
        manager.stop(engagement)
    except HAIBOXError as exc:
        obj.audit("gui.session_stop_failed", engagement=engagement, data={"reason": str(exc)})
        raise
    payload = {"engagement": engagement, "stopped": True}
    _emit(obj, payload, lambda data: _status_table(data))


@gui_app.command("status")
def gui_status(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Show the state of the GUI session of an engagement."""

    obj = get_context(ctx)
    # Status is never gated: it only reads state.
    engagement = _engagement_id(obj, engagement_id)
    manager = _manager(obj)
    payload = manager.status(engagement).to_dict()
    _emit(obj, payload, lambda data: _status_table(data))


def gui_diagnostics() -> list[tuple[str, bool, str]]:
    """Return the doctor checks for the optional GUI capability.

    A disabled GUI is not a failure: the capability is optional and its gate
    is an owner decision. Only a broken image definition is reported as a
    failed check.
    """

    checks: list[tuple[str, bool, str]] = []
    try:
        manifest = ImageCatalog().load("gui")
    except HAIBOXError as exc:
        # The GUI is optional: a missing image definition is reported, but it
        # never makes the installation unhealthy.
        checks.append(("gui image definition", True, f"not installed: {exc}"))
        return checks
    checks.append(
        ("gui image definition", True, f"{manifest.image_ref} is {manifest.status}")
    )
    if manifest.status == "active":
        checks.append(("gui capability", True, "enabled"))
    else:
        checks.append(
            (
                "gui capability",
                True,
                f"disabled: the GUI image is {manifest.status}, not active",
            )
        )
    return checks
