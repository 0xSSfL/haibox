"""Fakes for unit tests.

The fake runtime implements the same protocol as :class:`DockerCli` so the
CLI and services can be exercised without a Docker daemon.  The scripted
runner does the same for the Docker CLI adapter itself.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from haibox.errors import ContainerError, RuntimeFailure
from haibox.models import NetworkProfile, Scope
from haibox.runtime.base import ContainerInfo, ExecResult, ImageInfo
from haibox.runtime.process import ProcessResult
from haibox.runtime.spec import ContainerSpec
from haibox.runtime.vpn_spec import VpnGatewaySpec


@dataclass
class FakeRuntime:
    """In-memory ContainerRuntime used by unit and CLI tests."""

    server_version: str = "fake-29.0"
    available: bool = True
    ephemeral_result: ExecResult = field(
        default_factory=lambda: ExecResult(exit_code=0, stdout="", stderr="")
    )
    build_output: str = "fake build output"
    containers: dict[str, ContainerInfo] = field(default_factory=dict)
    networks: dict[str, str] = field(default_factory=dict)
    vpn_networks: dict[str, str] = field(default_factory=dict)
    policies: dict[str, Scope] = field(default_factory=dict)
    missing_images: set[str] = field(default_factory=set)
    calls: list[tuple[str, tuple[Any, ...]]] = field(default_factory=list)
    exec_results: list[ExecResult] = field(default_factory=list)

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, args))

    def called(self, name: str) -> list[tuple[Any, ...]]:
        return [args for call, args in self.calls if call == name]

    # ------------------------------------------------------------------ daemon
    def ensure_available(self) -> str:
        self._record("ensure_available")
        if not self.available:
            raise RuntimeFailure("fake Docker daemon is unavailable")
        return self.server_version

    # ---------------------------------------------------------------- networks
    def network_create(
        self,
        name: str,
        engagement_id: str,
        network_profile: NetworkProfile | None = None,
    ) -> None:
        self._record("network_create", name, engagement_id, network_profile)
        self.networks.setdefault(name, engagement_id)

    def network_exists(self, name: str) -> bool:
        self._record("network_exists", name)
        return name == "none" or name in self.networks or name in self.vpn_networks

    def network_remove(
        self, name: str, network_profile: NetworkProfile | None = None
    ) -> None:
        self._record("network_remove", name, network_profile)
        if name not in self.networks:
            raise ContainerError(f"network not found: {name}")
        del self.networks[name]

    def vpn_network_create(self, name: str, vpn_name: str) -> None:
        self._record("vpn_network_create", name, vpn_name)
        self.vpn_networks.setdefault(name, vpn_name)

    def vpn_network_remove(self, name: str, vpn_name: str) -> None:
        self._record("vpn_network_remove", name, vpn_name)
        if self.vpn_networks.get(name) != vpn_name:
            raise ContainerError(f"VPN network not found or not owned: {name}")
        del self.vpn_networks[name]

    # ------------------------------------------------------------------ policy
    def apply_policy(self, scope: Scope, bridge: str, engagement_id: str) -> None:
        self._record("apply_policy", scope, bridge, engagement_id)
        self.policies[engagement_id] = scope

    def remove_policy(self, engagement_id: str) -> None:
        self._record("remove_policy", engagement_id)
        self.policies.pop(engagement_id, None)

    # -------------------------------------------------------------- containers
    def create_container(self, spec: ContainerSpec) -> str:
        self._record("create_container", spec)
        if spec.name in self.containers:
            raise ContainerError(f"container already exists: {spec.name}")
        container_id = f"fake-{len(self.containers) + 1:04d}"
        self.containers[spec.name] = ContainerInfo(
            id=container_id,
            name=spec.name,
            image=spec.image,
            state="created",
            status="Created",
            labels=dict(spec.labels),
        )
        return container_id

    def create_vpn_gateway(self, spec: VpnGatewaySpec) -> str:
        self._record("create_vpn_gateway", spec)
        if spec.name in self.containers:
            raise ContainerError(f"VPN gateway already exists: {spec.name}")
        self.vpn_network_create(spec.network, spec.profile_name)
        container_id = f"fake-vpn-{len(self.containers) + 1:04d}"
        self.containers[spec.name] = ContainerInfo(
            id=container_id,
            name=spec.name,
            image=spec.image,
            state="created",
            status="Created",
            labels={
                "haibox.managed": "true",
                "haibox.kind": "vpn-gateway",
                "haibox.vpn": spec.profile_name,
                "haibox.image": spec.image,
                "haibox.created-by": "haibox-platform",
            },
        )
        return container_id

    def _container(self, name: str) -> ContainerInfo:
        try:
            return self.containers[name]
        except KeyError as exc:
            raise ContainerError(f"container not found: {name}") from exc

    def start_container(self, name: str) -> None:
        self._record("start_container", name)
        self.containers[name] = dataclasses.replace(
            self._container(name), state="running", status="Up"
        )

    def stop_container(self, name: str, timeout: int = 10) -> None:
        self._record("stop_container", name, timeout)
        self.containers[name] = dataclasses.replace(
            self._container(name), state="exited", status="Exited"
        )

    def restart_container(self, name: str) -> None:
        self._record("restart_container", name)
        self.containers[name] = dataclasses.replace(
            self._container(name), state="running", status="Up"
        )

    def remove_container(self, name: str, force: bool = False) -> None:
        self._record("remove_container", name, force)
        self._container(name)
        del self.containers[name]

    def inspect_container(self, name: str) -> ContainerInfo:
        self._record("inspect_container", name)
        return self._container(name)

    def inspect_container_optional(self, name: str) -> ContainerInfo | None:
        self._record("inspect_container_optional", name)
        return self.containers.get(name)

    def list_containers(self, all: bool = True) -> list[ContainerInfo]:
        self._record("list_containers", all)
        return list(self.containers.values())

    def container_logs(self, name: str, tail: int = 200) -> str:
        self._record("container_logs", name, tail)
        self._container(name)
        return "fake log line\n"

    def exec_interactive(self, name: str, command: list[str]) -> int:
        self._record("exec_interactive", name, tuple(command))
        self._container(name)
        return 0

    def exec_capture(
        self, name: str, command: list[str], timeout: int | None = None
    ) -> ExecResult:
        self._record("exec_capture", name, tuple(command), timeout)
        self._container(name)
        if self.exec_results:
            return self.exec_results.pop(0)
        return ExecResult(exit_code=0, stdout="", stderr="")

    # ----------------------------------------------------------------- images
    def image_exists(self, ref: str) -> bool:
        self._record("image_exists", ref)
        return ref not in self.missing_images

    def image_inspect(self, ref: str) -> ImageInfo:
        self._record("image_inspect", ref)
        return ImageInfo(id="sha256:fake", tags=[ref], labels={})

    def build_image(
        self,
        tag: str,
        dockerfile: str,
        context: str,
        *,
        platform: str | None = None,
        no_cache: bool = False,
        labels: dict[str, str] | None = None,
        build_args: dict[str, str] | None = None,
        timeout: int | None = None,
    ) -> str:
        self._record(
            "build_image",
            tag,
            dockerfile,
            context,
            platform,
            no_cache,
            dict(labels or {}),
            dict(build_args or {}),
            timeout,
        )
        return self.build_output

    def run_ephemeral(
        self,
        image: str,
        command: list[str],
        *,
        timeout: int | None = None,
        network: str = "none",
        user: str = "65534:65534",
        env: dict[str, str] | None = None,
        entrypoint: str | None = None,
    ) -> ExecResult:
        self._record(
            "run_ephemeral",
            image,
            tuple(command),
            timeout,
            network,
            user,
            dict(env or {}),
            entrypoint,
        )
        return self.ephemeral_result


Handler = Callable[[list[str], dict[str, Any]], ProcessResult]


class ScriptedRunner:
    """CommandRunner with a caller-supplied response function."""

    def __init__(
        self,
        handler: Handler | None = None,
        *,
        which: str | None = "docker",
        interactive_code: int = 0,
    ) -> None:
        self.handler = handler or (lambda args, kwargs: ProcessResult(tuple(args), 0, "", ""))
        self.which_result = which
        self.interactive_code = interactive_code
        self.calls: list[list[str]] = []

    def run(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
        capture: bool = True,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        del timeout, capture, input_text, env
        self.calls.append([str(arg) for arg in args])
        return self.handler([str(arg) for arg in args], {})

    def interactive(self, args: list[str], *, env: dict[str, str] | None = None) -> int:
        del env
        self.calls.append([str(arg) for arg in args])
        return self.interactive_code

    def which(self, program: str) -> str | None:
        del program
        return self.which_result


def process_ok(stdout: str = "") -> ProcessResult:
    return ProcessResult(args=(), returncode=0, stdout=stdout, stderr="")


def process_fail(stderr: str = "failed", returncode: int = 1) -> ProcessResult:
    return ProcessResult(args=(), returncode=returncode, stdout="", stderr=stderr)
