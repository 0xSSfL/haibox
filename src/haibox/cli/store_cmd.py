"""Scope, evidence, secret, and audit commands."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from haibox.audit import AuditLog
from haibox.cli.context import AppContext, get_context
from haibox.engagement import EngagementManager
from haibox.evidence import EvidenceStore
from haibox.scope import ScopeMatcher, scope_to_json
from haibox.secrets import SecretStore

scope_app = typer.Typer(help="Inspect and evaluate engagement scope.")
evidence_app = typer.Typer(help="Manage host-side evidence.")
secret_app = typer.Typer(help="Manage host-only engagement secrets.")
audit_app = typer.Typer(help="Verify and inspect audit logs.")
console = Console()


def _engagement_id(obj: AppContext, value: str | None) -> str:
    return EngagementManager(obj.paths).resolve(value).id


@scope_app.command("show")
def scope_show(
    ctx: typer.Context,
    engagement_id: str | None = typer.Argument(None, help="Engagement identifier."),
) -> None:
    """Print the scope file mounted into the container."""

    obj = get_context(ctx)
    resolved = _engagement_id(obj, engagement_id)
    typer.echo(scope_to_json(EngagementManager(obj.paths).scope(resolved)), nl=False)


@scope_app.command("check")
def scope_check(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="Host, URL, IP, or CIDR member to check."),
    port: int | None = typer.Option(None, "--port", "-p", help="Target port."),
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Engagement identifier."
    ),
) -> None:
    """Evaluate a target against the engagement scope."""

    obj = get_context(ctx)
    resolved = _engagement_id(obj, engagement_id)
    scope = EngagementManager(obj.paths).scope(resolved)
    decision = ScopeMatcher(scope).check(target, port=port)
    obj.audit(
        "scope.checked",
        engagement=resolved,
        data={
            "target": decision.target,
            "port": decision.port,
            "allowed": decision.allowed,
            "reason": decision.reason,
        },
    )
    status = "green" if decision.allowed else "red"
    label = "allowed" if decision.allowed else "denied"
    target = escape(decision.target)
    if decision.port is not None:
        target += f":{decision.port}"
    console.print(f"[{status}]{label}[/] {target} — {escape(decision.reason)}")
    if not decision.allowed:
        raise typer.Exit(code=1)


@evidence_app.command("add")
def evidence_add(
    ctx: typer.Context,
    source: Path = typer.Argument(
        ..., exists=True, dir_okay=False, readable=True, help="File to preserve as evidence."
    ),
    note: str = typer.Option("", "--note", help="Evidence note."),
    tag: list[str] | None = typer.Option(None, "--tag", help="Evidence tag."),
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Engagement identifier."
    ),
) -> None:
    """Copy a file into the host-side evidence store."""

    obj = get_context(ctx)
    resolved = _engagement_id(obj, engagement_id)
    store = EvidenceStore(obj.paths.evidence_dir(resolved))
    entry = store.add(source, note=note, tags=tag or [])
    obj.audit(
        "evidence.added",
        engagement=resolved,
        data={"id": entry.id, "sha256": entry.sha256, "size": entry.size},
    )
    console.print(f"Evidence [bold]{entry.id}[/bold]")
    console.print(f"  SHA-256: {entry.sha256}")
    console.print(f"  size:    {entry.size}")


@evidence_app.command("list")
def evidence_list(
    ctx: typer.Context,
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Engagement identifier."
    ),
) -> None:
    """List evidence entries."""

    obj = get_context(ctx)
    resolved = _engagement_id(obj, engagement_id)
    entries = EvidenceStore(obj.paths.evidence_dir(resolved)).list()
    if not entries:
        console.print("No evidence.")
        return
    table = Table(title=f"Evidence for {resolved}")
    table.add_column("ID", no_wrap=True, min_width=35)
    table.add_column("Original name", no_wrap=True)
    table.add_column("Size")
    table.add_column("Added")
    table.add_column("Note")
    for entry in entries:
        table.add_row(
            escape(entry.id),
            escape(entry.original_name),
            str(entry.size),
            escape(entry.added_at),
            escape(entry.note),
        )
    console.print(table, crop=False)


@evidence_app.command("verify")
def evidence_verify(
    ctx: typer.Context,
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Engagement identifier."
    ),
) -> None:
    """Verify evidence files against the manifest."""

    obj = get_context(ctx)
    resolved = _engagement_id(obj, engagement_id)
    result = EvidenceStore(obj.paths.evidence_dir(resolved)).verify()
    obj.audit(
        "evidence.verified",
        engagement=resolved,
        data={"valid": result.valid, "entries": result.entries, "errors": result.errors},
    )
    if result.valid:
        console.print(f"Evidence valid ({result.entries} entries).")
        return
    for error in result.errors:
        console.print(f"[red]{error}[/red]")
    raise typer.Exit(code=1)


@evidence_app.command("rm")
def evidence_remove(
    ctx: typer.Context,
    evidence_id: str = typer.Argument(..., help="Evidence identifier."),
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Engagement identifier."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Remove an evidence file and its manifest entry."""

    obj = get_context(ctx)
    resolved = _engagement_id(obj, engagement_id)
    if not yes:
        typer.confirm(f"Remove evidence {evidence_id!r}?", abort=True)
    EvidenceStore(obj.paths.evidence_dir(resolved)).remove(evidence_id)
    obj.audit(
        "evidence.removed",
        engagement=resolved,
        data={"id": evidence_id},
    )
    console.print(f"Removed evidence [bold]{evidence_id}[/bold]")


@secret_app.command("set")
def secret_set(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Secret name."),
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Engagement identifier."
    ),
) -> None:
    """Store a secret without printing it."""

    obj = get_context(ctx)
    resolved = _engagement_id(obj, engagement_id)
    value = typer.prompt("Secret value", hide_input=True, confirmation_prompt=True)
    SecretStore(obj.paths.secrets_file(resolved)).set(name, value)
    obj.audit("secret.set", engagement=resolved, data={"name": name})
    console.print(f"Stored secret [bold]{name}[/bold]")


@secret_app.command("list")
def secret_list(
    ctx: typer.Context,
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Engagement identifier."
    ),
) -> None:
    """List secret names and timestamps; values are never printed."""

    obj = get_context(ctx)
    resolved = _engagement_id(obj, engagement_id)
    entries = SecretStore(obj.paths.secrets_file(resolved)).list()
    if not entries:
        console.print("No secrets.")
        return
    table = Table(title=f"Secret names for {resolved}")
    table.add_column("Name")
    table.add_column("Created")
    table.add_column("Updated")
    for entry in entries:
        table.add_row(entry.name, entry.created_at.isoformat(), entry.updated_at.isoformat())
    console.print(table)


@secret_app.command("rm")
def secret_remove(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Secret name."),
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Engagement identifier."
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
) -> None:
    """Remove a secret."""

    obj = get_context(ctx)
    resolved = _engagement_id(obj, engagement_id)
    if not yes:
        typer.confirm(f"Remove secret {name!r}?", abort=True)
    SecretStore(obj.paths.secrets_file(resolved)).remove(name)
    obj.audit("secret.removed", engagement=resolved, data={"name": name})
    console.print(f"Removed secret [bold]{name}[/bold]")


def _audit_path(obj: AppContext, engagement_id: str | None) -> tuple[object, Path]:
    if engagement_id:
        engagement = EngagementManager(obj.paths).resolve(engagement_id)
        return engagement, obj.paths.engagement_audit_file(engagement.id)
    return None, obj.paths.logs_dir / "audit.jsonl"


@audit_app.command("verify")
def audit_verify(
    ctx: typer.Context,
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Verify the engagement log instead of the platform log."
    ),
) -> None:
    """Verify the hash chain of an audit log."""

    obj = get_context(ctx)
    _, path = _audit_path(obj, engagement_id)
    result = AuditLog(path).verify()
    if result.valid:
        console.print(f"Audit log valid ({result.entries} entries).")
        return
    console.print(f"[red]Audit log invalid:[/red] {result.error}")
    raise typer.Exit(code=1)


@audit_app.command("tail")
def audit_tail(
    ctx: typer.Context,
    lines: int = typer.Option(20, "--lines", "-n", help="Number of entries."),
    engagement_id: str | None = typer.Option(
        None, "--engagement", help="Read the engagement log instead of the platform log."
    ),
) -> None:
    """Print recent audit entries."""

    if lines < 1:
        raise typer.BadParameter("lines must be positive")
    obj = get_context(ctx)
    _, path = _audit_path(obj, engagement_id)
    for entry in AuditLog(path).read(limit=lines):
        typer.echo(json.dumps(entry, sort_keys=True))


__all__ = ["audit_app", "evidence_app", "scope_app", "secret_app"]
