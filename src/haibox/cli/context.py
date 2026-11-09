"""Shared CLI context and audit helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import typer
from rich.console import Console

from haibox.audit import AuditLog
from haibox.models import HAIBOXConfig
from haibox.paths import Paths
from haibox.runtime.base import ContainerRuntime
from haibox.runtime.docker_cli import DockerCli

RuntimeFactory = Callable[
    [HAIBOXConfig, Callable[[list[str]], None]], ContainerRuntime
]


@dataclass
class AppContext:
    paths: Paths
    config: HAIBOXConfig
    verbose: bool = False
    quiet: bool = False
    color: bool | None = None
    json_output: bool = False
    assume_yes: bool = False
    debug: bool = False
    console: Console = field(default_factory=Console)
    runtime_factory: RuntimeFactory | None = None
    _runtime: ContainerRuntime | None = None

    def audit(
        self,
        event: str,
        *,
        engagement: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> None:
        AuditLog(self.paths.logs_dir / "audit.jsonl").append(
            event, engagement=engagement, data=data
        )
        if engagement:
            AuditLog(self.paths.engagement_audit_file(engagement)).append(
                event, engagement=engagement, data=data
            )

    def _record_docker_command(self, args: list[str]) -> None:
        self.audit("docker.command", data={"command": args})

    def get_runtime(self) -> ContainerRuntime:
        if self._runtime is None:
            if self.runtime_factory is not None:
                self._runtime = self.runtime_factory(
                    self.config, self._record_docker_command
                )
            else:
                self._runtime = DockerCli(
                    self.config.docker,
                    network_profile=self.config.network.profile,
                    on_command=self._record_docker_command,
                )
        return self._runtime


def get_context(ctx: typer.Context) -> AppContext:
    if not isinstance(ctx.obj, AppContext):
        raise typer.Exit(code=2)
    return ctx.obj
