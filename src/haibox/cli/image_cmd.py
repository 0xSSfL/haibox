"""Image catalog, build, verification, and scan commands."""

from __future__ import annotations

import typer
import yaml
from rich.console import Console
from rich.markup import escape
from rich.table import Table

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
    table = Table(title="HAIBOX image definitions")
    table.add_column("Name")
    table.add_column("Version")
    table.add_column("Status")
    table.add_column("Image reference")
    table.add_column("Depends on")
    table.add_column("Tools")
    for manifest in manifests.values():
        table.add_row(
            escape(manifest.name),
            escape(manifest.version),
            escape(manifest.status),
            escape(manifest.image_ref),
            escape(", ".join(manifest.depends_on) or "-"),
            str(len(manifest.tools)),
        )
    console.print(table)


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
    """Scan a built image with trivy or grype if available."""

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
            "ignorefile": str(ignorefile) if ignorefile else None,
        },
    )
    if result.output:
        typer.echo(result.output)
    if not result.ok:
        raise ImageError(
            f"scanner {result.tool} reported findings or failed "
            f"(exit {result.exit_code})"
        )
    console.print(f"Scan completed for [bold]{manifest.image_ref}[/bold]")
