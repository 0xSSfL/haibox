"""Engagement lifecycle commands."""

from __future__ import annotations

import json

import typer
import yaml
from pydantic import ValidationError as PydanticValidationError
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from haibox.cli.context import get_context
from haibox.engagement import EngagementManager
from haibox.errors import EngagementError, ValidationError
from haibox.models import Scope
from haibox.profiles import load_profile

engagement_app = typer.Typer(help="Create and manage engagements.")
console = Console()


def _scope(
    targets: list[str] | None,
    excludes: list[str] | None,
    ports: list[int] | None,
    notes: str,
) -> Scope:
    try:
        return Scope(
            allowed=targets or [],
            excluded=excludes or [],
            allowed_ports=ports or [],
            notes=notes,
        )
    except PydanticValidationError as exc:
        raise ValidationError(f"invalid scope: {exc}") from exc


@engagement_app.command("init")
def engagement_init(
    ctx: typer.Context,
    engagement_id: str = typer.Argument(..., help="Engagement identifier."),
    name: str | None = typer.Option(None, "--name", help="Human-readable name."),
    profile: str | None = typer.Option(None, "--profile", help="Profile name."),
    target: list[str] | None = typer.Option(
        None, "--target", "-t", help="Allowed target. Repeat for multiple targets."
    ),
    exclude: list[str] | None = typer.Option(
        None, "--exclude", "-x", help="Excluded target or CIDR. Repeat as needed."
    ),
    allowed_port: list[int] | None = typer.Option(
        None, "--allowed-port", "-p", help="Allowed port. Repeat as needed."
    ),
    scope_notes: str = typer.Option("", "--scope-notes", help="Scope notes."),
    image: str | None = typer.Option(None, "--image", help="Override the profile image."),
    cpus: float | None = typer.Option(None, "--cpus", help="CPU limit."),
    memory: str | None = typer.Option(None, "--memory", help="Memory limit, e.g. 4g."),
    pids_limit: int | None = typer.Option(None, "--pids-limit", help="PID limit."),
    uid: int | None = typer.Option(None, "--uid", help="Container UID."),
    gid: int | None = typer.Option(None, "--gid", help="Container GID."),
    notes: str = typer.Option("", "--notes", help="Engagement notes."),
    allow_empty_scope: bool = typer.Option(
        False, "--allow-empty-scope", help="Create an engagement that denies all targets."
    ),
    no_current: bool = typer.Option(False, "--no-current", help="Do not set as current."),
) -> None:
    """Create an engagement with a frozen runtime configuration."""

    obj = get_context(ctx)
    targets = target or []
    if not targets and not allow_empty_scope:
        raise EngagementError("at least one --target is required (or pass --allow-empty-scope)")
    scope = _scope(targets, exclude, allowed_port, scope_notes)
    manager = EngagementManager(obj.paths)
    profile_name = profile or obj.config.defaults.profile
    try:
        engagement = manager.create(
            engagement_id,
            name=name,
            profile_name=profile_name,
            scope=scope,
            image=image,
            cpus=cpus,
            memory=memory,
            pids_limit=pids_limit,
            uid=uid,
            gid=gid,
            notes=notes,
            set_current=not no_current,
        )
    except PydanticValidationError as exc:
        raise ValidationError(f"invalid engagement: {exc}") from exc

    loaded_profile = load_profile(engagement.profile, obj.paths)
    if loaded_profile.status != "active":
        console.print(
            f"[yellow]warning:[/yellow] profile {loaded_profile.name!r} is "
            f"{loaded_profile.status}; its image may not be buildable yet"
        )
    console.print(f"Engagement [bold]{engagement.id}[/bold] created")
    console.print(f"  workspace: {obj.paths.workspace_dir(engagement.id)}")
    console.print(f"  scope:     {obj.paths.scope_file(engagement.id)}")
    console.print(f"  container: {engagement.runtime.container_name}")


@engagement_app.command("list")
def engagement_list(ctx: typer.Context) -> None:
    """List engagements."""

    obj = get_context(ctx)
    engagements = EngagementManager(obj.paths).list()
    if not engagements:
        console.print("No engagements.")
        return
    table = Table(title="Engagements")
    table.add_column("ID")
    table.add_column("Name")
    table.add_column("Profile")
    table.add_column("Status")
    table.add_column("Workspace")
    for engagement in engagements:
        table.add_row(
            escape(engagement.id),
            escape(engagement.name),
            escape(engagement.profile),
            escape(engagement.status),
            escape(str(obj.paths.workspace_dir(engagement.id))),
        )
    console.print(table)


@engagement_app.command("show")
def engagement_show(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON."),
) -> None:
    """Show one engagement."""

    obj = get_context(ctx)
    engagement = EngagementManager(obj.paths).resolve(engagement_id)
    payload = engagement.model_dump(mode="json")
    if json_output:
        typer.echo(json.dumps(payload, indent=2, sort_keys=True))
    else:
        typer.echo(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True))


@engagement_app.command("use")
def engagement_use(
    ctx: typer.Context,
    engagement_id: str = typer.Argument(..., help="Engagement identifier."),
) -> None:
    """Set the current engagement."""

    obj = get_context(ctx)
    EngagementManager(obj.paths).set_current(engagement_id)
    console.print(f"Current engagement: [bold]{engagement_id}[/bold]")


@engagement_app.command("current")
def engagement_current(ctx: typer.Context) -> None:
    """Print the current engagement."""

    obj = get_context(ctx)
    engagement = EngagementManager(obj.paths).current()
    if engagement is None:
        console.print("No current engagement.")
        raise typer.Exit(code=1)
    console.print(engagement.id)


@engagement_app.command("archive")
def engagement_archive(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Archive an engagement without deleting its data."""

    obj = get_context(ctx)
    engagement = EngagementManager(obj.paths).resolve(engagement_id)
    EngagementManager(obj.paths).archive(engagement.id)
    console.print(f"Archived engagement [bold]{engagement.id}[/bold]")


@engagement_app.command("destroy")
def engagement_destroy(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
    force: bool = typer.Option(
        False, "--force", help="Remove a managed container/network and delete an active engagement."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Delete an engagement and its local data."""

    obj = get_context(ctx)
    manager = EngagementManager(obj.paths)
    engagement = manager.resolve(engagement_id)
    if not yes:
        typer.confirm(
            f"Destroy engagement {engagement.id!r} and all local data?",
            abort=True,
        )

    runtime = obj.get_runtime()
    container_name = engagement.runtime.container_name
    network_name = engagement.runtime.network_name
    container = runtime.inspect_container_optional(container_name)
    if container is not None:
        if not force:
            raise EngagementError(
                f"container {container_name!r} still exists; remove it first or pass --force"
            )
        runtime.remove_container(container_name, force=True)
        obj.audit(
            "container.removed",
            engagement=engagement.id,
            data={"name": container_name},
        )
    if network_name != "none" and runtime.network_exists(network_name):
        if not force:
            raise EngagementError(
                f"network {network_name!r} still exists; remove it first or pass --force"
            )
        network_mode = engagement.runtime.network_mode
        runtime.network_remove(
            network_name,
            network_profile=network_mode if network_mode != "none" else None,
        )
        obj.audit(
            "network.removed",
            engagement=engagement.id,
            data={"name": network_name},
        )

    manager.destroy(engagement.id, force=force)
    console.print(f"Destroyed engagement [bold]{engagement.id}[/bold]")


__all__ = ["engagement_app"]
