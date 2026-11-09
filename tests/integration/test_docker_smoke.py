"""Opt-in Docker integration smoke test.

These tests create a real container and network. They are skipped unless
``HAIBOX_RUN_INTEGRATION=1`` and a dedicated ``haibox`` Docker context is
available. The context may point at the local Fedora socket or a remote
dedicated server. Set ``HAIBOX_TEST_IMAGE`` to test the container shape with
an already-present image before the Web Security image is built.
"""

from __future__ import annotations

import contextlib
import dataclasses
import os
import shutil
import socket
import subprocess
import time
import uuid
from collections.abc import Iterator

import pytest

from haibox.engagement import EngagementManager
from haibox.errors import HAIBOXError
from haibox.models import DockerSettings, Scope
from haibox.paths import Paths
from haibox.runtime.base import ExecResult
from haibox.runtime.docker_cli import DockerCli
from haibox.runtime.spec import ContainerSpec

RUN_INTEGRATION = os.environ.get("HAIBOX_RUN_INTEGRATION") == "1"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not RUN_INTEGRATION,
        reason="set HAIBOX_RUN_INTEGRATION=1 to run against a reviewed Docker endpoint",
    ),
]


@pytest.fixture
def runtime() -> Iterator[DockerCli]:
    context = os.environ.get("HAIBOX_DOCKER_CONTEXT", "haibox")
    cli = DockerCli(DockerSettings(context=context))
    try:
        cli.ensure_available()
    except HAIBOXError as exc:
        pytest.skip(f"dedicated Docker context {context!r} is unavailable: {exc}")
    yield cli


@pytest.fixture
def engagement(tmp_path):
    paths = Paths(data_dir=tmp_path / "data", config_dir=tmp_path / "config")
    manager = EngagementManager(paths)
    engagement_id = f"it-{uuid.uuid4().hex[:8]}"
    created = manager.create(
        engagement_id,
        name="Integration smoke",
        scope=Scope(allowed=["192.0.2.10"], allowed_ports=[443]),
    )
    try:
        yield manager, paths, created
    finally:
        with contextlib.suppress(HAIBOXError):
            manager.destroy(created.id, force=True)


def test_container_isolation_shape(runtime: DockerCli, engagement) -> None:
    manager, paths, created = engagement
    spec = ContainerSpec.from_engagement(created, paths)
    test_image = os.environ.get("HAIBOX_TEST_IMAGE")
    if test_image:
        spec = dataclasses.replace(
            spec,
            image=test_image,
            labels={**spec.labels, "haibox.image": test_image},
        )

    if not runtime.image_exists(spec.image):
        pytest.skip(
            f"image {spec.image} is not present; build it or set HAIBOX_TEST_IMAGE "
            "to an already-present image"
        )

    try:
        runtime.create_container(spec)
        runtime.start_container(spec.name)

        uid = runtime.exec_capture(spec.name, ["id", "-u"])
        assert uid.ok
        assert int(uid.stdout.strip()) == spec.uid
        assert spec.uid != 0

        network = runtime.network_inspect(spec.network)
        assert network.internal
        assert network.labels["haibox.engagement"] == created.id

        writable = runtime.exec_capture(
            spec.name, ["/bin/sh", "-c", "touch /workspace/.integration-check"]
        )
        assert writable.ok, writable.stderr

        scope_read_only = runtime.exec_capture(
            spec.name, ["/bin/sh", "-c", "test ! -w /etc/haibox/scope.json"]
        )
        assert scope_read_only.ok, "the mounted scope file is writable"

        host_only_script = (
            "test ! -e /evidence && test ! -e /reports && test ! -e /secrets.json"
        )
        host_only = runtime.exec_capture(
            spec.name,
            ["/bin/sh", "-c", host_only_script],
        )
        assert host_only.ok, "a host-only directory leaked into the container"
    finally:
        if runtime.inspect_container_optional(spec.name) is not None:
            runtime.remove_container(spec.name, force=True)
        if spec.network != "none" and runtime.network_exists(spec.network):
            runtime.network_remove(spec.network)


def _host_lan_ip() -> str:
    """Return the host's primary non-loopback IPv4 address."""

    configured = os.environ.get("HAIBOX_TEST_HOST_LAN_IP")
    if configured:
        return configured
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        # TEST-NET-1; no packet is sent for a UDP connect.
        sock.connect(("192.0.2.1", 9))
        return str(sock.getsockname()[0])


def _host_ipv4_addresses() -> list[str]:
    """Return global IPv4 addresses configured on the Docker host."""

    if shutil.which("ip") is None:
        return []
    result = subprocess.run(
        ["ip", "-4", "-o", "addr", "show", "scope", "global"],
        capture_output=True,
        text=True,
        check=False,
    )
    addresses: list[str] = []
    for line in result.stdout.splitlines():
        parts = line.split()
        if "inet" not in parts:
            continue
        addresses.append(parts[parts.index("inet") + 1].split("/")[0])
    return addresses


def test_container_network_isolation(runtime: DockerCli, engagement) -> None:
    """Probe the default isolated runner network with real connection attempts.

    The test covers the host SSH/PostgreSQL ports, other host listeners, the
    host LAN address, the host's Docker bridges, public IPv4 and IPv6, DNS,
    HTTP redirects, the link-local metadata address, and container-to-container
    traffic on the same engagement network.

    The host-side address and bridge checks assume the Docker context points at
    the local host, which is the reviewed development endpoint. Against a
    remote endpoint they still fail closed but do not describe the remote host.
    """

    manager, paths, created = engagement
    spec = ContainerSpec.from_engagement(created, paths)
    if not runtime.image_exists(spec.image):
        pytest.skip(
            f"image {spec.image} is not present; build it before running this test"
        )

    host_lan = _host_lan_ip()

    def probe(script: str) -> ExecResult:
        return runtime.exec_capture(spec.name, ["/bin/sh", "-c", script])

    try:
        runtime.create_container(spec)
        runtime.start_container(spec.name)

        route = runtime.exec_capture(spec.name, ["ip", "route"])
        assert route.ok, route.stderr
        lines = [line for line in route.stdout.splitlines() if line.strip()]
        assert lines, "the runner has no route to its engagement network"
        assert not any(line.startswith("default") for line in lines)
        assert any("dev eth0" in line for line in lines)

        network = runtime.network_inspect(spec.network)
        assert network.internal
        assert network.gateway_mode_ipv4 == "isolated"
        assert network.gateway_mode_ipv6 == "isolated"
        assert network.gateway is None, f"network still has a gateway: {network.gateway}"

        bridge = f"br-{network.id[:12]}"
        if shutil.which("ip"):
            host_bridge = subprocess.run(
                ["ip", "-4", "-o", "addr", "show", "dev", bridge],
                capture_output=True,
                text=True,
                check=False,
            )
            assert "inet " not in host_bridge.stdout, (
                f"the host still has an address on {bridge}: {host_bridge.stdout}"
            )

        ipv6 = runtime.exec_capture(
            spec.name, ["ip", "-6", "addr", "show", "scope", "global"]
        )
        assert ipv6.ok, ipv6.stderr
        assert ipv6.stdout.strip() == "", "the runner has a global IPv6 address"

        dns = runtime.exec_capture(spec.name, ["getent", "hosts", "example.com"])
        assert not dns.ok, "external DNS resolution succeeded"

        # Real connection attempts to host services and public destinations.
        # Port 22 is SSH, 5432 is the existing PostgreSQL listener, and 5355
        # is another host-wide listener on this workstation.
        targets = [
            (host_lan, 22),
            (host_lan, 5432),
            (host_lan, 5355),
            ("1.1.1.1", 443),
            ("8.8.8.8", 53),
            ("169.254.169.254", 80),
        ]
        for address in _host_ipv4_addresses():
            if address == host_lan:
                continue
            targets.extend([(address, 22), (address, 5432)])
        for address, port in targets:
            result = probe(f"timeout 4 nc -z -w 2 {address} {port}")
            assert not result.ok, f"runner reached {address}:{port}"

        ipv6_target = probe(
            "timeout 4 nc -6 -z -w 2 2606:4700:4700::1111 443"
        )
        assert not ipv6_target.ok, "runner reached a public IPv6 destination"

        http = probe("timeout 6 curl -sS -o /dev/null http://example.com")
        assert not http.ok, "runner followed an HTTP redirect to a public host"

        # Container-to-container traffic on the engagement network must work:
        # authorized lab targets live on this bridge.
        address = runtime.exec_capture(spec.name, ["hostname", "-i"])
        assert address.ok, address.stderr
        runner_ip = address.stdout.split()[0]
        listener = runtime.exec_capture(
            spec.name,
            ["/bin/sh", "-c", "nc -lk -p 8080 >/dev/null 2>&1 &"],
        )
        assert listener.ok, listener.stderr
        time.sleep(0.5)

        by_ip = runtime.run_ephemeral(
            spec.image,
            ["-c", f"timeout 4 nc -z -w 2 {runner_ip} 8080"],
            entrypoint="/bin/sh",
            network=spec.network,
            timeout=30,
        )
        assert by_ip.exit_code == 0, by_ip.stderr

        by_name = runtime.run_ephemeral(
            spec.image,
            ["-c", f"timeout 4 nc -z -w 2 {spec.name} 8080"],
            entrypoint="/bin/sh",
            network=spec.network,
            timeout=30,
        )
        assert by_name.exit_code == 0, by_name.stderr

        # A redirect to a public host must fail when the client follows it.
        redirect = runtime.exec_capture(
            spec.name,
            [
                "/bin/sh",
                "-c",
                "while true; do "
                "printf 'HTTP/1.1 302 Found\\r\\n"
                "Location: http://example.com/\\r\\n"
                "Content-Length: 0\\r\\n\\r\\n' | nc -l -p 8081; "
                "done >/dev/null 2>&1 &",
            ],
        )
        assert redirect.ok, redirect.stderr
        time.sleep(0.5)
        followed = runtime.run_ephemeral(
            spec.image,
            [
                "-c",
                f"curl -sSL -o /dev/null --max-time 8 http://{runner_ip}:8081",
            ],
            entrypoint="/bin/sh",
            network=spec.network,
            timeout=30,
        )
        assert followed.exit_code != 0, "runner followed a redirect to a public host"
    finally:
        if runtime.inspect_container_optional(spec.name) is not None:
            runtime.remove_container(spec.name, force=True)
        if spec.network != "none" and runtime.network_exists(spec.network):
            runtime.network_remove(spec.network)
