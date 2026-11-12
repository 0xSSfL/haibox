"""Root Typer application and small top-level commands."""

from __future__ import annotations

import json
import platform
import sys
from pathlib import Path
from typing import Any

import typer
import yaml
from rich import box
from rich.markup import escape
from rich.table import Table

from haibox.cli import ui
from haibox.cli.container_cmd import container_app
from haibox.cli.context import AppContext, get_context
from haibox.cli.engagement_cmd import engagement_app
from haibox.cli.execution_cmd import register as register_execution
from haibox.cli.gui_cmd import gui_app, gui_diagnostics
from haibox.cli.image_cmd import image_app
from haibox.cli.store_cmd import audit_app, evidence_app, scope_app, secret_app
from haibox.cli.vpn_cmd import vpn_app
from haibox.config import load_config, write_default_config
from haibox.errors import HAIBOXError
from haibox.images.catalog import ImageCatalog
from haibox.paths import Paths
from haibox.profiles import list_profiles
from haibox.version import __version__

app = typer.Typer(
    name="haibox",
    help="Isolation-first, manual-first penetration testing platform.",
    no_args_is_help=True,
    add_completion=True,
)
config_app = typer.Typer(help="Inspect and initialise HAIBOX configuration.")
app.add_typer(config_app, name="config")
app.add_typer(engagement_app, name="engagement")
app.add_typer(container_app, name="container")
app.add_typer(image_app, name="image")
app.add_typer(scope_app, name="scope")
app.add_typer(evidence_app, name="evidence")
app.add_typer(secret_app, name="secret")
app.add_typer(audit_app, name="audit")
app.add_typer(vpn_app, name="vpn")
app.add_typer(gui_app, name="gui")
register_execution(app)

console = ui.console


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def _root(
    ctx: typer.Context,
    data_dir: Path | None = typer.Option(
        None, "--data-dir", help="Override the XDG data directory."
    ),
    config_dir: Path | None = typer.Option(
        None, "--config-dir", help="Override the XDG configuration directory."
    ),
    config_file: Path | None = typer.Option(
        None, "--config", help="Use a specific configuration file."
    ),
    verbose: int = typer.Option(
        0, "--verbose", "-v", count=True, help="Verbose diagnostics (repeat for more)."
    ),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="Suppress non-error output."),
    color: bool = typer.Option(False, "--color", help="Force colour output."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colour output."),
    json_output: bool = typer.Option(
        False, "--json", help="Emit machine-readable JSON where supported."
    ),
    assume_yes: bool = typer.Option(
        False, "--yes", "-y", help="Assume yes for confirmation prompts."
    ),
    debug: bool = typer.Option(False, "--debug", help="Show tracebacks for unexpected errors."),
    version_flag: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print the version and exit.",
    ),
) -> None:
    ui.configure(
        quiet=quiet,
        color=False if no_color else (True if color else None),
        json_output=json_output,
        assume_yes=assume_yes,
        debug=debug,
        verbose=verbose,
    )
    paths = Paths.resolve(data_dir=data_dir, config_dir=config_dir)
    paths.ensure()
    config = load_config(paths, config_file=config_file)
    ctx.obj = AppContext(
        paths=paths,
        config=config,
        verbose=bool(verbose),
        quiet=quiet,
        color=False if no_color else (True if color else None),
        json_output=json_output,
        assume_yes=assume_yes,
        debug=debug,
    )
    if verbose:
        ui.muted(f"config: {paths.config_file}")
        ui.muted(f"data:   {paths.data_dir}")


@app.command()
def version() -> None:
    """Print the HAIBOX version."""

    typer.echo(__version__)


@app.command()
def init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Replace an existing configuration."),
) -> None:
    """Initialise the local HAIBOX directories and default configuration."""

    obj = get_context(ctx)
    path = write_default_config(obj.paths, force=force)
    obj.audit("config.initialised", data={"path": str(path)})
    console.print(f"Configuration written to [bold]{path}[/bold]")


@app.command()
def doctor(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Check the local configuration and the dedicated Docker context."""

    obj = get_context(ctx)
    checks: list[dict[str, Any]] = []

    def record(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": ok, "detail": detail})

    record("data directory", obj.paths.data_dir.is_dir(), str(obj.paths.data_dir))
    record("config directory", obj.paths.config_dir.is_dir(), str(obj.paths.config_dir))
    record(
        "configuration",
        True,
        str(obj.paths.config_file)
        if obj.paths.config_file.exists()
        else "built-in defaults",
    )

    try:
        profiles = list_profiles(obj.paths)
        record("profiles", bool(profiles), f"{len(profiles)} profile(s)")
    except HAIBOXError as exc:
        record("profiles", False, str(exc))

    endpoint = obj.config.docker.host or obj.config.docker.context or "(implicit)"
    record(
        "docker endpoint policy",
        bool(obj.config.docker.host or obj.config.docker.context),
        str(endpoint),
    )
    try:
        server = obj.get_runtime().ensure_available()
        record("docker daemon", True, f"server {server} via {endpoint}")
    except HAIBOXError as exc:
        record("docker daemon", False, str(exc))

    for name, ok, detail in gui_diagnostics():
        record(name, ok, detail)

    if json_output:
        typer.echo(json.dumps({"checks": checks}, indent=2, sort_keys=True))
    else:
        table = Table(title="HAIBOX doctor", box=box.ROUNDED, border_style="haibox.border")
        table.add_column("Check", style="haibox.key")
        table.add_column("Status")
        table.add_column("Detail", style="haibox.muted")
        for check in checks:
            status = (
                "[haibox.ok]ok[/haibox.ok]" if check["ok"] else "[haibox.warn]fail[/haibox.warn]"
            )
            table.add_row(str(check["name"]), status, escape(str(check["detail"])))
        console.print(table)

    if not all(bool(check["ok"]) for check in checks):
        raise typer.Exit(code=1)


@app.command()
def info(
    ctx: typer.Context,
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Show the effective environment, paths, profiles, and images."""

    obj = get_context(ctx)
    current: str | None = None
    try:
        from haibox.engagement import EngagementManager

        engagement = EngagementManager(obj.paths).current()
        current = engagement.id if engagement is not None else None
    except HAIBOXError:
        current = None
    profiles = list_profiles(obj.paths)
    images = ImageCatalog().list()
    data = {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "config_file": str(obj.paths.config_file),
        "data_dir": str(obj.paths.data_dir),
        "config_dir": str(obj.paths.config_dir),
        "docker_context": obj.config.docker.context,
        "docker_host": obj.config.docker.host,
        "network_profile": obj.config.network.profile,
        "current_engagement": current,
        "profiles": sorted(profiles),
        "images": {
            name: {"version": manifest.version, "status": manifest.status}
            for name, manifest in images.items()
        },
    }
    if json_output or obj.json_output:
        typer.echo(json.dumps(data, indent=2, sort_keys=True))
        return

    console = ui.get_console()
    console.print(
        f"[[haibox.info]*[/haibox.info]] [bold white]HAIBOX[/bold white] "
        f"[haibox.gold]Security Workstation[/haibox.gold] is currently in version "
        f"[haibox.tag]v{__version__}[/haibox.tag]"
    )
    console.print(
        "[[haibox.info]*[/haibox.info]] More about HAIBOX at: "
        "[haibox.info]https://0xssfl.github.io/haibox/[/haibox.info]\n"
    )

    console.print("[haibox.section]▸ Available images[/haibox.section]")
    img_table = Table(box=box.ROUNDED, border_style="haibox.border")
    img_table.add_column("Image", style="bold white")
    img_table.add_column("Version", style="haibox.value")
    img_table.add_column("Status")
    img_table.add_column("Depends on", style="haibox.info")
    img_table.add_column("Tools", style="haibox.value")
    for name, manifest in images.items():
        if manifest.status == "active":
            status_style = "[haibox.ok]Active[/haibox.ok]"
        else:
            status_style = "[haibox.warn]Experimental[/haibox.warn]"
        img_table.add_row(
            escape(name),
            escape(manifest.version),
            status_style,
            escape(", ".join(manifest.depends_on) or "-"),
            str(len(manifest.tools)),
        )
    console.print(img_table)
    console.print()

    console.print("[haibox.section]▸ Environment & Runtime[/haibox.section]")
    env_table = Table(box=box.ROUNDED, border_style="haibox.border")
    env_table.add_column("Key", style="haibox.key")
    env_table.add_column("Value", style="haibox.value")
    for key, value in data.items():
        if key == "images":
            continue
        if isinstance(value, list):
            rendered = ", ".join(str(item) for item in value) or "(none)"
        else:
            rendered = str(value) if value is not None else "(none)"
        env_table.add_row(key, escape(rendered))
    console.print(env_table)


@app.command()
def tui(ctx: typer.Context) -> None:
    """Launch the interactive terminal menu."""

    from haibox.cli.tui import run_tui

    run_tui(ctx)


@config_app.command("init")
def config_init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Replace an existing configuration."),
) -> None:
    """Write a default configuration file."""

    obj = get_context(ctx)
    path = write_default_config(obj.paths, force=force)
    obj.audit("config.initialised", data={"path": str(path)})
    console.print(f"Configuration written to [bold]{path}[/bold]")


@config_app.command("show")
def config_show(ctx: typer.Context) -> None:
    """Print the effective configuration."""

    obj = get_context(ctx)
    typer.echo(yaml.safe_dump(obj.config.model_dump(mode="json"), sort_keys=False))


@config_app.command("path")
def config_path(ctx: typer.Context) -> None:
    """Print the configuration file path."""

    obj = get_context(ctx)
    typer.echo(str(obj.paths.config_file))


def main() -> None:
    """Console-script entry point with clean expected-error handling."""

    try:
        app()
    except HAIBOXError as exc:
        if ui.options().debug:
            raise
        ui.error(str(exc))
        raise SystemExit(exc.exit_code) from None


if __name__ == "__main__":
    main()
