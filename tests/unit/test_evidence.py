"""Evidence store tests, including the symlink and duplicate-ID regressions."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from haibox.errors import EvidenceError
from haibox.evidence import EvidenceEntry, EvidenceStore


def _entry(**overrides: object) -> EvidenceEntry:
    values: dict[str, object] = {
        "id": "ev-20260101T000000Z-12345678-abcdef",
        "original_name": "note.txt",
        "stored_name": "ev-20260101T000000Z-12345678-abcdef-note.txt",
        "sha256": "0" * 64,
        "size": 0,
        "added_at": "2026-01-01T00:00:00+00:00",
        "note": "",
        "tags": [],
    }
    values.update(overrides)
    return EvidenceEntry(**values)  # type: ignore[arg-type]


def test_add_and_verify(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("evidence\n", encoding="utf-8")
    store = EvidenceStore(tmp_path / "evidence")

    entry = store.add(source, note="first", tags=["b", "a", "a"])

    assert entry.id.startswith("ev-")
    assert entry.original_name == "note.txt"
    assert entry.stored_name.startswith(entry.id)
    assert entry.tags == ["a", "b"]
    stored = store.path_for(entry)
    assert stored.is_file()
    assert stat.S_IMODE(stored.stat().st_mode) == 0o400
    assert stat.S_IMODE(store.manifest_path.stat().st_mode) == 0o600
    assert store.verify().valid
    assert store.get(entry.id) == entry


def test_duplicate_content_gets_unique_ids(tmp_path: Path) -> None:
    source = tmp_path / "same.txt"
    source.write_text("same bytes\n", encoding="utf-8")
    store = EvidenceStore(tmp_path / "evidence")

    first = store.add(source)
    second = store.add(source)

    assert first.id != second.id
    assert first.sha256 == second.sha256
    assert len(store.list()) == 2
    assert store.verify().valid


def test_symlink_source_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("data\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(EvidenceError):
        EvidenceStore(tmp_path / "evidence").add(link)


def test_symlinked_path_component_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    source = real / "note.txt"
    source.write_text("data\n", encoding="utf-8")
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    with pytest.raises(EvidenceError):
        EvidenceStore(tmp_path / "evidence").add(link / "note.txt")


def test_source_inside_store_is_rejected(tmp_path: Path) -> None:
    store = EvidenceStore(tmp_path / "evidence")
    source = tmp_path / "source.txt"
    source.write_text("data\n", encoding="utf-8")
    entry = store.add(source)
    with pytest.raises(EvidenceError):
        store.add(store.path_for(entry))


def test_directory_source_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(EvidenceError):
        EvidenceStore(tmp_path / "evidence").add(tmp_path)


def test_missing_source_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(EvidenceError):
        EvidenceStore(tmp_path / "evidence").add(tmp_path / "missing.txt")


def test_path_for_rejects_traversal() -> None:
    store = EvidenceStore(Path("/tmp/evidence"))
    for stored_name in ["../escape", "/etc/passwd", "", "."]:
        with pytest.raises(EvidenceError):
            store.path_for(_entry(stored_name=stored_name))


def test_verify_detects_tampering(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("original\n", encoding="utf-8")
    store = EvidenceStore(tmp_path / "evidence")
    entry = store.add(source)
    stored = store.path_for(entry)
    stored.chmod(0o600)
    stored.write_text("tampered\n", encoding="utf-8")
    stored.chmod(0o400)

    result = store.verify()
    assert not result.valid
    assert any("SHA-256 mismatch" in error for error in result.errors)


def test_verify_detects_writable_file(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("data\n", encoding="utf-8")
    store = EvidenceStore(tmp_path / "evidence")
    entry = store.add(source)
    store.path_for(entry).chmod(0o600)

    result = store.verify()
    assert not result.valid
    assert any("writable" in error for error in result.errors)


def test_verify_detects_missing_and_symlinked_files(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("data\n", encoding="utf-8")
    store = EvidenceStore(tmp_path / "evidence")
    entry = store.add(source)
    stored = store.path_for(entry)
    stored.unlink()
    stored.symlink_to(source)

    result = store.verify()
    assert not result.valid
    assert any("symbolic link" in error for error in result.errors)

    stored.unlink()
    result = store.verify()
    assert not result.valid
    assert any("missing" in error for error in result.errors)


def test_remove_updates_manifest(tmp_path: Path) -> None:
    source = tmp_path / "note.txt"
    source.write_text("data\n", encoding="utf-8")
    store = EvidenceStore(tmp_path / "evidence")
    entry = store.add(source)
    store.remove(entry.id)
    assert store.list() == []
    assert not store.path_for(entry).exists()


def test_invalid_manifest_is_reported(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    (root / "manifest.json").write_text(json.dumps({"entries": {}}), encoding="utf-8")
    with pytest.raises(EvidenceError):
        EvidenceStore(root).list()


def test_manifest_symlink_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "evidence"
    root.mkdir()
    target = tmp_path / "manifest.json"
    target.write_text(json.dumps({"api_version": "haibox/v1", "entries": []}), encoding="utf-8")
    (root / "manifest.json").symlink_to(target)
    with pytest.raises(EvidenceError):
        EvidenceStore(root).list()


def test_evidence_root_symlink_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "evidence"
    link.symlink_to(target, target_is_directory=True)
    store = EvidenceStore(link)
    with pytest.raises(EvidenceError):
        store.add(tmp_path / "source.txt")
    with pytest.raises(EvidenceError):
        store.list()
    with pytest.raises(EvidenceError):
        store.verify()
