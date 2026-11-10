"""Runtime-neutral container interfaces.

The manual CLI uses :class:`DockerCli`.  A future restricted broker will expose
the same protocol to the AI lane, so callers never depend on the Docker CLI
shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from haibox.models import NetworkProfile, Scope
    from haibox.runtime.spec import ContainerSpec
    from haibox.runtime.vpn_spec import VpnGatewaySpec


@dataclass(frozen=True)
class ContainerInfo:
    id: str
    name: str
    image: str
    state: str
    status: str
    labels: dict[str, str] = field(default_factory=dict)
    created: str = ""

    @property
    def running(self) -> bool:
        return self.state.lower() == "running"

    @property
    def managed(self) -> bool:
        return self.labels.get("haibox.managed") == "true"

    @property
    def engagement(self) -> str | None:
        return self.labels.get("haibox.engagement")


@dataclass(frozen=True)
class NetworkInfo:
    id: str
    name: str
    driver: str
    internal: bool
    labels: dict[str, str] = field(default_factory=dict)
    gateway_mode_ipv4: str | None = None
    gateway_mode_ipv6: str | None = None
    subnet: str | None = None
    gateway: str | None = None

    @property
    def bridge_interface(self) -> str | None:
        if self.driver == "bridge" and self.id:
            return f"br-{self.id[:12]}"
        return None

    @property
    def managed(self) -> bool:
        return self.labels.get("haibox.managed") == "true"


@dataclass(frozen=True)
class ImageInfo:
    id: str
    tags: list[str]
    created: str = ""
    labels: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ExecResult:
    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class ContainerRuntime(Protocol):
    def ensure_available(self) -> str:
        """Return the server version or raise RuntimeFailure."""

    def network_create(
        self,
        name: str,
        engagement_id: str,
        network_profile: NetworkProfile | None = None,
    ) -> None: ...

    def vpn_network_create(self, name: str, vpn_name: str) -> None: ...

    def vpn_network_remove(self, name: str, vpn_name: str) -> None: ...

    def network_exists(self, name: str) -> bool: ...

    def network_remove(
        self, name: str, network_profile: NetworkProfile | None = None
    ) -> None: ...

    def apply_policy(self, scope: Scope, bridge: str, engagement_id: str) -> None: ...

    def remove_policy(self, engagement_id: str) -> None: ...

    def create_container(self, spec: ContainerSpec) -> str: ...

    def create_vpn_gateway(self, spec: VpnGatewaySpec) -> str: ...

    def start_container(self, name: str) -> None: ...

    def stop_container(self, name: str, timeout: int = 10) -> None: ...

    def restart_container(self, name: str) -> None: ...

    def remove_container(self, name: str, force: bool = False) -> None: ...

    def inspect_container(self, name: str) -> ContainerInfo: ...

    def inspect_container_optional(self, name: str) -> ContainerInfo | None: ...

    def list_containers(self, all: bool = True) -> list[ContainerInfo]: ...

    def container_logs(self, name: str, tail: int = 200) -> str: ...

    def exec_interactive(self, name: str, command: list[str]) -> int: ...

    def exec_capture(
        self, name: str, command: list[str], timeout: int | None = None
    ) -> ExecResult: ...

    def image_exists(self, ref: str) -> bool: ...

    def image_inspect(self, ref: str) -> ImageInfo: ...

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
    ) -> str: ...

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
    ) -> ExecResult: ...


def labels_for(engagement_id: str, profile: str, image: str) -> dict[str, str]:
    return {
        "haibox.managed": "true",
        "haibox.engagement": engagement_id,
        "haibox.profile": profile,
        "haibox.image": image,
        "haibox.created-by": "haibox-platform",
    }


def parse_labels(value: Any) -> dict[str, str]:
    if isinstance(value, dict):
        return {str(key): str(item) for key, item in value.items()}
    if isinstance(value, str):
        result: dict[str, str] = {}
        for item in value.split(","):
            if "=" in item:
                key, _, val = item.partition("=")
                result[key] = val
        return result
    return {}
