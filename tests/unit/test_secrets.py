"""Host-only secret store tests."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from haibox.errors import SecretError
from haibox.secrets import SecretStore


def test_set_get_list_and_remove(tmp_path: Path) -> None:
    store = SecretStore(tmp_path / "secrets.json")
    created = store.set("api_key", "value-1")
    assert created.name == "api_key"
    assert store.get("api_key") == "value-1"

    names = store.list()
    assert [item.name for item in names] == ["api_key"]

    store.set("api_key", "value-2")
    assert store.get("api_key") == "value-2"
    updated = store.list()[0]
    assert updated.created_at == created.created_at
    assert updated.updated_at >= created.updated_at

    store.remove("api_key")
    assert store.list() == []
    with pytest.raises(SecretError):
        store.get("api_key")


def test_store_and_parent_permissions(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "secrets.json"
    SecretStore(path).set("name", "value")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700


def test_existing_permissive_mode_is_repaired(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    store = SecretStore(path)
    store.set("name", "value")
    path.chmod(0o644)
    assert store.get("name") == "value"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("name", ["", "1abc", "with space", "with/slash", "a" * 65])
def test_invalid_names_are_rejected(tmp_path: Path, name: str) -> None:
    with pytest.raises(SecretError):
        SecretStore(tmp_path / "secrets.json").set(name, "value")


def test_empty_value_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(SecretError):
        SecretStore(tmp_path / "secrets.json").set("name", "")


def test_missing_secret_is_reported(tmp_path: Path) -> None:
    with pytest.raises(SecretError):
        SecretStore(tmp_path / "secrets.json").get("missing")
    with pytest.raises(SecretError):
        SecretStore(tmp_path / "secrets.json").remove("missing")


def test_invalid_store_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "secrets.json"
    path.write_text(json.dumps({"secrets": []}), encoding="utf-8")
    with pytest.raises(SecretError):
        SecretStore(path).list()


def test_symlink_store_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.json"
    target.write_text(json.dumps({"api_version": "haibox/v1", "secrets": {}}), encoding="utf-8")
    link = tmp_path / "secrets.json"
    link.symlink_to(target)
    with pytest.raises(SecretError):
        SecretStore(link).list()
    with pytest.raises(SecretError):
        SecretStore(link).set("name", "value")


def test_symlinked_parent_directory_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "secrets"
    link.symlink_to(real, target_is_directory=True)
    store = SecretStore(link / "secrets.json")
    with pytest.raises(SecretError):
        store.set("name", "value")
    with pytest.raises(SecretError):
        store.list()
