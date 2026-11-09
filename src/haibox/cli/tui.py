"""Interactive terminal UI.

The TUI is a thin menu over the same commands the CLI exposes. It deliberately
does not own any state or bypass validation: every action is dispatched through
the Typer application, so the same deny-by-default checks apply.
"""

from __future__ import annotations

import sys

import typer
from rich.table import Table
from typer.testing import CliRunner

from haibox.cli import ui

_runner = CliRunner()


def _invoke(args: list[str]) -> None:
    """Run a CLI command in-process and print its output verbatim."""

    # Imported lazily: app.py imports this module to register the command.
    from haibox.cli.app import app

    result = _runner.invoke(app, args, color=True)
    if result.output:
        sys.stdout.write(result.output)
    if result.exception is not None and not isinstance(result.exception, SystemExit):
        ui.error(str(result.exception))
    if result.exit_code not in (0, None):
        ui.warn(f"command exited with status {result.exit_code}")


def _pause() -> None:
    if not ui.options().assume_yes:
        typer.prompt("Press Enter to continue", default="", show_default=False)


def _engagements() -> None:
    while True:
        choice = ui.choose(
            "Engagements",
            [
                ("list", "List engagements"),
                ("init", "Create an engagement"),
                ("show", "Show an engagement"),
                ("use", "Select the current engagement"),
                ("back", "Back"),
            ],
        )
        if choice == "back":
            return
        if choice == "list":
            _invoke(["engagement", "list"])
        elif choice == "init":
            name = ui.ask("Name", default="engagement")
            profile = ui.ask("Profile", default="web-security")
            target = ui.ask("Target (blank to skip)", default="")
            args = ["engagement", "init", "--name", name, "--profile", profile]
            if target:
                args.extend(["--target", target])
            _invoke(args)
        elif choice == "show":
            engagement_id = ui.ask("Engagement id")
            _invoke(["engagement", "show", engagement_id])
        elif choice == "use":
            engagement_id = ui.ask("Engagement id")
            _invoke(["engagement", "use", engagement_id])
        _pause()


def _containers() -> None:
    while True:
        choice = ui.choose(
            "Containers",
            [
                ("ps", "List containers"),
                ("start", "Start an engagement container"),
                ("shell", "Show the shell command"),
                ("stop", "Stop a container"),
                ("logs", "Show container logs"),
                ("back", "Back"),
            ],
        )
        if choice == "back":
            return
        if choice == "ps":
            _invoke(["container", "ps", "--all"])
        elif choice in {"start", "stop", "logs"}:
            engagement_id = ui.ask("Engagement id")
            if choice == "start":
                _invoke(["container", "start", engagement_id])
            elif choice == "stop":
                _invoke(["container", "stop", engagement_id])
            else:
                _invoke(["container", "logs", engagement_id])
        elif choice == "shell":
            engagement_id = ui.ask("Engagement id")
            ui.info(f"Run: [haibox.key]haibox shell {engagement_id}[/haibox.key]")
        _pause()


def _images() -> None:
    while True:
        choice = ui.choose(
            "Images",
            [
                ("list", "List image definitions"),
                ("inspect", "Inspect an image manifest"),
                ("build", "Build an image"),
                ("verify", "Verify an image"),
                ("scan", "Scan an image"),
                ("back", "Back"),
            ],
        )
        if choice == "back":
            return
        if choice == "list":
            _invoke(["image", "list"])
        else:
            name = ui.ask("Image name", default="web-security")
            if choice == "inspect":
                _invoke(["image", "inspect", name])
            elif choice == "build":
                _invoke(["image", "build", name])
            elif choice == "verify":
                _invoke(["image", "verify", name])
            else:
                _invoke(["image", "scan", name])
        _pause()


def _evidence() -> None:
    while True:
        choice = ui.choose(
            "Evidence",
            [
                ("list", "List evidence"),
                ("add", "Add a file"),
                ("verify", "Verify manifests"),
                ("back", "Back"),
            ],
        )
        if choice == "back":
            return
        engagement_id = ui.ask("Engagement id (blank for current)", default="")
        args = ["evidence", choice] if choice != "add" else ["evidence", "add"]
        if choice == "add":
            path = ui.ask("File path")
            args.extend([path])
        if engagement_id:
            args.extend(["--engagement", engagement_id])
        _invoke(args)
        _pause()


def _audit() -> None:
    while True:
        choice = ui.choose(
            "Audit",
            [
                ("verify", "Verify the hash chain"),
                ("tail", "Show recent entries"),
                ("back", "Back"),
            ],
        )
        if choice == "back":
            return
        engagement_id = ui.ask("Engagement id (blank for global)", default="")
        args = ["audit", choice]
        if engagement_id:
            args.extend(["--engagement", engagement_id])
        _invoke(args)
        _pause()


def _scope() -> None:
    while True:
        choice = ui.choose(
            "Scope",
            [
                ("show", "Show the scope"),
                ("check", "Check a target"),
                ("back", "Back"),
            ],
        )
        if choice == "back":
            return
        engagement_id = ui.ask("Engagement id (blank for current)", default="")
        args = ["scope", choice]
        if choice == "check":
            target = ui.ask("Target")
            args.append(target)
        if engagement_id:
            args.extend(["--engagement", engagement_id])
        _invoke(args)
        _pause()


def _status_panel(ctx: typer.Context) -> None:
    from haibox.cli.context import AppContext

    obj = ctx.obj
    if not isinstance(obj, AppContext):
        return
    table = Table(title="HAIBOX", border_style="haibox.border", show_header=False)
    table.add_column("Key", style="haibox.key")
    table.add_column("Value", style="haibox.value")
    table.add_row("Config", str(obj.paths.config_file))
    table.add_row("Data", str(obj.paths.data_dir))
    from haibox.profiles import list_profiles

    table.add_row("Profiles", str(len(list_profiles(obj.paths))))
    table.add_row("Docker", obj.config.docker.context or obj.config.docker.host or "implicit")
    ui.get_console().print(table)


def run_tui(ctx: typer.Context) -> None:
    """Run the interactive menu until the operator quits."""

    ui.banner()
    while True:
        _status_panel(ctx)
        choice = ui.choose(
            "Main menu",
            [
                ("engagements", "Engagements"),
                ("containers", "Containers"),
                ("images", "Images"),
                ("evidence", "Evidence"),
                ("audit", "Audit"),
                ("scope", "Scope"),
                ("doctor", "Run doctor"),
                ("info", "Environment information"),
                ("quit", "Quit"),
            ],
        )
        if choice == "quit":
            ui.muted("bye")
            return
        if choice == "engagements":
            _engagements()
        elif choice == "containers":
            _containers()
        elif choice == "images":
            _images()
        elif choice == "evidence":
            _evidence()
        elif choice == "audit":
            _audit()
        elif choice == "scope":
            _scope()
        elif choice == "doctor":
            _invoke(["doctor"])
            _pause()
        elif choice == "info":
            _invoke(["info"])
            _pause()
