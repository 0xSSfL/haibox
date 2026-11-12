"""Eligibility checks for a GUI session.

A GUI session may only run for an engagement that is isolated, has no
external targets, uses the approved GUI image, and whose container is attached
to exactly one network: the engagement network.  The checks are the same ones
the disposable prototype enforced, promoted to product code so that a GUI
session can never run beside a broader network or a broader scope.
"""

from __future__ import annotations

from haibox.errors import ScopeError
from haibox.gui.errors import GuiPreflightError
from haibox.gui.spec import GuiSessionSpec
from haibox.models import Engagement
from haibox.paths import Paths
from haibox.runtime.base import ContainerInfo, ContainerRuntime
from haibox.scope import load_scope


def verify_scope(engagement: Engagement, paths: Paths) -> None:
    """Refuse an engagement whose scope is not empty or not canonical."""

    settings = engagement.runtime
    if settings.network_mode != "isolated":
        raise GuiPreflightError(
            f"engagement {engagement.id!r} uses the {settings.network_mode!r} network "
            "profile; a GUI session requires the 'isolated' profile"
        )
    scope = engagement.scope
    if scope.allowed or scope.allowed_ports:
        raise GuiPreflightError(
            f"engagement {engagement.id!r} has external targets; "
            "a GUI session requires an empty target scope"
        )
    scope_file = paths.scope_file(engagement.id)
    try:
        canonical = load_scope(scope_file)
    except (ScopeError, OSError, ValueError) as exc:
        raise GuiPreflightError(
            f"cannot read the canonical scope file {scope_file}: {exc}"
        ) from exc
    if canonical != scope:
        raise GuiPreflightError(
            f"engagement {engagement.id!r} scope metadata does not match the "
            f"canonical scope file {scope_file}"
        )


def verify_container(
    engagement: Engagement,
    runtime: ContainerRuntime,
    spec: GuiSessionSpec,
    *,
    require_running: bool = True,
) -> ContainerInfo:
    """Refuse a container that is not the engagement's own isolated runner.

    ``require_running`` is relaxed for status queries, which report a stopped
    container instead of failing.
    """

    settings = engagement.runtime
    info = runtime.inspect_container(spec.container)
    if not info.managed:
        raise GuiPreflightError(f"container {spec.container!r} is not HAIBOX-managed")
    if info.engagement != engagement.id:
        raise GuiPreflightError(
            f"container {spec.container!r} does not belong to engagement {engagement.id!r}"
        )
    if require_running and not info.running:
        raise GuiPreflightError(f"container {spec.container!r} is not running")
    if not info.running:
        return info
    if info.network_mode != settings.network_name:
        raise GuiPreflightError(
            f"container {spec.container!r} uses network {info.network_mode!r}; "
            f"expected {settings.network_name!r}"
        )
    if tuple(sorted(info.networks)) != (settings.network_name,):
        raise GuiPreflightError(
            f"container {spec.container!r} is attached to networks "
            f"{sorted(info.networks)!r}; expected only {settings.network_name!r}"
        )
    return info


def verify_gui_preflight(
    engagement: Engagement,
    paths: Paths,
    runtime: ContainerRuntime,
    spec: GuiSessionSpec,
    *,
    require_running: bool = True,
) -> ContainerInfo:
    """Run every GUI eligibility check and return the container information."""

    verify_scope(engagement, paths)
    return verify_container(
        engagement, runtime, spec, require_running=require_running
    )
