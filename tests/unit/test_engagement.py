"""Engagement lifecycle and on-disk layout tests."""

from __future__ import annotations

import stat

import pytest

from haibox.audit import AuditLog
from haibox.engagement import EngagementManager
from haibox.errors import ConfigError, EngagementError, ScopeError
from haibox.models import Scope
from haibox.paths import Paths
from haibox.scope import load_scope

UID = 1000
GID = 1000


def _manager(paths: Paths) -> EngagementManager:
    return EngagementManager(paths)


def _create(manager: EngagementManager, engagement_id: str = "demo", **kwargs):
    values = {
        "name": "Demo engagement",
        "scope": Scope(allowed=["10.10.20.5"], allowed_ports=[443]),
        "uid": UID,
        "gid": GID,
    }
    values.update(kwargs)
    return manager.create(engagement_id, **values)


def test_create_layout_and_metadata(paths: Paths) -> None:
    manager = _manager(paths)
    engagement = _create(manager)

    root = paths.engagement_dir("demo")
    assert root.is_dir()
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for directory in ("workspace", "workspace/notes", "workspace/scans", "workspace/loot"):
        assert (root / directory).is_dir()
    assert (root / "workspace" / ".home").is_dir()
    assert (root / "evidence").is_dir()
    assert (root / "reports").is_dir()
    assert paths.scope_file("demo").is_file()
    assert stat.S_IMODE(paths.scope_file("demo").stat().st_mode) == 0o600
    assert paths.engagement_file("demo").is_file()
    assert stat.S_IMODE(paths.engagement_file("demo").stat().st_mode) == 0o600
    assert paths.current_file.read_text(encoding="utf-8").strip() == "demo"

    assert engagement.status == "active"
    assert engagement.owner
    assert engagement.profile == "web-security"
    assert engagement.runtime.uid == UID
    assert engagement.runtime.gid == GID
    assert engagement.runtime.container_name == "haibox-demo"
    assert engagement.runtime.network_name == "haibox-demo-net"
    assert engagement.runtime.environment["HAIBOX_SCOPE_FILE"] == "/etc/haibox/scope.json"
    assert engagement.runtime.environment["HOME"] == "/workspace/.home"

    assert load_scope(paths.scope_file("demo")).allowed == ["10.10.20.5"]
    assert manager.load("demo").id == "demo"
    assert manager.current() is not None
    assert manager.current().id == "demo"

    assert AuditLog(paths.engagement_audit_file("demo")).verify().valid
    platform = AuditLog(paths.logs_dir / "audit.jsonl")
    assert platform.verify().valid
    assert any(entry["event"] == "engagement.created" for entry in platform.read())


def test_duplicate_engagement_is_rejected(paths: Paths) -> None:
    manager = _manager(paths)
    _create(manager)
    with pytest.raises(EngagementError):
        _create(manager)


def test_invalid_id_is_rejected_before_touching_the_filesystem(paths: Paths) -> None:
    manager = _manager(paths)
    with pytest.raises(EngagementError):
        _create(manager, "../escape")
    assert not (paths.engagements_dir.parent / "escape").exists()


def test_unknown_profile_is_rejected(paths: Paths) -> None:
    with pytest.raises(ConfigError):
        _create(_manager(paths), profile_name="does-not-exist")


def test_planned_profile_is_rejected(paths: Paths) -> None:
    paths.ensure()
    (paths.profiles_dir / "planned.yaml").write_text(
        "\n".join(
            [
                "api_version: haibox/v1",
                "name: planned",
                "description: not implemented",
                "image: haibox/planned:0.1.0",
                "status: planned",
                "network: isolated",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(EngagementError):
        _create(_manager(paths), profile_name="planned")


def test_user_profile_override_is_used(paths: Paths) -> None:
    paths.ensure()
    (paths.profiles_dir / "web-security.yaml").write_text(
        "\n".join(
            [
                "api_version: haibox/v1",
                "name: web-security",
                "description: local override",
                "image: registry.example/web:1.2.3",
                "status: active",
                "network: isolated",
                "capabilities: []",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    engagement = _create(_manager(paths))
    assert engagement.image == "registry.example/web:1.2.3"
    assert engagement.profile == "web-security"


def test_runtime_settings_are_frozen_at_creation(paths: Paths) -> None:
    paths.ensure()
    profile_path = paths.profiles_dir / "web-security.yaml"
    profile_path.write_text(
        "\n".join(
            [
                "api_version: haibox/v1",
                "name: web-security",
                "description: local override",
                "image: haibox/web-security:0.1.0",
                "status: active",
                "network: isolated",
                "capabilities:",
                "  - NET_RAW",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    manager = _manager(paths)
    engagement = _create(manager)
    assert engagement.runtime.capabilities == ["NET_RAW"]

    profile_path.write_text(
        "\n".join(
            [
                "api_version: haibox/v1",
                "name: web-security",
                "description: widened after creation",
                "image: haibox/web-security:9.9.9",
                "status: active",
                "network: isolated",
                "capabilities:",
                "  - NET_RAW",
                "  - NET_BIND_SERVICE",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    reloaded = manager.load("demo")
    assert reloaded.runtime.capabilities == ["NET_RAW"]
    assert reloaded.image == "haibox/web-security:0.1.0"


def test_list_and_current_selection(paths: Paths) -> None:
    manager = _manager(paths)
    _create(manager, "demo")
    _create(manager, "second", name="Second", set_current=False)

    assert [item.id for item in manager.list()] == ["demo", "second"]
    assert manager.current().id == "demo"
    assert manager.resolve().id == "demo"

    manager.set_current("second")
    assert manager.current().id == "second"
    assert manager.resolve().id == "second"
    assert manager.resolve("demo").id == "demo"


def test_resolve_without_engagements(paths: Paths) -> None:
    paths.ensure()
    with pytest.raises(EngagementError):
        _manager(paths).resolve()


def test_resolve_is_ambiguous_without_a_current_pointer(paths: Paths) -> None:
    manager = _manager(paths)
    _create(manager, "demo")
    _create(manager, "second", name="Second", set_current=False)
    paths.current_file.unlink()
    with pytest.raises(EngagementError):
        manager.resolve()


def test_archive_and_destroy(paths: Paths) -> None:
    manager = _manager(paths)
    _create(manager)

    archived = manager.archive("demo")
    assert archived.status == "archived"
    assert not paths.current_file.exists()
    assert manager.current() is None

    manager.destroy("demo")
    assert not paths.engagement_dir("demo").exists()
    assert manager.list() == []

    platform = AuditLog(paths.logs_dir / "audit.jsonl")
    assert platform.verify().valid
    assert any(entry["event"] == "engagement.destroyed" for entry in platform.read())


def test_active_engagement_requires_force_to_destroy(paths: Paths) -> None:
    manager = _manager(paths)
    _create(manager)
    with pytest.raises(EngagementError):
        manager.destroy("demo")
    manager.destroy("demo", force=True)
    assert not paths.engagement_dir("demo").exists()


def test_set_scope_updates_files_and_audit(paths: Paths) -> None:
    manager = _manager(paths)
    _create(manager)
    updated = Scope(allowed=["example.com"], allowed_ports=[80, 443], notes="updated")
    engagement = manager.set_scope("demo", updated)

    assert engagement.scope == updated
    assert load_scope(paths.scope_file("demo")) == updated
    assert manager.load("demo").scope == updated
    entries = AuditLog(paths.engagement_audit_file("demo")).read()
    assert any(entry["event"] == "engagement.scope_changed" for entry in entries)


def test_network_none_profile(paths: Paths) -> None:
    paths.ensure()
    (paths.profiles_dir / "offline.yaml").write_text(
        "\n".join(
            [
                "api_version: haibox/v1",
                "name: offline",
                "description: no network",
                "image: haibox/offline:0.1.0",
                "status: experimental",
                "network: none",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    engagement = _create(_manager(paths), profile_name="offline")
    assert engagement.runtime.network_mode == "none"
    assert engagement.runtime.network_name == "none"


def test_current_pointer_traversal_is_rejected(paths: Paths) -> None:
    manager = _manager(paths)
    _create(manager)
    paths.current_file.write_text("../escape\n", encoding="utf-8")
    with pytest.raises(EngagementError):
        manager.current()


def test_engagement_file_symlink_is_rejected(paths: Paths) -> None:
    manager = _manager(paths)
    _create(manager)
    path = paths.engagement_file("demo")
    target = paths.data_dir / "other.yaml"
    target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(EngagementError):
        manager.load("demo")


def test_scope_file_symlink_is_rejected(paths: Paths) -> None:
    manager = _manager(paths)
    _create(manager)
    path = paths.scope_file("demo")
    target = paths.data_dir / "other-scope.json"
    target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(ScopeError):
        manager.scope("demo")
