"""Redaction helpers.

The audit log and command previews must never contain secret material.  This
module intentionally errs on the side of over-redaction: it handles explicit
secret keys, common credential-looking flags, URL userinfo, and bearer tokens.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

REDACTED = "***REDACTED***"

_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "private_key",
    "credential",
    "authorization",
    "cookie",
    "session",
)

_FLAG_PATTERNS = [
    re.compile(r"(?i)(--?(?:password|passwd|pass|token|api[-_]?key|secret)(?:=|\s+))([^\s]+)"),
    re.compile(r"(?i)(authorization:\s*(?:bearer|basic)\s+)([^\s]+)"),
    re.compile(r"(?i)(bearer\s+)([A-Za-z0-9._~+/\-]+=*)"),
]

_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/@\s]+)@")
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b("
    r"[A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|PRIVATE_KEY|CREDENTIAL)"
    r"[A-Z0-9_]*=)([^\s]+)"
)


def is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def redact_text(value: str) -> str:
    """Redact common credential shapes from a free-form string."""

    text = _URL_USERINFO.sub(lambda m: f"{m.group(1)}{REDACTED}@", value)
    text = _SECRET_ASSIGNMENT.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    for pattern in _FLAG_PATTERNS:
        text = pattern.sub(lambda m: f"{m.group(1)}{REDACTED}", text)
    return text


def redact(value: Any) -> Any:
    """Recursively redact a JSON-like value."""

    if isinstance(value, Mapping):
        return {
            str(key): (REDACTED if is_sensitive_key(str(key)) else redact(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_args(args: Iterable[str]) -> list[str]:
    """Redact a command argument vector without changing its shape."""

    return [redact_text(arg) for arg in args]


def redact_env(env: Mapping[str, str]) -> dict[str, str]:
    return {
        key: (REDACTED if is_sensitive_key(key) else value)
        for key, value in env.items()
    }
