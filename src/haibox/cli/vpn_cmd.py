"""Host-only VPN profile and gateway commands."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import typer
import yaml
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from haibox.cli.context import AppContext, get_context
from haibox.errors import VpnError
from haibox.paths import validate_vpn_name
from haibox.vpn import VpnStore, VpnType

vpn_app = typer.Typer(help="Manage host-only VPN profiles and gateways.")
console = Console()


def _store(obj: AppContext) -> VpnStore:
    return VpnStore(obj.paths)


def _gateway_name(name: str) -> str:
    return f"haibox-vpn-{name}"


@vpn_app.command("add")
def vpn_add(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="VPN profile name."),
    vpn_type: str = typer.Option(
        ..., "--type", help="VPN type: wireguard or openvpn."
    ),
    config: Path = typer.Option(
        ..., "--config", help="Path to the WireGuard or OpenVPN configuration."
    ),
    description: str = typer.Option("", "--description", help="Profile description."),
    force: bool = typer.Option(False, "--force", help="Replace an existing profile."),
) -> None:
    """Store and validate a host-only VPN profile."""

    obj = get_context(ctx)
    vpn_type_value = vpn_type.lower()
    if vpn_type_value not in ("wireguard", "openvpn"):
        raise VpnError(f"unsupported VPN type: {vpn_type!r}")
    profile = _store(obj).add(
        name,
        cast(VpnType, vpn_type_value),
        config,
        description=description,
        force=force,
    )
    obj.audit(
        "vpn.profile.added",
        data={"profile": profile.name, "type": profile.type},
    )
    console.print(
        f"VPN profile [bold]{profile.name}[/bold] stored as {profile.type}. "
        "The configuration file is host-only and was not displayed."
    )


@vpn_app.command("list")
def vpn_list(ctx: typer.Context) -> None:
    """List stored VPN profiles."""

    obj = get_context(ctx)
    profiles = _store(obj).list()
    if not profiles:
        console.print("No VPN profiles. Add one with 'haibox vpn add'.")
        return
    table = Table(title="VPN profiles")
    table.add_column("Name", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Description")
    table.add_column("Created", no_wrap=True)
    for profile in profiles:
        table.add_row(
            escape(profile.name),
            escape(profile.type),
            escape(profile.description),
            escape(profile.created_at.isoformat()),
        )
    console.print(table, crop=False)


@vpn_app.command("show")
def vpn_show(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="VPN profile name."),
) -> None:
    """Show VPN profile metadata without printing secret material."""

    obj = get_context(ctx)
    store = _store(obj)
    profile = store.load(name)
    typer.echo(yaml.safe_dump(profile.model_dump(mode="json"), sort_keys=False))
    console.print(
        f"Config file: [bold]{escape(str(store.config_path(name)))}[/bold] "
        "(contents are not displayed)",
        soft_wrap=True,
    )


@vpn_app.command("remove")
def vpn_remove(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="VPN profile name."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip the confirmation prompt."),
) -> None:
    """Remove a stored VPN profile."""

    obj = get_context(ctx)
    if not yes:
        typer.confirm(f"Remove VPN profile {name!r}?", abort=True)
    runtime = obj.get_runtime()
    gateway = runtime.inspect_container_optional(_gateway_name(name))
    if gateway is not None:
        raise VpnError(
            f"VPN gateway {gateway.name!r} exists; run 'haibox vpn down {name}' first"
        )
    _store(obj).remove(name)
    obj.audit("vpn.profile.removed", data={"profile": name})
    console.print(f"VPN profile [bold]{name}[/bold] removed.")


@vpn_app.command("up")
def vpn_up(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="VPN profile name."),
) -> None:
    """Start the trusted gateway for a VPN profile.

    This starts the tunnel container only. Runner routing and kill-switch
    enforcement are not implemented yet.
    """

    obj = get_context(ctx)
    store = _store(obj)
    profile = store.load(name)
    spec = store.gateway_spec(name)
    runtime = obj.get_runtime()
    if not runtime.image_exists(spec.image):
        raise VpnError(
            f"VPN gateway image {spec.image!r} is not present; build it first "
            "(the gateway image definition is not part of this milestone)"
        )
    if runtime.inspect_container_optional(spec.name) is not None:
        raise VpnError(
            f"VPN gateway {spec.name!r} already exists; run 'haibox vpn down {name}' first"
        )
    runtime.create_vpn_gateway(spec)
    runtime.start_container(spec.name)
    obj.audit(
        "vpn.gateway.started",
        data={
            "profile": profile.name,
            "container": spec.name,
            "network": spec.network,
            "routing": "not-implemented",
        },
    )
    console.print(
        f"VPN gateway [bold]{escape(spec.name)}[/bold] started for profile "
        f"[bold]{escape(profile.name)}[/bold]."
    )
    console.print(
        "[yellow]Runner routing and kill-switch enforcement are not implemented yet.[/yellow] "
        "Engagement containers remain on their internal networks."
    )


@vpn_app.command("down")
def vpn_down(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="VPN profile name."),
) -> None:
    """Stop and remove the gateway for a VPN profile."""

    obj = get_context(ctx)
    # Teardown must not depend on a readable profile: a damaged config or a
    # revoked credential must never strand a running gateway.
    validate_vpn_name(name)
    gateway_name = _gateway_name(name)
    network = f"haibox-vpn-{name}-net"
    runtime = obj.get_runtime()
    gateway = runtime.inspect_container_optional(gateway_name)
    if gateway is not None:
        if gateway.running:
            runtime.stop_container(gateway_name)
        runtime.remove_container(gateway_name, force=True)
    if runtime.network_exists(network):
        runtime.vpn_network_remove(network, name)
    obj.audit("vpn.gateway.stopped", data={"profile": name, "container": gateway_name})
    console.print(f"VPN gateway for [bold]{escape(name)}[/bold] is stopped.")


@vpn_app.command("status")
def vpn_status(
    ctx: typer.Context,
    name: str | None = typer.Argument(None, help="VPN profile name."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show gateway state and the current routing limitation."""

    obj = get_context(ctx)
    store = _store(obj)
    profiles = [store.load(name)] if name else store.list()
    if not profiles:
        console.print("No VPN profiles. Add one with 'haibox vpn add'.")
        return
    runtime = obj.get_runtime()
    rows: list[dict[str, str]] = []
    for profile in profiles:
        spec = store.gateway_spec(profile.name)
        gateway = runtime.inspect_container_optional(spec.name)
        rows.append(
            {
                "name": profile.name,
                "type": profile.type,
                "gateway": spec.name if gateway is not None else "not running",
                "state": gateway.status if gateway is not None else "-",
                "routing": "not implemented",
            }
        )
    if json_output:
        typer.echo(json.dumps({"profiles": rows}, indent=2))
        return
    table = Table(title="VPN status")
    table.add_column("Name", no_wrap=True)
    table.add_column("Type", no_wrap=True)
    table.add_column("Gateway", no_wrap=True)
    table.add_column("State")
    table.add_column("Runner routing")
    for row in rows:
        table.add_row(
            escape(row["name"]),
            escape(row["type"]),
            escape(row["gateway"]),
            escape(row["state"]),
            escape(row["routing"]),
        )
    console.print(table, crop=False)
    console.print(
        "[yellow]VPN gateways do not route engagement traffic yet; "
        "kill-switch behaviour is not implemented.[/yellow]"
    )
