"""Interactive shell and one-off command execution."""

from __future__ import annotations

import typer

from haibox.cli.container_cmd import _ensure_running
from haibox.cli.context import get_context
from haibox.engagement import EngagementManager
from haibox.utils.redact import redact_args


def shell(ctx: typer.Context) -> None:
    """Open an interactive shell in the engagement container."""

    obj = get_context(ctx)
    engagement = EngagementManager(obj.paths).resolve(None)
    runtime, name = _ensure_running(obj, engagement)
    obj.audit("shell.opened", engagement=engagement.id, data={"container": name})
    code = runtime.exec_interactive(name, ["/bin/bash"])
    if code == 127:
        code = runtime.exec_interactive(name, ["/bin/sh"])
    obj.audit(
        "shell.closed",
        engagement=engagement.id,
        data={"container": name, "exit_code": code},
    )
    if code != 0:
        raise typer.Exit(code=code)


def run(
    ctx: typer.Context,
    command: list[str] = typer.Argument(
        ..., help="Command and arguments. Use -- before command options."
    ),
) -> None:
    """Run a one-off command in the engagement container."""

    obj = get_context(ctx)
    engagement = EngagementManager(obj.paths).resolve(None)
    runtime, name = _ensure_running(obj, engagement)
    obj.audit(
        "command.executed",
        engagement=engagement.id,
        data={"container": name, "command": redact_args(command)},
    )
    result = runtime.exec_capture(name, command)
    if result.stdout:
        typer.echo(result.stdout, nl=not result.stdout.endswith("\n"))
    if result.stderr:
        typer.echo(result.stderr, nl=not result.stderr.endswith("\n"), err=True)
    if result.exit_code != 0:
        raise typer.Exit(code=result.exit_code)


def register(app: typer.Typer) -> None:
    app.command("shell")(shell)
    app.command("run")(run)
