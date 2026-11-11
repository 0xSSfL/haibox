"""Image catalog, build, verification, and scan commands."""

from __future__ import annotations

import typer
import yaml
from rich import box
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from haibox.cli import ui
from haibox.cli.context import get_context
from haibox.errors import ImageError
from haibox.images.builder import ImageBuilder
from haibox.images.catalog import ImageCatalog
from haibox.images.scan import ImageScanner
from haibox.images.verify import ImageVerifier

image_app = typer.Typer(help="Inspect and build HAIBOX images.")
console = Console()


def _catalog() -> ImageCatalog:
    return ImageCatalog()


@image_app.command("list")
def image_list() -> None:
    """List image definitions in the repository."""

    catalog = _catalog()
    manifests = catalog.list()
    if not manifests:
        console.print(f"No image definitions under {catalog.root}")
        return
    table = Table(box=box.ROUNDED, border_style="haibox.border")
    table.add_column("Image", style="bold white")
    table.add_column("Version", style="haibox.value")
    table.add_column("Status")
    table.add_column("Image reference", style="haibox.muted")
    table.add_column("Depends on", style="haibox.info")
    table.add_column("Tools", style="haibox.value")
    for manifest in manifests.values():
        if manifest.status == "active":
            status_style = "[haibox.ok]Active[/haibox.ok]"
        else:
            status_style = "[haibox.warn]Experimental[/haibox.warn]"
        table.add_row(
            escape(manifest.name),
            escape(manifest.version),
            status_style,
            escape(manifest.image_ref),
            escape(", ".join(manifest.depends_on) or "-"),
            str(len(manifest.tools)),
        )
    ui.get_console().print("[haibox.section]▸ Available images[/haibox.section]")
    ui.get_console().print(table)


@image_app.command("inspect")
def image_inspect(
    name: str = typer.Argument(..., help="Image definition name."),
) -> None:
    """Print an image manifest."""

    manifest = _catalog().load(name)
    typer.echo(yaml.safe_dump(manifest.model_dump(mode="json"), sort_keys=False))


@image_app.command("build")
def image_build(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Image definition name."),
    no_cache: bool = typer.Option(False, "--no-cache", help="Disable the Docker build cache."),
    platform: str | None = typer.Option(None, "--platform", help="Target platform."),
    reuse_dependencies: bool = typer.Option(
        False,
        "--reuse-dependencies",
        help="Reuse local dependency images instead of rebuilding them.",
    ),
) -> None:
    """Build an image from its pinned manifest."""

    obj = get_context(ctx)
    catalog = _catalog()
    manifest = catalog.load(name)
    runtime = obj.get_runtime()
    runtime.ensure_available()
    output = ImageBuilder(catalog, runtime).build(
        manifest,
        no_cache=no_cache,
        platform=platform,
        reuse_existing=reuse_dependencies,
    )
    obj.audit("image.built", data={"name": name, "image": manifest.image_ref})
    if output:
        typer.echo(output)
    console.print(f"Built [bold]{manifest.image_ref}[/bold]")


@image_app.command("verify")
def image_verify(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Image definition name."),
    timeout: int = typer.Option(600, "--timeout", help="Verification timeout in seconds."),
) -> None:
    """Run the manifest verification commands in an ephemeral container."""

    obj = get_context(ctx)
    catalog = _catalog()
    manifest = catalog.load(name)
    runtime = obj.get_runtime()
    runtime.ensure_available()
    output = ImageVerifier(catalog, runtime).verify(manifest, timeout=timeout)
    obj.audit("image.verified", data={"name": name, "image": manifest.image_ref})
    if output:
        typer.echo(output)
    console.print(f"Verified [bold]{manifest.image_ref}[/bold]")


@image_app.command("scan")
def image_scan(
    ctx: typer.Context,
    name: str = typer.Argument(..., help="Image definition name."),
    timeout: int = typer.Option(1800, "--timeout", help="Scan timeout in seconds."),
) -> None:
    """Scan a built image with Trivy, falling back to Grype when needed."""

    obj = get_context(ctx)
    catalog = _catalog()
    manifest = catalog.load(name)
    ignorefile = catalog.scan_ignorefile(manifest)
    result = ImageScanner().scan(
        manifest.image_ref, timeout=timeout, ignorefile=ignorefile
    )
    obj.audit(
        "image.scanned",
        data={
            "name": name,
            "image": manifest.image_ref,
            "tool": result.tool,
            "exit_code": result.exit_code,
            "covered": result.covered,
            "findings": result.findings,
            "ignorefile": str(ignorefile) if ignorefile else None,
        },
    )
    if result.output:
        typer.echo(result.output)
    if not result.ok:
        if not result.covered:
            raise ImageError(
                f"scanner {result.tool} did not scan OS packages for "
                f"{manifest.image_ref}; the image OS is unsupported or not detected"
            )
        raise ImageError(
            f"scanner {result.tool} reported {result.findings} HIGH/CRITICAL "
            f"finding(s) or failed (exit {result.exit_code})"
        )
    console.print(f"Scan completed for [bold]{manifest.image_ref}[/bold]")
