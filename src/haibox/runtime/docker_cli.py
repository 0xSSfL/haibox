"""Docker CLI adapter.

The adapter never invokes a shell.  It passes an explicit Docker context or
host, checks managed labels before destructive operations, and verifies the
security shape of a container immediately after creation.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from typing import Any

from haibox.errors import ContainerError, RuntimeFailure
from haibox.models import DockerSettings, NetworkProfile, Scope
from haibox.policy.nftables import NftablesPolicy
from haibox.runtime.base import (
    ContainerInfo,
    ExecResult,
    ExecStream,
    ImageInfo,
    NetworkInfo,
    parse_labels,
)
from haibox.runtime.process import CommandRunner, ProcessResult, SubprocessRunner
from haibox.runtime.spec import ContainerSpec
from haibox.runtime.vpn_spec import VpnGatewaySpec
from haibox.scope import load_scope
from haibox.utils.redact import redact_args, redact_text

_NAME_RE = re.compile(r"^haibox-[a-z0-9][a-z0-9-]{0,61}$")
_NETWORK_RE = re.compile(r"^haibox-[a-z0-9][a-z0-9-]{0,61}$")


def _optional_text(value: Any) -> str | None:
    if value is None or value == "":
        return None
    return str(value)


def _normalise_capabilities(values: list[Any]) -> list[str]:
    """Docker reports ``CAP_NET_RAW`` even when ``NET_RAW`` was requested."""

    return sorted(
        value if value.startswith("CAP_") else f"CAP_{value}"
        for value in (str(item) for item in values)
    )


class DockerCli:
    def __init__(
        self,
        settings: DockerSettings,
        *,
        network_profile: NetworkProfile = "isolated",
        runner: CommandRunner | None = None,
        on_command: Callable[[list[str]], None] | None = None,
    ) -> None:
        self.settings = settings
        self.network_profile = network_profile
        self.runner = runner or SubprocessRunner()
        self.on_command = on_command

    # --------------------------------------------------------------- plumbing
    @property
    def base_args(self) -> list[str]:
        args = ["docker"]
        if self.settings.host:
            args.extend(["--host", self.settings.host])
        elif self.settings.context:
            args.extend(["--context", self.settings.context])
        return args

    def _run(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
        capture: bool = True,
        input_text: str | None = None,
    ) -> ProcessResult:
        full = [*self.base_args, *args]
        if self.on_command is not None:
            self.on_command(redact_args(full))
        return self.runner.run(
            full,
            timeout=self.settings.timeout_seconds if timeout is None else timeout,
            capture=capture,
            input_text=input_text,
        )

    def _check(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
        input_text: str | None = None,
    ) -> ProcessResult:
        result = self._run(args, timeout=timeout, input_text=input_text)
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeFailure(
                f"docker command failed (exit {result.returncode}): {redact_text(detail)}"
            )
        return result

    def _inspect_raw(self, name: str) -> dict[str, Any]:
        result = self._run(["inspect", name])
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()
            raise ContainerError(f"container not found or not inspectable: {name}: {detail}")
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ContainerError(f"cannot parse docker inspect output for {name}") from exc
        if isinstance(raw, list):
            if not raw:
                raise ContainerError(f"docker inspect returned no data for {name}")
            raw = raw[0]
        if not isinstance(raw, dict):
            raise ContainerError(f"unexpected docker inspect output for {name}")
        return raw

    # ---------------------------------------------------------------- daemon
    def ensure_available(self) -> str:
        if self.runner.which("docker") is None:
            raise RuntimeFailure(
                "docker CLI not found; install Docker on the host and expose a "
                "named 'haibox' context"
            )
        if self.settings.context:
            context = self._run(["context", "inspect", self.settings.context])
            if not context.ok:
                raise RuntimeFailure(
                    f"Docker context {self.settings.context!r} is not available; "
                    "create it for the intended endpoint (see docs/host-docker-review.md)"
                )
        result = self._run(["version", "--format", "{{.Server.Version}}"])
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeFailure(f"Docker daemon is not reachable: {redact_text(detail)}")
        version = result.stdout.strip()
        if not version:
            raise RuntimeFailure("Docker daemon returned an empty version")
        return version

    # --------------------------------------------------------------- networks
    def network_exists(self, name: str) -> bool:
        if name == "none":
            return True
        result = self._run(["network", "inspect", name])
        return result.ok

    def network_inspect(self, name: str) -> NetworkInfo:
        if not _NETWORK_RE.fullmatch(name):
            raise ContainerError(f"invalid network name: {name!r}")
        result = self._run(["network", "inspect", name])
        if not result.ok:
            raise ContainerError(f"network not found: {name}")
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ContainerError(f"cannot parse network inspect output for {name}") from exc
        if isinstance(raw, list):
            if not raw:
                raise ContainerError(f"network inspect returned no data for {name}")
            raw = raw[0]
        if not isinstance(raw, dict):
            raise ContainerError(f"unexpected network inspect output for {name}")
        options = raw.get("Options")
        if not isinstance(options, dict):
            options = {}
        ipam = raw.get("IPAM")
        if not isinstance(ipam, dict):
            ipam = {}
        configs = ipam.get("Config")
        if not isinstance(configs, list):
            configs = []
        first = configs[0] if configs and isinstance(configs[0], dict) else {}
        return NetworkInfo(
            id=str(raw.get("Id", "")),
            name=str(raw.get("Name", name)),
            driver=str(raw.get("Driver", "")),
            internal=bool(raw.get("Internal", False)),
            labels=parse_labels(raw.get("Labels")),
            gateway_mode_ipv4=_optional_text(
                options.get("com.docker.network.bridge.gateway_mode_ipv4")
            ),
            gateway_mode_ipv6=_optional_text(
                options.get("com.docker.network.bridge.gateway_mode_ipv6")
            ),
            subnet=_optional_text(first.get("Subnet")),
            gateway=_optional_text(first.get("Gateway")),
        )

    def network_create(
        self,
        name: str,
        engagement_id: str,
        network_profile: NetworkProfile | None = None,
    ) -> None:
        if not _NETWORK_RE.fullmatch(name):
            raise ContainerError(f"invalid network name: {name!r}")
        profile = network_profile or self.network_profile
        if self.network_exists(name):
            info = self._require_managed_network(
                name, engagement_id, network_profile=profile
            )
            self._require_network_profile(info, profile)
            return
        args = ["network", "create", "--driver", "bridge"]
        if profile == "isolated":
            args.extend(
                [
                    "--internal",
                    "--opt",
                    "com.docker.network.bridge.gateway_mode_ipv4=isolated",
                    "--opt",
                    "com.docker.network.bridge.gateway_mode_ipv6=isolated",
                ]
            )
        args.extend(
            [
                "--label",
                "haibox.managed=true",
                "--label",
                f"haibox.engagement={engagement_id}",
                "--label",
                f"haibox.network-profile={profile}",
                "--label",
                "haibox.created-by=haibox-platform",
                name,
            ]
        )
        self._check(args)
        self._require_network_profile(self.network_inspect(name), profile)

    def ensure_network(
        self,
        name: str,
        engagement_id: str,
        network_profile: NetworkProfile | None = None,
    ) -> None:
        if name == "none":
            return
        self.network_create(name, engagement_id, network_profile)

    def vpn_network_create(self, name: str, vpn_name: str) -> None:
        """Create a labelled bridge with egress for the trusted VPN gateway.

        This network is intentionally not ``--internal`` because the gateway
        must reach the VPN endpoint. Engagement runners never attach to it.
        """

        if not _NETWORK_RE.fullmatch(name):
            raise ContainerError(f"invalid VPN network name: {name!r}")
        if self.network_exists(name):
            self._require_vpn_network(name, vpn_name)
            return
        self._check(
            [
                "network",
                "create",
                "--driver",
                "bridge",
                "--label",
                "haibox.managed=true",
                "--label",
                "haibox.kind=vpn-network",
                "--label",
                f"haibox.vpn={vpn_name}",
                "--label",
                "haibox.created-by=haibox-platform",
                name,
            ]
        )

    def _require_vpn_network(self, name: str, vpn_name: str) -> NetworkInfo:
        info = self.network_inspect(name)
        if not info.managed:
            raise ContainerError(
                f"refusing to use network {name!r}: missing haibox.managed=true label"
            )
        if info.labels.get("haibox.kind") != "vpn-network":
            raise ContainerError(f"refusing network {name!r}: it is not a VPN network")
        if info.labels.get("haibox.vpn") != vpn_name:
            raise ContainerError(
                f"refusing network {name!r}: it belongs to another VPN profile"
            )
        if info.internal:
            raise ContainerError(
                f"refusing network {name!r}: a VPN gateway network must have egress"
            )
        return info

    def vpn_network_remove(self, name: str, vpn_name: str) -> None:
        if not _NETWORK_RE.fullmatch(name):
            raise ContainerError(f"invalid VPN network name: {name!r}")
        self._require_vpn_network(name, vpn_name)
        self._check(["network", "rm", name])

    def _require_managed_network(
        self,
        name: str,
        engagement_id: str | None = None,
        network_profile: NetworkProfile | None = None,
    ) -> NetworkInfo:
        info = self.network_inspect(name)
        if not info.managed:
            raise ContainerError(
                f"refusing to use network {name!r}: missing haibox.managed=true label"
            )
        if engagement_id and info.labels.get("haibox.engagement") != engagement_id:
            raise ContainerError(
                f"refusing to use network {name!r}: it belongs to another engagement"
            )
        profile = network_profile or self.network_profile
        if profile == "isolated" and not info.internal:
            raise ContainerError(f"refusing network {name!r}: it is not internal")
        return info

    def _require_network_profile(
        self, info: NetworkInfo, network_profile: NetworkProfile | None = None
    ) -> None:
        profile = network_profile or self.network_profile
        if profile == "isolated":
            if (
                info.gateway_mode_ipv4 != "isolated"
                or info.gateway_mode_ipv6 != "isolated"
            ):
                raise ContainerError(
                    f"refusing network {info.name!r}: it does not use Docker's "
                    "isolated gateway profile; remove and recreate it. The legacy "
                    "'internal' profile has been removed because it exposed the "
                    "host gateway to runners"
                )
            if info.gateway:
                raise ContainerError(
                    f"refusing network {info.name!r}: it still has a host gateway "
                    f"address ({info.gateway})"
                )
        elif profile == "scoped":
            if info.labels.get("haibox.network-profile") != "scoped":
                raise ContainerError(
                    f"refusing network {info.name!r}: missing haibox.network-profile=scoped label"
                )

    def network_remove(
        self, name: str, network_profile: NetworkProfile | None = None
    ) -> None:
        if not _NETWORK_RE.fullmatch(name):
            raise ContainerError(f"invalid network name: {name!r}")
        info = self.network_inspect(name)
        # The network label records the profile used at creation, so cleanup
        # does not depend on the current global configuration.
        label_profile = info.labels.get("haibox.network-profile")
        profile: NetworkProfile
        if network_profile is not None:
            profile = network_profile
        elif label_profile == "scoped":
            profile = "scoped"
        elif label_profile == "isolated":
            profile = "isolated"
        else:
            profile = self.network_profile
        self._require_managed_network(name, network_profile=profile)
        engagement_id = info.labels.get("haibox.engagement")
        # Remove the policy before the network: if nftables cleanup fails, the
        # network is left in place so the operator can retry instead of
        # silently losing the error.
        if engagement_id and profile == "scoped":
            self.remove_policy(engagement_id)
        self._check(["network", "rm", name])

    # ------------------------------------------------------------------ policy
    def apply_policy(self, scope: Scope, bridge: str, engagement_id: str) -> None:
        policy = NftablesPolicy(scope=scope, bridge=bridge, engagement_id=engagement_id)
        policy.apply(self.runner)

    def remove_policy(self, engagement_id: str) -> None:
        policy = NftablesPolicy(scope=Scope(), bridge="br-stub", engagement_id=engagement_id)
        policy.remove(self.runner)

    # -------------------------------------------------------------- containers
    def _require_managed_container(
        self, name: str, engagement_id: str | None = None
    ) -> ContainerInfo:
        info = self.inspect_container(name)
        if not info.managed:
            raise ContainerError(
                f"refusing to operate on container {name!r}: missing haibox.managed=true label"
            )
        if engagement_id and info.engagement != engagement_id:
            raise ContainerError(
                f"refusing to operate on container {name!r}: it belongs to another engagement"
            )
        return info

    def create_container(self, spec: ContainerSpec) -> str:
        if self.inspect_container_optional(spec.name) is not None:
            raise ContainerError(f"container already exists: {spec.name}")
        engagement_id = spec.labels["haibox.engagement"]
        # The engagement snapshot is authoritative: never widen an existing
        # engagement just because the global config now says ``scoped`` (or
        # vice versa).  A ``none`` network never reaches the bridge path, so
        # the profile only needs to distinguish isolated from scoped here.
        network_profile: NetworkProfile = (
            "isolated" if spec.network_profile == "none" else spec.network_profile
        )
        self.ensure_network(spec.network, engagement_id, network_profile)
        if network_profile == "scoped" and spec.network != "none":
            net_info = self.network_inspect(spec.network)
            bridge = net_info.bridge_interface
            if bridge is None:
                # Fail closed: without a resolvable bridge there is no policy
                # enforcement point, so the runner must not be created.
                raise ContainerError(
                    f"refusing to create a scoped runner: network {spec.network!r} "
                    "does not expose a bridge interface, so the nftables policy "
                    "cannot be applied"
                )
            scope = load_scope(spec.scope_file)
            self.apply_policy(scope, bridge, engagement_id)
        result = self._check(spec.to_create_args(), timeout=max(self.settings.timeout_seconds, 120))
        container_id = result.stdout.strip()
        try:
            self._verify_created_container(spec)
        except Exception:
            # Never leave a container whose shape we could not verify. Remove
            # anonymous volumes too: an image-declared VOLUME can create one
            # before verification runs.
            self._run(["rm", "--force", "--volumes", spec.name])
            raise
        return container_id

    def create_vpn_gateway(self, spec: VpnGatewaySpec) -> str:
        if self.inspect_container_optional(spec.name) is not None:
            raise ContainerError(f"VPN gateway already exists: {spec.name}")
        self.vpn_network_create(spec.network, spec.profile_name)
        result = self._check(spec.to_create_args(), timeout=max(self.settings.timeout_seconds, 120))
        try:
            self._verify_created_vpn_gateway(spec)
        except Exception:
            self._run(["rm", "--force", "--volumes", spec.name])
            raise
        return result.stdout.strip()

    def inspect_container_optional(self, name: str) -> ContainerInfo | None:
        result = self._run(["inspect", name])
        if not result.ok:
            return None
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise ContainerError(f"cannot parse docker inspect output for {name}") from exc
        if isinstance(raw, list):
            if not raw:
                return None
            raw = raw[0]
        if not isinstance(raw, dict):
            raise ContainerError(f"unexpected docker inspect output for {name}")
        return self._parse_container(raw)

    def inspect_container(self, name: str) -> ContainerInfo:
        return self._parse_container(self._inspect_raw(name))

    def _parse_container(self, raw: dict[str, Any]) -> ContainerInfo:
        state_raw = raw.get("State")
        state: dict[str, Any] = state_raw if isinstance(state_raw, dict) else {}
        config_raw = raw.get("Config")
        config: dict[str, Any] = config_raw if isinstance(config_raw, dict) else {}
        host_raw = raw.get("HostConfig")
        host: dict[str, Any] = host_raw if isinstance(host_raw, dict) else {}
        network_raw = raw.get("NetworkSettings")
        network: dict[str, Any] = network_raw if isinstance(network_raw, dict) else {}
        networks_raw = network.get("Networks")
        networks = (
            tuple(sorted(str(name) for name in networks_raw))
            if isinstance(networks_raw, dict)
            else ()
        )
        return ContainerInfo(
            id=str(raw.get("Id", "")),
            name=str(raw.get("Name", "")).lstrip("/"),
            image=str(config.get("Image", "")),
            state=str(state.get("Status", "")),
            status=str(state.get("Status", "")),
            labels=parse_labels(config.get("Labels")),
            created=str(raw.get("Created", "")),
            network_mode=str(host.get("NetworkMode", "")),
            networks=networks,
        )

    def _verify_created_container(self, spec: ContainerSpec) -> None:
        raw = self._inspect_raw(spec.name)
        host_raw = raw.get("HostConfig")
        host: dict[str, Any] = host_raw if isinstance(host_raw, dict) else {}
        config_raw = raw.get("Config")
        config: dict[str, Any] = config_raw if isinstance(config_raw, dict) else {}
        mounts_raw = raw.get("Mounts")
        mounts: list[Any] = mounts_raw if isinstance(mounts_raw, list) else []
        container_id = str(raw.get("Id", ""))
        problems: list[str] = []

        # Docker itself bind-mounts these files from the container state
        # directory.  They are expected and are not user-controlled mounts.
        docker_managed_binds = {"/etc/resolv.conf", "/etc/hostname", "/etc/hosts"}
        docker_managed_tmpfs = {"/dev/shm", "/dev/mqueue"}

        def expect(condition: bool, message: str) -> None:
            if not condition:
                problems.append(message)

        expect(host.get("Privileged") is False, "container is privileged")
        expect(host.get("ReadonlyRootfs") is True, "root filesystem is not read-only")
        expect(host.get("NetworkMode") == spec.network, "network mode was changed")
        expect(host.get("PidMode") in ("", "private"), "host PID namespace is enabled")
        expect(host.get("IpcMode") in ("", "private"), "host IPC namespace is enabled")
        expect(not host.get("Devices"), "devices were passed through")
        expect(not host.get("Binds"), "legacy bind mounts were used")
        expect(not host.get("PortBindings"), "ports were published")
        expect(
            str(host.get("RestartPolicy", {}).get("Name", "no")) == "no",
            "restart policy is not 'no'",
        )
        expect(host.get("AutoRemove") is False, "auto-remove is enabled")
        expect(host.get("CapDrop") == ["ALL"], "capabilities were not dropped")
        expect(
            _normalise_capabilities(host.get("CapAdd") or [])
            == _normalise_capabilities(spec.capabilities),
            "capability allowlist does not match the specification",
        )
        security_opt = host.get("SecurityOpt") or []
        expect(
            any(str(item).startswith("no-new-privileges") for item in security_opt),
            "no-new-privileges is missing",
        )
        expect(config.get("User") == f"{spec.uid}:{spec.gid}", "container user was changed")
        expect(str(raw.get("Name", "")).lstrip("/") == spec.name, "container name was changed")
        expect(config.get("Image") == spec.image, "container image was changed")
        tmpfs_raw = host.get("Tmpfs")
        tmpfs: dict[str, Any] = tmpfs_raw if isinstance(tmpfs_raw, dict) else {}
        expect("/tmp" in tmpfs and "/run" in tmpfs, "expected tmpfs mounts are missing")

        destinations: set[str] = set()
        for mount in mounts:
            if not isinstance(mount, dict):
                continue
            destination = str(mount.get("Destination", ""))
            destinations.add(destination)
            if destination == "/workspace":
                expect(
                    str(mount.get("Source", "")) == str(spec.workspace),
                    "workspace source changed",
                )
                expect(bool(mount.get("RW")) is True, "workspace is not writable")
            elif destination == "/etc/haibox/scope.json":
                expect(
                    str(mount.get("Source", "")) == str(spec.scope_file),
                    "scope file source changed",
                )
                expect(bool(mount.get("RW")) is False, "scope file is not read-only")
            elif destination in ("/tmp", "/run"):
                expect(str(mount.get("Type", "")) == "tmpfs", f"{destination} is not tmpfs")
            elif destination in docker_managed_binds:
                expect(
                    str(mount.get("Type", "")) == "bind",
                    f"{destination} is not a Docker-managed bind mount",
                )
                source = str(mount.get("Source", ""))
                expect(
                    bool(container_id) and f"/containers/{container_id}" in source,
                    f"{destination} does not come from this container's state directory",
                )
            elif destination in docker_managed_tmpfs:
                expect(
                    str(mount.get("Type", "")) == "tmpfs",
                    f"{destination} is not a tmpfs mount",
                )
            elif str(mount.get("Type", "")) == "volume":
                problems.append(
                    f"image declares a writable volume at {destination}; "
                    "use an image without VOLUME or add an explicit reviewed policy"
                )
            else:
                problems.append(f"unexpected mount destination: {destination}")
        expect("/workspace" in destinations, "workspace mount is missing")
        expect("/etc/haibox/scope.json" in destinations, "scope mount is missing")

        if problems:
            raise ContainerError(
                "created container failed the security verification: " + "; ".join(problems)
            )

    def _verify_created_vpn_gateway(self, spec: VpnGatewaySpec) -> None:
        raw = self._inspect_raw(spec.name)
        host_raw = raw.get("HostConfig")
        host: dict[str, Any] = host_raw if isinstance(host_raw, dict) else {}
        config_raw = raw.get("Config")
        config: dict[str, Any] = config_raw if isinstance(config_raw, dict) else {}
        mounts_raw = raw.get("Mounts")
        mounts: list[Any] = mounts_raw if isinstance(mounts_raw, list) else []
        container_id = str(raw.get("Id", ""))
        problems: list[str] = []

        def expect(condition: bool, message: str) -> None:
            if not condition:
                problems.append(message)

        expect(host.get("Privileged") is False, "gateway is privileged")
        expect(host.get("ReadonlyRootfs") is True, "gateway root filesystem is not read-only")
        expect(host.get("NetworkMode") == spec.network, "gateway network mode was changed")
        expect(host.get("PidMode") in ("", "private"), "gateway uses the host PID namespace")
        expect(host.get("IpcMode") in ("", "private"), "gateway uses the host IPC namespace")
        expect(not host.get("Binds"), "gateway uses legacy bind mounts")
        expect(not host.get("PortBindings"), "gateway publishes ports")
        expect(
            str(host.get("RestartPolicy", {}).get("Name", "no")) == "no",
            "gateway restart policy is not 'no'",
        )
        expect(host.get("AutoRemove") is False, "gateway auto-remove is enabled")
        expect(host.get("CapDrop") == ["ALL"], "gateway did not drop capabilities")
        expect(
            _normalise_capabilities(host.get("CapAdd") or []) == ["CAP_NET_ADMIN"],
            "gateway capability allowlist is not exactly NET_ADMIN",
        )
        security_opt = host.get("SecurityOpt") or []
        expect(
            any(str(item).startswith("no-new-privileges") for item in security_opt),
            "gateway no-new-privileges is missing",
        )
        expect(config.get("User") == "0:0", "gateway user was changed")
        expect(str(raw.get("Name", "")).lstrip("/") == spec.name, "gateway name was changed")
        expect(config.get("Image") == spec.image, "gateway image was changed")
        devices_raw = host.get("Devices")
        devices: list[Any] = devices_raw if isinstance(devices_raw, list) else []
        expect(
            len(devices) == 1
            and isinstance(devices[0], dict)
            and devices[0].get("PathOnHost") == "/dev/net/tun"
            and devices[0].get("PathInContainer") == "/dev/net/tun",
            "gateway must receive exactly /dev/net/tun",
        )
        tmpfs_raw = host.get("Tmpfs")
        tmpfs: dict[str, Any] = tmpfs_raw if isinstance(tmpfs_raw, dict) else {}
        expect("/tmp" in tmpfs and "/run" in tmpfs, "gateway tmpfs mounts are missing")

        destinations: set[str] = set()
        for mount in mounts:
            if not isinstance(mount, dict):
                continue
            destination = str(mount.get("Destination", ""))
            destinations.add(destination)
            if destination == "/config/vpn.conf":
                expect(str(mount.get("Type", "")) == "bind", "VPN config is not a bind mount")
                expect(
                    str(mount.get("Source", "")) == str(spec.config_file),
                    "VPN config source changed",
                )
                expect(bool(mount.get("RW")) is False, "VPN config is not read-only")
            elif destination in ("/tmp", "/run"):
                expect(str(mount.get("Type", "")) == "tmpfs", f"{destination} is not tmpfs")
            elif destination in {"/etc/resolv.conf", "/etc/hostname", "/etc/hosts"}:
                source = str(mount.get("Source", ""))
                expect(
                    bool(container_id) and f"/containers/{container_id}" in source,
                    f"{destination} does not come from this container's state directory",
                )
            elif destination in {"/dev/shm", "/dev/mqueue"}:
                expect(
                    str(mount.get("Type", "")) == "tmpfs",
                    f"{destination} is not a tmpfs mount",
                )
            elif str(mount.get("Type", "")) == "volume":
                problems.append(
                    f"gateway image declares a writable volume at {destination}; "
                    "use an image without VOLUME"
                )
            else:
                problems.append(f"unexpected gateway mount destination: {destination}")
        expect("/config/vpn.conf" in destinations, "VPN config mount is missing")

        if problems:
            raise ContainerError(
                "created VPN gateway failed the security verification: "
                + "; ".join(problems)
            )

    def start_container(self, name: str) -> None:
        self._require_managed_container(name)
        self._check(["start", name])

    def stop_container(self, name: str, timeout: int = 10) -> None:
        self._require_managed_container(name)
        self._check(["stop", "--time", str(timeout), name], timeout=timeout + 30)

    def restart_container(self, name: str) -> None:
        self._require_managed_container(name)
        self._check(["restart", name])

    def remove_container(self, name: str, force: bool = False) -> None:
        self._require_managed_container(name)
        args = ["rm"]
        if force:
            args.append("--force")
        # We never create named volumes. Removing anonymous volumes prevents
        # image-declared VOLUME metadata from leaking storage on every run.
        args.append("--volumes")
        args.append(name)
        self._check(args, timeout=max(self.settings.timeout_seconds, 120))

    def list_containers(self, all: bool = True) -> list[ContainerInfo]:
        args = ["ps", "--filter", "label=haibox.managed=true", "--format", "{{json .}}"]
        if all:
            args.insert(1, "--all")
        result = self._check(args)
        containers: list[ContainerInfo] = []
        for line in result.stdout.splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            containers.append(
                ContainerInfo(
                    id=str(raw.get("ID", "")),
                    name=str(raw.get("Names", "")),
                    image=str(raw.get("Image", "")),
                    state=str(raw.get("State", "")),
                    status=str(raw.get("Status", "")),
                    labels=parse_labels(raw.get("Labels")),
                    created=str(raw.get("CreatedAt", "")),
                )
            )
        return containers

    def container_logs(self, name: str, tail: int = 200) -> str:
        if tail <= 0:
            raise ContainerError("tail must be positive")
        self._require_managed_container(name)
        result = self._run(["logs", "--tail", str(tail), name])
        if not result.ok:
            detail = redact_text((result.stderr or result.stdout).strip())
            raise ContainerError(f"cannot read logs for {name}: {detail}")
        return result.stdout + result.stderr

    def exec_interactive(self, name: str, command: list[str]) -> int:
        info = self._require_managed_container(name)
        if not info.running:
            raise ContainerError(f"container is not running: {name}")
        if not command:
            raise ContainerError("exec command must not be empty")
        full = [*self.base_args, "exec", "--interactive", "--tty", name, *command]
        if self.on_command is not None:
            self.on_command(redact_args(full))
        return self.runner.interactive(full)

    def exec_capture(
        self, name: str, command: list[str], timeout: int | None = None
    ) -> ExecResult:
        info = self._require_managed_container(name)
        if not info.running:
            raise ContainerError(f"container is not running: {name}")
        if not command:
            raise ContainerError("exec command must not be empty")
        result = self._run(["exec", name, *command], timeout=timeout)
        return ExecResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def exec_detached(
        self, name: str, command: list[str], timeout: int | None = None
    ) -> None:
        """Start a command in the background inside the container."""

        info = self._require_managed_container(name)
        if not info.running:
            raise ContainerError(f"container is not running: {name}")
        if not command:
            raise ContainerError("exec command must not be empty")
        result = self._run(["exec", "--detach", name, *command], timeout=timeout)
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()[:400]
            raise ContainerError(f"cannot start a detached command in {name}: {detail}")

    def exec_with_input(
        self,
        name: str,
        command: list[str],
        input_bytes: bytes,
        timeout: int | None = None,
    ) -> ExecResult:
        """Run a command in the container and write bytes to its standard input."""

        info = self._require_managed_container(name)
        if not info.running:
            raise ContainerError(f"container is not running: {name}")
        if not command:
            raise ContainerError("exec command must not be empty")
        full = [*self.base_args, "exec", "--interactive", name, *command]
        if self.on_command is not None:
            self.on_command(redact_args(full))
        limit = self.settings.timeout_seconds if timeout is None else timeout
        try:
            completed = subprocess.run(  # noqa: S603 - explicit argv, no shell
                full,
                input=input_bytes,
                capture_output=True,
                timeout=limit,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ContainerError(
                f"docker exec in {name} timed out after {limit}s"
            ) from exc
        except OSError as exc:
            raise ContainerError(f"cannot run docker: {exc}") from exc
        return ExecResult(
            exit_code=completed.returncode,
            stdout=(completed.stdout or b"").decode("utf-8", "replace"),
            stderr=(completed.stderr or b"").decode("utf-8", "replace"),
        )

    def exec_stream(self, name: str, command: list[str]) -> ExecStream:
        """Open a bidirectional byte stream to a command in the container."""

        info = self._require_managed_container(name)
        if not info.running:
            raise ContainerError(f"container is not running: {name}")
        if not command:
            raise ContainerError("exec command must not be empty")
        full = [*self.base_args, "exec", "--interactive", name, *command]
        if self.on_command is not None:
            self.on_command(redact_args(full))
        stream = self.runner.stream(full)
        return ExecStream(stdin=stream.stdin, stdout=stream.stdout, close=stream.close)

    # ----------------------------------------------------------------- images
    def image_exists(self, ref: str) -> bool:
        return self._run(["image", "inspect", ref]).ok

    def image_inspect(self, ref: str) -> ImageInfo:
        result = self._run(["image", "inspect", ref])
        if not result.ok:
            raise RuntimeFailure(f"image not found: {ref}")
        try:
            raw = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeFailure(f"cannot parse image inspect output for {ref}") from exc
        if isinstance(raw, list):
            if not raw:
                raise RuntimeFailure(f"image inspect returned no data for {ref}")
            raw = raw[0]
        if not isinstance(raw, dict):
            raise RuntimeFailure(f"unexpected image inspect output for {ref}")
        config_raw = raw.get("Config")
        config: dict[str, Any] = config_raw if isinstance(config_raw, dict) else {}
        return ImageInfo(
            id=str(raw.get("Id", "")),
            tags=[str(tag) for tag in raw.get("RepoTags", []) or []],
            created=str(raw.get("Created", "")),
            labels=parse_labels(config.get("Labels")),
        )

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
        args = [
            "build",
            "--file",
            dockerfile,
            "--tag",
            tag,
            "--progress",
            "plain",
            "--pull=false",
        ]
        if platform:
            args.extend(["--platform", platform])
        if no_cache:
            args.append("--no-cache")
        for key, value in sorted((labels or {}).items()):
            args.extend(["--label", f"{key}={value}"])
        for key, value in sorted((build_args or {}).items()):
            args.extend(["--build-arg", f"{key}={value}"])
        args.append(context)
        result = self._run(args, timeout=timeout or max(self.settings.timeout_seconds, 3600))
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()
            raise RuntimeFailure(
                f"image build failed for {tag} (exit {result.returncode}): "
                f"{redact_text(detail[-4000:])}"
            )
        return result.stdout + result.stderr

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
        if not command:
            raise ContainerError("ephemeral command must not be empty")
        if network != "none" and not _NETWORK_RE.fullmatch(network):
            raise ContainerError(f"invalid ephemeral network: {network!r}")
        user_match = re.fullmatch(r"(\d+):(\d+)", user)
        if user_match is None or int(user_match.group(1)) == 0:
            raise ContainerError(
                "ephemeral containers must run as a numeric non-root uid:gid"
            )
        args = [
            "run",
            "--rm",
            "--network",
            network,
            "--read-only",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges:true",
            "--user",
            user,
            "--workdir",
            "/tmp",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",
            "--pids-limit",
            "128",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--log-driver",
            "none",
            "--env",
            "HOME=/tmp",
            "--env",
            "TMPDIR=/tmp",
        ]
        for key, value in sorted((env or {}).items()):
            args.extend(["--env", f"{key}={value}"])
        if entrypoint:
            args.extend(["--entrypoint", entrypoint])
        args.append(image)
        args.extend(command)
        result = self._run(args, timeout=timeout)
        return ExecResult(
            exit_code=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )
