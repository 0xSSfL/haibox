"""Container lifecycle commands."""

from __future__ import annotations

import dataclasses
import json

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from haibox.cli.context import AppContext, get_context
from haibox.engagement import EngagementManager
from haibox.errors import ContainerError
from haibox.models import Engagement
from haibox.runtime.base import ContainerRuntime
from haibox.runtime.spec import ContainerSpec, ensure_workspace_ownership

container_app = typer.Typer(help="Manage engagement containers.")
console = Console()


def _engagement(obj: AppContext, engagement_id: str | None) -> Engagement:
    return EngagementManager(obj.paths).resolve(engagement_id)


def _spec(obj: AppContext, engagement: Engagement) -> ContainerSpec:
    return ContainerSpec.from_engagement(engagement, obj.paths)


def _ensure_running(obj: AppContext, engagement: Engagement) -> tuple[ContainerRuntime, str]:
    runtime = obj.get_runtime()
    spec = _spec(obj, engagement)
    info = runtime.inspect_container_optional(spec.name)
    if info is None:
        ensure_workspace_ownership(spec.workspace, spec.uid, spec.gid)
        runtime.create_container(spec)
        obj.audit(
            "container.created",
            engagement=engagement.id,
            data={"name": spec.name, "image": spec.image},
        )
    if info is None or not info.running:
        runtime.start_container(spec.name)
        obj.audit(
            "container.started",
            engagement=engagement.id,
            data={"name": spec.name},
        )
    return runtime, spec.name


@container_app.command("create")
def container_create(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Create the engagement container without starting it."""

    obj = get_context(ctx)
    engagement = _engagement(obj, engagement_id)
    runtime = obj.get_runtime()
    spec = _spec(obj, engagement)
    if runtime.inspect_container_optional(spec.name) is not None:
        raise ContainerError(f"container already exists: {spec.name}")
    ensure_workspace_ownership(spec.workspace, spec.uid, spec.gid)
    container_id = runtime.create_container(spec)
    obj.audit(
        "container.created",
        engagement=engagement.id,
        data={"name": spec.name, "image": spec.image},
    )
    console.print(f"Created container [bold]{spec.name}[/bold] ({container_id[:12]})")


@container_app.command("start")
def container_start(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Start the engagement container."""

    obj = get_context(ctx)
    engagement = _engagement(obj, engagement_id)
    runtime = obj.get_runtime()
    spec = _spec(obj, engagement)
    runtime.start_container(spec.name)
    obj.audit("container.started", engagement=engagement.id, data={"name": spec.name})
    console.print(f"Started [bold]{spec.name}[/bold]")


@container_app.command("stop")
def container_stop(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Stop the engagement container."""

    obj = get_context(ctx)
    engagement = _engagement(obj, engagement_id)
    runtime = obj.get_runtime()
    spec = _spec(obj, engagement)
    runtime.stop_container(spec.name)
    obj.audit("container.stopped", engagement=engagement.id, data={"name": spec.name})
    console.print(f"Stopped [bold]{spec.name}[/bold]")


@container_app.command("restart")
def container_restart(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Restart the engagement container."""

    obj = get_context(ctx)
    engagement = _engagement(obj, engagement_id)
    runtime = obj.get_runtime()
    spec = _spec(obj, engagement)
    runtime.restart_container(spec.name)
    obj.audit("container.restarted", engagement=engagement.id, data={"name": spec.name})
    console.print(f"Restarted [bold]{spec.name}[/bold]")


@container_app.command("rm")
def container_remove(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
    force: bool = typer.Option(False, "--force", help="Force removal of a running container."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Remove the engagement container."""

    obj = get_context(ctx)
    engagement = _engagement(obj, engagement_id)
    runtime = obj.get_runtime()
    spec = _spec(obj, engagement)
    if not yes:
        typer.confirm(f"Remove container {spec.name!r}?", abort=True)
    runtime.remove_container(spec.name, force=force)
    obj.audit("container.removed", engagement=engagement.id, data={"name": spec.name})
    console.print(f"Removed [bold]{spec.name}[/bold]")


@container_app.command("ps")
def container_ps(
    ctx: typer.Context,
    all_containers: bool = typer.Option(
        True, "--all/--running", help="Show stopped containers too."
    ),
) -> None:
    """List HAIBOX-managed containers."""

    obj = get_context(ctx)
    containers = obj.get_runtime().list_containers(all=all_containers)
    if not containers:
        console.print("No HAIBOX containers.")
        return
    table = Table(title="HAIBOX containers")
    table.add_column("Name")
    table.add_column("Engagement")
    table.add_column("State")
    table.add_column("Image")
    for item in containers:
        table.add_row(
            escape(item.name),
            escape(item.engagement or ""),
            escape(item.state),
            escape(item.image),
        )
    console.print(table)


@container_app.command("inspect")
def container_inspect(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Inspect the engagement container."""

    obj = get_context(ctx)
    engagement = _engagement(obj, engagement_id)
    info = obj.get_runtime().inspect_container(_spec(obj, engagement).name)
    typer.echo(json.dumps(dataclasses.asdict(info), indent=2, sort_keys=True))


@container_app.command("logs")
def container_logs(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
    tail: int = typer.Option(200, "--tail", "-n", help="Number of lines."),
) -> None:
    """Show engagement container logs."""

    obj = get_context(ctx)
    engagement = _engagement(obj, engagement_id)
    output = obj.get_runtime().container_logs(_spec(obj, engagement).name, tail=tail)
    typer.echo(output, nl=not output.endswith("\n"))
