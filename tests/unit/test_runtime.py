"""Docker CLI adapter tests using a scripted command runner."""

from __future__ import annotations

import json
from typing import Any

import pytest
from pydantic import ValidationError

from haibox.errors import ContainerError, RuntimeFailure
from haibox.models import (
    DockerSettings,
    Engagement,
    NetworkProfile,
    NetworkSettings,
)
from haibox.paths import Paths
from haibox.runtime.base import ExecResult
from haibox.runtime.docker_cli import DockerCli
from haibox.runtime.spec import ContainerSpec
from haibox.runtime.vpn_spec import VpnGatewaySpec
from tests.fakes import ScriptedRunner, process_fail, process_ok


@pytest.fixture
def spec(engagement: Engagement, paths: Paths) -> ContainerSpec:
    return ContainerSpec.from_engagement(engagement, paths)


def _cli(
    handler,
    *,
    settings: DockerSettings | None = None,
    network_profile: NetworkProfile = "isolated",
) -> tuple[DockerCli, ScriptedRunner]:
    runner = ScriptedRunner(handler)
    return (
        DockerCli(
            settings or DockerSettings(context="haibox"),
            network_profile=network_profile,
            runner=runner,
        ),
        runner,
    )


def _payload(spec: ContainerSpec, *, container_id: str = "a" * 64) -> dict[str, Any]:
    return {
        "Id": container_id,
        "Name": f"/{spec.name}",
        "Created": "2026-01-01T00:00:00Z",
        "Config": {
            "Image": spec.image,
            "User": f"{spec.uid}:{spec.gid}",
            "Labels": dict(spec.labels),
        },
        "HostConfig": {
            "Privileged": False,
            "ReadonlyRootfs": True,
            "NetworkMode": spec.network,
            "PidMode": "",
            "IpcMode": "private",
            "Devices": [],
            "Binds": None,
            "PortBindings": {},
            "RestartPolicy": {"Name": "no"},
            "AutoRemove": False,
            "CapDrop": ["ALL"],
            "CapAdd": list(spec.capabilities),
            "SecurityOpt": ["no-new-privileges:true"],
            "Tmpfs": {"/tmp": "rw,noexec", "/run": "rw,noexec"},
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(spec.workspace),
                "Destination": "/workspace",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": str(spec.scope_file),
                "Destination": "/etc/haibox/scope.json",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": f"/var/lib/docker/containers/{container_id}/resolv.conf",
                "Destination": "/etc/resolv.conf",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": f"/var/lib/docker/containers/{container_id}/hostname",
                "Destination": "/etc/hostname",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": f"/var/lib/docker/containers/{container_id}/hosts",
                "Destination": "/etc/hosts",
                "RW": True,
            },
            {"Type": "tmpfs", "Source": "", "Destination": "/dev/shm", "RW": True},
        ],
    }


@pytest.fixture
def gateway_spec(tmp_path) -> VpnGatewaySpec:
    config = tmp_path / "vpn.conf"
    config.write_text(
        "[Interface]\nPrivateKey = test\n"
        "[Peer]\nPublicKey = test\nEndpoint = vpn.example.test:51820\n",
        encoding="utf-8",
    )
    return VpnGatewaySpec(
        profile_name="lab",
        vpn_type="wireguard",
        config_file=config,
    )


def _gateway_payload(
    spec: VpnGatewaySpec, *, container_id: str = "b" * 64
) -> dict[str, Any]:
    return {
        "Id": container_id,
        "Name": f"/{spec.name}",
        "Created": "2026-01-01T00:00:00Z",
        "Config": {
            "Image": spec.image,
            "User": "0:0",
            "Labels": {
                "haibox.managed": "true",
                "haibox.kind": "vpn-gateway",
                "haibox.vpn": spec.profile_name,
            },
        },
        "HostConfig": {
            "Privileged": False,
            "ReadonlyRootfs": True,
            "NetworkMode": spec.network,
            "PidMode": "",
            "IpcMode": "private",
            "Binds": None,
            "PortBindings": {},
            "RestartPolicy": {"Name": "no"},
            "AutoRemove": False,
            "CapDrop": ["ALL"],
            "CapAdd": ["CAP_NET_ADMIN"],
            "SecurityOpt": ["no-new-privileges:true"],
            "Devices": [
                {
                    "PathOnHost": "/dev/net/tun",
                    "PathInContainer": "/dev/net/tun",
                    "CgroupPermissions": "rwm",
                }
            ],
            "Tmpfs": {"/tmp": "rw", "/run": "rw"},
        },
        "Mounts": [
            {
                "Type": "bind",
                "Source": str(spec.config_file),
                "Destination": "/config/vpn.conf",
                "RW": False,
            },
            {
                "Type": "bind",
                "Source": f"/var/lib/docker/containers/{container_id}/resolv.conf",
                "Destination": "/etc/resolv.conf",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": f"/var/lib/docker/containers/{container_id}/hostname",
                "Destination": "/etc/hostname",
                "RW": True,
            },
            {
                "Type": "bind",
                "Source": f"/var/lib/docker/containers/{container_id}/hosts",
                "Destination": "/etc/hosts",
                "RW": True,
            },
            {"Type": "tmpfs", "Source": "", "Destination": "/dev/shm", "RW": True},
        ],
    }


def _vpn_network_payload(
    name: str = "haibox-vpn-lab-net",
    *,
    vpn_name: str = "lab",
    internal: bool = False,
    kind: str = "vpn-network",
) -> str:
    return json.dumps(
        {
            "Id": "vpn-network-id",
            "Name": name,
            "Driver": "bridge",
            "Internal": internal,
            "Labels": {
                "haibox.managed": "true",
                "haibox.kind": kind,
                "haibox.vpn": vpn_name,
            },
        }
    )


def _network_payload(
    name: str = "haibox-demo-net",
    *,
    engagement_id: str | None = "demo",
    internal: bool = True,
    managed: bool = True,
    gateway_mode: str | None = "isolated",
    gateway: str | None = None,
) -> str:
    labels: dict[str, str] = {}
    if managed:
        labels["haibox.managed"] = "true"
    if engagement_id:
        labels["haibox.engagement"] = engagement_id
    options: dict[str, str] = {}
    if gateway_mode:
        options["com.docker.network.bridge.gateway_mode_ipv4"] = gateway_mode
        options["com.docker.network.bridge.gateway_mode_ipv6"] = gateway_mode
    ipam: dict[str, Any] = {"Driver": "default", "Options": {}, "Config": []}
    if gateway:
        ipam["Config"] = [{"Subnet": "172.19.0.0/16", "Gateway": gateway}]
    return json.dumps(
        {
            "Id": "network-id",
            "Name": name,
            "Driver": "bridge",
            "Internal": internal,
            "Labels": labels,
            "Options": options,
            "IPAM": ipam,
        }
    )


def test_base_args_use_context_or_host() -> None:
    context_cli = DockerCli(DockerSettings(context="haibox"), runner=ScriptedRunner())
    assert context_cli.base_args == ["docker", "--context", "haibox"]

    host_cli = DockerCli(
        DockerSettings(context=None, host="unix:///var/run/docker.sock"),
        runner=ScriptedRunner(),
    )
    assert host_cli.base_args == ["docker", "--host", "unix:///var/run/docker.sock"]


def test_ensure_available_requires_docker_cli() -> None:
    cli, _ = _cli(lambda args, kwargs: process_ok())
    cli.runner = ScriptedRunner(which=None)
    with pytest.raises(RuntimeFailure):
        cli.ensure_available()


def test_ensure_available_checks_the_context() -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "context" in args:
            return process_fail("context not found")
        return process_ok("29.0")

    cli, _ = _cli(handler)
    with pytest.raises(RuntimeFailure) as excinfo:
        cli.ensure_available()
    assert "not available" in str(excinfo.value)


def test_ensure_available_returns_the_server_version() -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "context" in args:
            return process_ok("{}")
        return process_ok("29.0\n")

    cli, _ = _cli(handler)
    assert cli.ensure_available() == "29.0"


def test_ensure_available_reports_daemon_failure() -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "context" in args:
            return process_ok("{}")
        return process_fail("cannot connect")

    cli, _ = _cli(handler)
    with pytest.raises(RuntimeFailure):
        cli.ensure_available()


def test_network_create_is_internal_and_labeled() -> None:
    created = False

    def handler(args: list[str], kwargs: dict[str, Any]):
        nonlocal created
        del kwargs
        if "network" in args and "inspect" in args:
            return process_ok(_network_payload()) if created else process_fail("not found")
        if "network" in args and "create" in args:
            created = True
            return process_ok()
        return process_fail("unexpected")

    cli, runner = _cli(handler)
    cli.network_create("haibox-demo-net", "demo")
    create = next(call for call in runner.calls if "create" in call)
    assert "--internal" in create
    assert "--label" in create
    assert "haibox.managed=true" in create
    assert "haibox.engagement=demo" in create
    assert "com.docker.network.bridge.gateway_mode_ipv4=isolated" in create
    assert "com.docker.network.bridge.gateway_mode_ipv6=isolated" in create


def test_legacy_internal_profile_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NetworkSettings(profile="internal")


def test_existing_network_without_isolated_profile_is_refused() -> None:
    cli, _ = _cli(
        lambda args, kwargs: process_ok(_network_payload(gateway_mode=None)),
    )
    with pytest.raises(ContainerError, match="isolated gateway profile"):
        cli.network_create("haibox-demo-net", "demo")


def test_isolated_network_with_a_host_gateway_is_refused() -> None:
    cli, _ = _cli(
        lambda args, kwargs: process_ok(_network_payload(gateway="172.19.0.1")),
    )
    with pytest.raises(ContainerError, match="host gateway"):
        cli.network_create("haibox-demo-net", "demo")


def test_network_inspect_reports_gateway_profile() -> None:
    cli, _ = _cli(
        lambda args, kwargs: process_ok(
            _network_payload(gateway="172.19.0.1")
        ),
    )
    info = cli.network_inspect("haibox-demo-net")
    assert info.gateway_mode_ipv4 == "isolated"
    assert info.gateway_mode_ipv6 == "isolated"
    assert info.gateway == "172.19.0.1"


def test_existing_managed_network_is_reused() -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "network" in args and "inspect" in args:
            return process_ok(_network_payload())
        return process_fail("should not create")

    cli, runner = _cli(handler)
    cli.network_create("haibox-demo-net", "demo")
    assert not any("create" in call for call in runner.calls)


def test_unmanaged_network_is_refused() -> None:
    cli, _ = _cli(
        lambda args, kwargs: process_ok(_network_payload(managed=False)),
    )
    with pytest.raises(ContainerError):
        cli.network_create("haibox-demo-net", "demo")


def test_network_owned_by_another_engagement_is_refused() -> None:
    cli, _ = _cli(
        lambda args, kwargs: process_ok(_network_payload(engagement_id="other")),
    )
    with pytest.raises(ContainerError):
        cli.network_create("haibox-demo-net", "demo")


def test_non_internal_network_is_refused() -> None:
    cli, _ = _cli(
        lambda args, kwargs: process_ok(_network_payload(internal=False)),
    )
    with pytest.raises(ContainerError):
        cli.network_create("haibox-demo-net", "demo")


def test_network_exists_handles_none() -> None:
    cli, runner = _cli(lambda args, kwargs: process_fail("unexpected"))
    assert cli.network_exists("none")
    assert runner.calls == []


def test_create_container_verifies_the_security_shape(spec: ContainerSpec) -> None:
    created = False
    network_created = False
    payload = _payload(spec)

    def handler(args: list[str], kwargs: dict[str, Any]):
        nonlocal created, network_created
        del kwargs
        if "network" in args and "inspect" in args:
            return (
                process_ok(_network_payload())
                if network_created
                else process_fail("not found")
            )
        if "network" in args and "create" in args:
            network_created = True
            return process_ok()
        if "inspect" in args:
            if not created:
                return process_fail("not found")
            return process_ok(json.dumps(payload))
        if "create" in args:
            created = True
            return process_ok("container-id\n")
        return process_fail("unexpected")

    cli, runner = _cli(handler)
    assert cli.create_container(spec) == "container-id"
    create = next(
        call for call in runner.calls if "create" in call and "--read-only" in call
    )
    assert "--read-only" in create
    assert "--cap-drop" in create
    assert "--security-opt" in create
    assert "--user" in create


def test_create_container_rejects_an_existing_container(spec: ContainerSpec) -> None:
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(_payload(spec))))
    with pytest.raises(ContainerError) as excinfo:
        cli.create_container(spec)
    assert "already exists" in str(excinfo.value)


def test_failed_verification_removes_the_container(spec: ContainerSpec) -> None:
    created = False
    network_created = False
    payload = _payload(spec)
    payload["HostConfig"]["Privileged"] = True

    def handler(args: list[str], kwargs: dict[str, Any]):
        nonlocal created, network_created
        del kwargs
        if "network" in args and "inspect" in args:
            return (
                process_ok(_network_payload())
                if network_created
                else process_fail("not found")
            )
        if "network" in args and "create" in args:
            network_created = True
            return process_ok()
        if "inspect" in args:
            if not created:
                return process_fail("not found")
            return process_ok(json.dumps(payload))
        if "create" in args:
            created = True
            return process_ok("container-id\n")
        if "rm" in args:
            return process_ok()
        return process_fail("unexpected")

    cli, runner = _cli(handler)
    with pytest.raises(ContainerError) as excinfo:
        cli.create_container(spec)
    assert "privileged" in str(excinfo.value)
    assert any("rm" in call and "--force" in call for call in runner.calls)


def test_verification_accepts_docker_managed_mounts(spec: ContainerSpec) -> None:
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(_payload(spec))))
    cli._verify_created_container(spec)


def test_verification_accepts_docker_normalised_capabilities(
    spec: ContainerSpec,
) -> None:
    payload = _payload(spec)
    payload["HostConfig"]["CapAdd"] = [
        f"CAP_{capability}" for capability in spec.capabilities
    ]
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(payload)))
    cli._verify_created_container(spec)


def test_verification_rejects_unexpected_mounts(spec: ContainerSpec) -> None:
    payload = _payload(spec)
    payload["Mounts"].append(
        {"Type": "bind", "Source": "/", "Destination": "/host", "RW": True}
    )
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(payload)))
    with pytest.raises(ContainerError) as excinfo:
        cli._verify_created_container(spec)
    assert "unexpected mount" in str(excinfo.value)


def test_verification_rejects_image_declared_volumes(spec: ContainerSpec) -> None:
    payload = _payload(spec)
    payload["Mounts"].append(
        {
            "Type": "volume",
            "Name": "anonymous",
            "Source": "/var/lib/docker/volumes/anonymous/_data",
            "Destination": "/var/lib/postgresql/data",
            "RW": True,
        }
    )
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(payload)))
    with pytest.raises(ContainerError) as excinfo:
        cli._verify_created_container(spec)
    assert "VOLUME" in str(excinfo.value)


def test_verification_rejects_a_writable_scope_file(spec: ContainerSpec) -> None:
    payload = _payload(spec)
    payload["Mounts"][1]["RW"] = True
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(payload)))
    with pytest.raises(ContainerError) as excinfo:
        cli._verify_created_container(spec)
    assert "read-only" in str(excinfo.value)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda payload: payload["Config"].__setitem__("User", "0:0"), "user"),
        (
            lambda payload: payload["HostConfig"].__setitem__(
                "PortBindings", {"80/tcp": [{"HostPort": "80"}]}
            ),
            "ports",
        ),
        (
            lambda payload: payload["HostConfig"].__setitem__("Binds", ["/:/host"]),
            "bind mounts",
        ),
        (
            lambda payload: payload["HostConfig"].__setitem__("Devices", [{}]),
            "devices",
        ),
        (
            lambda payload: payload["HostConfig"].__setitem__("PidMode", "host"),
            "PID",
        ),
    ],
)
def test_verification_rejects_weakened_shapes(
    spec: ContainerSpec, mutator, message: str
) -> None:
    payload = _payload(spec)
    mutator(payload)
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(payload)))
    with pytest.raises(ContainerError) as excinfo:
        cli._verify_created_container(spec)
    assert message.lower() in str(excinfo.value).lower()


def test_managed_label_is_required_for_lifecycle_operations(spec: ContainerSpec) -> None:
    payload = _payload(spec)
    payload["Config"]["Labels"] = {}
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(payload)))
    for operation in (
        lambda: cli.start_container(spec.name),
        lambda: cli.stop_container(spec.name),
        lambda: cli.restart_container(spec.name),
        lambda: cli.remove_container(spec.name),
    ):
        with pytest.raises(ContainerError):
            operation()


def test_start_stop_restart_and_remove(spec: ContainerSpec) -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "inspect" in args:
            return process_ok(json.dumps(_payload(spec)))
        return process_ok()

    cli, runner = _cli(handler)
    cli.start_container(spec.name)
    cli.stop_container(spec.name)
    cli.restart_container(spec.name)
    cli.remove_container(spec.name, force=True)
    assert any("start" in call for call in runner.calls)
    assert any("stop" in call for call in runner.calls)
    assert any("restart" in call for call in runner.calls)
    assert any(
        "rm" in call and "--force" in call and "--volumes" in call
        for call in runner.calls
    )


def test_list_containers_parses_json_lines() -> None:
    line = json.dumps(
        {
            "ID": "abc",
            "Names": "haibox-demo",
            "Image": "haibox/web-security:0.1.0",
            "State": "running",
            "Status": "Up",
            "Labels": "haibox.managed=true,haibox.engagement=demo",
            "CreatedAt": "2026-01-01",
        }
    )
    cli, _ = _cli(lambda args, kwargs: process_ok(line + "\n"))
    containers = cli.list_containers()
    assert len(containers) == 1
    assert containers[0].name == "haibox-demo"
    assert containers[0].running
    assert containers[0].engagement == "demo"


def test_container_logs_and_tail_validation(spec: ContainerSpec) -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "inspect" in args:
            return process_ok(json.dumps(_payload(spec)))
        return process_ok("line\n")

    cli, _ = _cli(handler)
    assert cli.container_logs(spec.name, tail=5) == "line\n"
    with pytest.raises(ContainerError):
        cli.container_logs(spec.name, tail=0)


def test_exec_capture_requires_a_running_managed_container(spec: ContainerSpec) -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "inspect" in args:
            payload = _payload(spec)
            payload["State"] = {"Status": "exited"}
            return process_ok(json.dumps(payload))
        return process_ok("output\n")

    cli, _ = _cli(handler)
    with pytest.raises(ContainerError):
        cli.exec_capture(spec.name, ["id"])


def test_exec_capture_returns_output(spec: ContainerSpec) -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "inspect" in args:
            payload = _payload(spec)
            payload["State"] = {"Status": "running"}
            return process_ok(json.dumps(payload))
        return process_ok("output\n")

    cli, _ = _cli(handler)
    result = cli.exec_capture(spec.name, ["id"])
    assert result == ExecResult(exit_code=0, stdout="output\n", stderr="")


def test_exec_interactive_returns_the_exit_code(spec: ContainerSpec) -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "inspect" in args:
            payload = _payload(spec)
            payload["State"] = {"Status": "running"}
            return process_ok(json.dumps(payload))
        return process_ok()

    cli, runner = _cli(handler)
    runner.interactive_code = 7
    assert cli.exec_interactive(spec.name, ["/bin/bash"]) == 7


def test_run_ephemeral_has_a_restricted_shape() -> None:
    cli, runner = _cli(lambda args, kwargs: process_ok("ok\n"))
    result = cli.run_ephemeral(
        "haibox/web-security:0.1.0",
        ["-c", "id"],
        entrypoint="/bin/sh",
        env={"EXTRA": "value"},
    )
    assert result.stdout == "ok\n"
    args = runner.calls[0]
    assert "--rm" in args
    assert "--network" in args
    assert args[args.index("--network") + 1] == "none"
    assert "--read-only" in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--security-opt") + 1] == "no-new-privileges:true"
    assert args[args.index("--user") + 1] == "65534:65534"
    assert args[args.index("--entrypoint") + 1] == "/bin/sh"
    assert "EXTRA=value" in args


def test_run_ephemeral_rejects_a_privileged_network() -> None:
    cli, _ = _cli(lambda args, kwargs: process_ok())
    with pytest.raises(ContainerError):
        cli.run_ephemeral("image", ["id"], network="host")


def test_run_ephemeral_rejects_root_user() -> None:
    cli, _ = _cli(lambda args, kwargs: process_ok())
    with pytest.raises(ContainerError):
        cli.run_ephemeral("image", ["id"], user="0:0")


def test_build_image_passes_pins_and_labels() -> None:
    cli, runner = _cli(lambda args, kwargs: process_ok("built\n"))
    output = cli.build_image(
        "haibox/web-security:0.1.0",
        "/repo/images/web-security/Dockerfile",
        "/repo/images/web-security",
        labels={"haibox.image.name": "web-security"},
        build_args={"DEBIAN_SNAPSHOT": "20251101T000000Z"},
        no_cache=True,
    )
    assert output == "built\n"
    args = runner.calls[0]
    assert "build" in args
    assert args[args.index("--file") + 1].endswith("Dockerfile")
    assert args[args.index("--tag") + 1] == "haibox/web-security:0.1.0"
    assert "--no-cache" in args
    assert "haibox.image.name=web-security" in args
    assert "DEBIAN_SNAPSHOT=20251101T000000Z" in args


def test_build_failure_is_reported() -> None:
    cli, _ = _cli(lambda args, kwargs: process_fail("boom"))
    with pytest.raises(RuntimeFailure):
        cli.build_image("image", "Dockerfile", ".")


def test_on_command_redacts_secret_arguments() -> None:
    commands: list[list[str]] = []
    cli = DockerCli(
        DockerSettings(context="haibox"),
        runner=ScriptedRunner(lambda args, kwargs: process_ok()),
        on_command=commands.append,
    )
    cli.run_ephemeral(
        "image",
        ["tool"],
        env={"API_KEY": "super-secret-value"},
    )
    joined = " ".join(commands[0])
    assert "super-secret-value" not in joined
    assert "***REDACTED***" in joined


def test_inspect_optional_returns_none_for_missing_container() -> None:
    cli, _ = _cli(lambda args, kwargs: process_fail("not found"))
    assert cli.inspect_container_optional("haibox-demo") is None


def test_image_inspect_and_exists() -> None:
    payload = json.dumps(
        {
            "Id": "sha256:abc",
            "RepoTags": ["haibox/web-security:0.1.0"],
            "Created": "2026-01-01",
            "Config": {"Labels": {"haibox.image.name": "web-security"}},
        }
    )

    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "image" in args and "inspect" in args:
            return process_ok(payload)
        return process_fail("unexpected")

    cli, _ = _cli(handler)
    assert cli.image_exists("haibox/web-security:0.1.0")
    info = cli.image_inspect("haibox/web-security:0.1.0")
    assert info.id == "sha256:abc"
    assert info.labels["haibox.image.name"] == "web-security"


def test_network_inspect_rejects_an_invalid_name() -> None:
    cli, _ = _cli(lambda args, kwargs: process_ok("{}"))
    with pytest.raises(ContainerError):
        cli.network_inspect("host")


def test_vpn_network_create_has_egress_and_vpn_labels() -> None:
    def handler(args: list[str], kwargs: dict[str, Any]):
        del kwargs
        if "network" in args and "inspect" in args:
            return process_fail("not found")
        if "network" in args and "create" in args:
            return process_ok()
        return process_fail("unexpected")

    cli, runner = _cli(handler)
    cli.vpn_network_create("haibox-vpn-lab-net", "lab")
    create = next(call for call in runner.calls if "create" in call)
    assert "--internal" not in create
    assert "haibox.kind=vpn-network" in create
    assert "haibox.vpn=lab" in create


def test_vpn_network_remove_requires_vpn_ownership() -> None:
    payload = _vpn_network_payload(vpn_name="other")
    cli, _ = _cli(lambda args, kwargs: process_ok(payload))
    with pytest.raises(ContainerError, match="another VPN profile"):
        cli.vpn_network_remove("haibox-vpn-lab-net", "lab")


def test_vpn_network_remove_refuses_an_internal_network() -> None:
    payload = _vpn_network_payload(internal=True)
    cli, _ = _cli(lambda args, kwargs: process_ok(payload))
    with pytest.raises(ContainerError, match="must have egress"):
        cli.vpn_network_remove("haibox-vpn-lab-net", "lab")


def test_vpn_gateway_verification_accepts_the_expected_shape(
    gateway_spec: VpnGatewaySpec,
) -> None:
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(_gateway_payload(gateway_spec))))
    cli._verify_created_vpn_gateway(gateway_spec)


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (
            lambda payload: payload["HostConfig"].__setitem__("Privileged", True),
            "privileged",
        ),
        (
            lambda payload: payload["HostConfig"].__setitem__(
                "CapAdd", ["CAP_NET_ADMIN", "CAP_SYS_ADMIN"]
            ),
            "NET_ADMIN",
        ),
        (
            lambda payload: payload["HostConfig"].__setitem__(
                "Devices",
                [
                    {"PathOnHost": "/dev/net/tun", "PathInContainer": "/dev/net/tun"},
                    {"PathOnHost": "/dev/kvm", "PathInContainer": "/dev/kvm"},
                ],
            ),
            "dev/net/tun",
        ),
        (
            lambda payload: payload["Mounts"][0].__setitem__("RW", True),
            "read-only",
        ),
        (
            lambda payload: payload["HostConfig"].__setitem__(
                "PortBindings", {"1194/udp": [{"HostPort": "1194"}]}
            ),
            "publishes ports",
        ),
    ],
)
def test_vpn_gateway_verification_rejects_weakened_shapes(
    gateway_spec: VpnGatewaySpec, mutator, message: str
) -> None:
    payload = _gateway_payload(gateway_spec)
    mutator(payload)
    cli, _ = _cli(lambda args, kwargs: process_ok(json.dumps(payload)))
    with pytest.raises(ContainerError) as excinfo:
        cli._verify_created_vpn_gateway(gateway_spec)
    assert message.lower() in str(excinfo.value).lower()


def test_create_vpn_gateway_removes_a_failed_container(
    gateway_spec: VpnGatewaySpec,
) -> None:
    created = False
    payload = _gateway_payload(gateway_spec)
    payload["HostConfig"]["Privileged"] = True

    def handler(args: list[str], kwargs: dict[str, Any]):
        nonlocal created
        del kwargs
        if "network" in args and "inspect" in args:
            return process_fail("not found")
        if "network" in args and "create" in args:
            return process_ok()
        if "inspect" in args:
            if not created:
                return process_fail("not found")
            return process_ok(json.dumps(payload))
        if "create" in args:
            created = True
            return process_ok("gateway-id\n")
        if "rm" in args:
            return process_ok()
        return process_fail("unexpected")

    cli, runner = _cli(handler)
    with pytest.raises(ContainerError, match="privileged"):
        cli.create_vpn_gateway(gateway_spec)
    assert any(
        "rm" in call and "--force" in call and "--volumes" in call
        for call in runner.calls
    )
