"""Hash-chained audit log tests."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from haibox.audit import AuditLog
from haibox.errors import AuditError


def test_append_and_verify(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", actor="tester")
    first = log.append("one", data={"value": 1})
    second = log.append("two", engagement="demo", data={"value": 2})
    third = log.append("three")

    assert first["seq"] == 1
    assert second["seq"] == 2
    assert second["engagement"] == "demo"
    assert third["prev_hash"] == second["hash"]

    result = log.verify()
    assert result.valid
    assert result.entries == 3
    assert result.last_hash == third["hash"]
    assert log.read(limit=2) == [second, third]
    assert log.read(limit=0) == []


def test_actor_is_recorded(tmp_path: Path) -> None:
    log = AuditLog(tmp_path / "audit.jsonl", actor="default-actor")
    entry = log.append("event", actor="explicit-actor")
    assert entry["actor"] == "explicit-actor"


def test_tampering_with_data_breaks_the_chain(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("one", data={"value": 1})
    log.append("two", data={"value": 2})

    lines = path.read_text(encoding="utf-8").splitlines()
    payload = json.loads(lines[0])
    payload["data"]["value"] = 999
    lines[0] = json.dumps(payload, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = log.verify()
    assert not result.valid
    assert "invalid hash" in (result.error or "")


def test_deleting_an_entry_breaks_the_chain(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append("one")
    log.append("two")
    log.append("three")

    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")

    result = log.verify()
    assert not result.valid
    assert "seq" in (result.error or "")


def test_secrets_are_redacted_before_storage(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    log = AuditLog(path)
    log.append(
        "login",
        data={
            "username": "alice",
            "password": "hunter2",
            "api_token": "token-value",
            "command": ["tool", "--password=hunter2", "https://alice:hunter2@example.com"],
        },
    )
    text = path.read_text(encoding="utf-8")
    assert "hunter2" not in text
    assert "token-value" not in text
    assert "***REDACTED***" in text
    assert "alice" in text
    assert log.verify().valid


def test_corrupt_log_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text("{not-json}\n", encoding="utf-8")
    with pytest.raises(AuditError):
        AuditLog(path).read()


def test_empty_log_is_valid(tmp_path: Path) -> None:
    result = AuditLog(tmp_path / "missing.jsonl").verify()
    assert result.valid
    assert result.entries == 0


def test_negative_limit_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AuditError):
        AuditLog(tmp_path / "audit.jsonl").read(limit=-1)


def test_empty_event_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(AuditError):
        AuditLog(tmp_path / "audit.jsonl").append("   ")


def test_log_is_mode_0600(tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    AuditLog(path).append("event")
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600


def test_symlink_log_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target.jsonl"
    target.write_text("", encoding="utf-8")
    link = tmp_path / "audit.jsonl"
    link.symlink_to(target)
    with pytest.raises(AuditError):
        AuditLog(link).append("event")
    with pytest.raises(AuditError):
        AuditLog(link).read()


def test_symlinked_parent_directory_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "logs"
    link.symlink_to(real, target_is_directory=True)
    log = AuditLog(link / "audit.jsonl")
    with pytest.raises(AuditError):
        log.append("event")
    with pytest.raises(AuditError):
        log.read()
