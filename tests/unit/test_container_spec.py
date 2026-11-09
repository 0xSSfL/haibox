"""Deny-by-default container specification tests."""

from __future__ import annotations

import dataclasses
import os
from pathlib import Path

import pytest

from haibox.errors import ValidationError
from haibox.models import Engagement
from haibox.paths import Paths
from haibox.runtime.spec import ContainerSpec, ensure_workspace_ownership


@pytest.fixture
def spec(engagement: Engagement, paths: Paths) -> ContainerSpec:
    return ContainerSpec.from_engagement(engagement, paths)


def _mounts(args: list[str]) -> list[str]:
    return [args[index + 1] for index, value in enumerate(args) if value == "--mount"]


def test_create_args_have_the_security_shape(spec: ContainerSpec) -> None:
    args = spec.to_create_args()
    assert args[0] == "create"
    assert args[args.index("--name") + 1] == "haibox-demo"
    assert args[args.index("--hostname") + 1] == "haibox-demo"
    assert args[args.index("--network") + 1] == "haibox-demo-net"
    assert args[args.index("--user") + 1] == f"{spec.uid}:{spec.gid}"
    assert args[args.index("--workdir") + 1] == "/workspace"
    assert "--read-only" in args
    assert args[args.index("--cap-drop") + 1] == "ALL"
    assert args[args.index("--security-opt") + 1] == "no-new-privileges:true"
    assert args[args.index("--ipc") + 1] == "private"
    assert args[args.index("--restart") + 1] == "no"
    assert args[args.index("--init") : args.index("--init") + 1] == ["--init"]
    assert "--privileged" not in args
    assert "--pid" not in args
    assert "--device" not in args
    assert "--publish" not in args
    assert "-p" not in args
    assert "--volume" not in args
    assert "-v" not in args
    networks = [args[index + 1] for index, value in enumerate(args) if value == "--network"]
    assert "host" not in networks


def test_only_workspace_and_scope_are_mounted(spec: ContainerSpec) -> None:
    mounts = _mounts(spec.to_create_args())
    assert len(mounts) == 2
    assert f"source={spec.workspace},target=/workspace" in mounts[0]
    assert "readonly" not in mounts[0]
    assert f"source={spec.scope_file},target=/etc/haibox/scope.json,readonly" in mounts[1]


def test_environment_includes_reserved_values(spec: ContainerSpec) -> None:
    assert spec.environment["HAIBOX_ENGAGEMENT"] == "demo"
    assert spec.environment["HAIBOX_PROFILE"] == "web-security"
    assert spec.environment["HAIBOX_SCOPE_FILE"] == "/etc/haibox/scope.json"
    assert spec.environment["HOME"] == "/workspace/.home"
    assert spec.environment["TMPDIR"] == "/tmp"


def test_describe_does_not_include_secret_values(spec: ContainerSpec) -> None:
    described = spec.describe()
    assert described["read_only"] is True
    assert described["cap_drop"] == ["ALL"]
    assert described["no_new_privileges"] is True
    assert described["environment_keys"] == sorted(spec.environment)
    assert "environment" not in described


def test_unknown_capability_is_rejected(spec: ContainerSpec) -> None:
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, capabilities=["SYS_ADMIN"])


def test_root_user_is_rejected(spec: ContainerSpec) -> None:
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, uid=0)
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, gid=0)


def test_relative_paths_are_rejected(spec: ContainerSpec) -> None:
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, workspace=Path("relative"))
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, scope_file=Path("relative.json"))


def test_missing_scope_file_is_rejected(spec: ContainerSpec, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, scope_file=tmp_path / "missing.json")


def test_symlink_workspace_is_rejected(spec: ContainerSpec, tmp_path: Path) -> None:
    link = tmp_path / "workspace-link"
    link.symlink_to(spec.workspace, target_is_directory=True)
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, workspace=link)


def test_comma_in_path_is_rejected(spec: ContainerSpec, tmp_path: Path) -> None:
    comma = tmp_path / "with,comma"
    comma.mkdir()
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, workspace=comma)


def test_managed_label_is_required(spec: ContainerSpec) -> None:
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, labels={})


def test_invalid_network_is_rejected(spec: ContainerSpec) -> None:
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, network="host")


def test_invalid_image_is_rejected(spec: ContainerSpec) -> None:
    with pytest.raises(ValidationError):
        dataclasses.replace(spec, image="-privileged")


def test_from_engagement_copies_frozen_runtime(engagement: Engagement, paths: Paths) -> None:
    spec = ContainerSpec.from_engagement(engagement, paths)
    assert spec.image == engagement.image
    assert spec.network == engagement.runtime.network_name
    assert spec.uid == engagement.runtime.uid
    assert spec.gid == engagement.runtime.gid
    assert spec.capabilities == engagement.runtime.capabilities
    assert spec.labels["haibox.engagement"] == engagement.id
    assert spec.labels["haibox.managed"] == "true"


@pytest.mark.skipif(os.geteuid() == 0, reason="ownership checks are meaningless as root")
def test_workspace_ownership_check(spec: ContainerSpec) -> None:
    ensure_workspace_ownership(spec.workspace, os.getuid(), os.getgid())
    with pytest.raises(ValidationError):
        ensure_workspace_ownership(spec.workspace, os.getuid() + 1, os.getgid())


def test_workspace_ownership_requires_a_directory(spec: ContainerSpec, tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        ensure_workspace_ownership(tmp_path / "missing", os.getuid(), os.getgid())
