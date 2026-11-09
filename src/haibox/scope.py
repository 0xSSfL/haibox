"""Scope parsing and fail-closed target matching.

Scope entries may be IP addresses, CIDR networks, hostnames, wildcard
hostnames, or URLs.  Hostnames are never resolved: an IP target only matches an
IP or CIDR entry, so DNS rebinding cannot silently widen an engagement.
"""

from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlsplit

from haibox.errors import ScopeError
from haibox.models import Scope


def _normalise_host(host: str) -> str:
    value = host.strip().strip("[]").rstrip(".").lower()
    if not value:
        raise ScopeError("empty host")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass
    if "*" in value and not value.startswith("*."):
        raise ScopeError(f"unsupported wildcard host: {host!r}")
    if value.startswith("*."):
        suffix = value[2:]
        if not suffix or "*" in suffix:
            raise ScopeError(f"invalid wildcard host: {host!r}")
        return f"*.{_normalise_host(suffix)}"
    if any(ch.isspace() for ch in value) or any(ch in value for ch in "/\\@?#:"):
        raise ScopeError(f"invalid hostname: {host!r}")
    try:
        ascii_host = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ScopeError(f"invalid hostname: {host!r}") from exc
    if len(ascii_host) > 253:
        raise ScopeError(f"hostname is too long: {host!r}")
    for label in ascii_host.split("."):
        if not label or len(label) > 63 or not re.fullmatch(r"[a-z0-9_-]+", label):
            raise ScopeError(f"invalid hostname: {host!r}")
    return ascii_host


@dataclass(frozen=True)
class ParsedTarget:
    host: str
    port: int | None


def parse_target(target: str, port: int | None = None) -> ParsedTarget:
    """Parse a target as a host, URL, or host:port pair."""

    value = target.strip()
    if not value:
        raise ScopeError("target must not be empty")
    parsed_port = port
    if "://" in value:
        try:
            parts = urlsplit(value)
        except ValueError as exc:
            raise ScopeError(f"invalid target URL: {target!r}") from exc
        if not parts.hostname:
            raise ScopeError(f"target has no host: {target!r}")
        host = _normalise_host(parts.hostname)
        try:
            url_port = parts.port
        except ValueError as exc:
            raise ScopeError(f"invalid port in target: {target!r}") from exc
        if url_port is not None:
            if parsed_port is not None and parsed_port != url_port:
                raise ScopeError("target port and --port disagree")
            parsed_port = url_port
    elif value.startswith("[") and "]" in value:
        host_part, _, rest = value.partition("]")
        host = _normalise_host(host_part[1:])
        if rest.startswith(":"):
            try:
                url_port = int(rest[1:])
            except ValueError as exc:
                raise ScopeError(f"invalid port in target: {target!r}") from exc
            if parsed_port is not None and parsed_port != url_port:
                raise ScopeError("target port and --port disagree")
            parsed_port = url_port
        elif rest:
            raise ScopeError(f"invalid target: {target!r}")
    else:
        try:
            address = ipaddress.ip_address(value)
        except ValueError:
            address = None
        if address is not None:
            host = str(address)
        elif value.count(":") == 1:
            host_part, port_part = value.rsplit(":", 1)
            if not port_part.isdigit():
                raise ScopeError(f"invalid port in target: {target!r}")
            url_port = int(port_part)
            if parsed_port is not None and parsed_port != url_port:
                raise ScopeError("target port and --port disagree")
            parsed_port = url_port
            host = _normalise_host(host_part)
        else:
            host = _normalise_host(value)
    if parsed_port is not None and not 1 <= parsed_port <= 65535:
        raise ScopeError(f"invalid port: {parsed_port}")
    return ParsedTarget(host=host, port=parsed_port)


@dataclass(frozen=True)
class ScopeRule:
    raw: str
    kind: str
    host: str
    network: ipaddress.IPv4Network | ipaddress.IPv6Network | None = None
    port: int | None = None


def _rule_from_entry(entry: str) -> ScopeRule:
    value = entry.strip()
    if not value:
        raise ScopeError("scope entry must not be empty")
    if "/" in value and "://" not in value:
        try:
            network = ipaddress.ip_network(value, strict=False)
        except ValueError:
            # A hostname containing a slash is not a valid scope entry.
            raise ScopeError(f"invalid CIDR or hostname: {entry!r}") from None
        return ScopeRule(raw=entry, kind="network", host=str(network), network=network)
    # ``parse_target`` handles URLs, bare IPv6, bracketed IPv6 with a port,
    # and host:port entries.  A scope entry may carry a port; the matcher then
    # requires that exact port.
    parsed = parse_target(value)
    if parsed.host.startswith("*."):
        kind = "wildcard"
    else:
        try:
            ipaddress.ip_address(parsed.host)
        except ValueError:
            kind = "hostname"
        else:
            kind = "ip"
    return ScopeRule(raw=entry, kind=kind, host=parsed.host, port=parsed.port)


def _host_matches(rule: ScopeRule, host: str) -> bool:
    if rule.kind == "ip":
        try:
            return ipaddress.ip_address(host) == ipaddress.ip_address(rule.host)
        except ValueError:
            return False
    if rule.kind == "network":
        if rule.network is None:
            return False
        try:
            return ipaddress.ip_address(host) in rule.network
        except ValueError:
            return False
    if rule.kind == "hostname":
        return host == rule.host
    if rule.kind == "wildcard":
        suffix = rule.host[2:]
        return host != suffix and host.endswith(f".{suffix}")
    return False


def _rule_matches(rule: ScopeRule, target: ParsedTarget) -> bool:
    if not _host_matches(rule, target.host):
        return False
    return rule.port is None or rule.port == target.port


def _exclusion_matches(rule: ScopeRule, target: ParsedTarget) -> bool:
    """A port-specific exclusion also covers an ambiguous port-less target."""

    if not _host_matches(rule, target.host):
        return False
    return rule.port is None or target.port is None or rule.port == target.port


@dataclass(frozen=True)
class ScopeDecision:
    allowed: bool
    reason: str
    target: str
    port: int | None


class ScopeMatcher:
    """Evaluate targets against one engagement scope.

    Exclusions always win, an empty allow-list denies everything, and the
    optional port allow-list is applied after the host match.
    """

    def __init__(self, scope: Scope) -> None:
        self.scope = scope
        self._allowed = [_rule_from_entry(item) for item in scope.allowed]
        self._excluded = [_rule_from_entry(item) for item in scope.excluded]

    def check(self, target: str, port: int | None = None) -> ScopeDecision:
        parsed = parse_target(target, port=port)
        for rule in self._excluded:
            if _exclusion_matches(rule, parsed):
                return ScopeDecision(
                    allowed=False,
                    reason=f"excluded by rule {rule.raw!r}",
                    target=parsed.host,
                    port=parsed.port,
                )
        if not self._allowed:
            return ScopeDecision(
                allowed=False,
                reason="scope has no allowed targets",
                target=parsed.host,
                port=parsed.port,
            )
        if self.scope.allowed_ports and parsed.port is None:
            return ScopeDecision(
                allowed=False,
                reason="port is required when the scope defines an allowed port list",
                target=parsed.host,
                port=None,
            )
        match = next((rule for rule in self._allowed if _rule_matches(rule, parsed)), None)
        if match is None:
            return ScopeDecision(
                allowed=False,
                reason="target is not in the allowed scope",
                target=parsed.host,
                port=parsed.port,
            )
        if (
            self.scope.allowed_ports
            and parsed.port is not None
            and parsed.port not in self.scope.allowed_ports
        ):
            return ScopeDecision(
                allowed=False,
                reason=f"port {parsed.port} is not in the allowed port list",
                target=parsed.host,
                port=parsed.port,
            )
        return ScopeDecision(
            allowed=True,
            reason=f"matched allowed rule {match.raw!r}",
            target=parsed.host,
            port=parsed.port,
        )

    def assert_allowed(self, target: str, port: int | None = None) -> ScopeDecision:
        decision = self.check(target, port)
        if not decision.allowed:
            raise ScopeError(f"target {target!r} is out of scope: {decision.reason}")
        return decision


def load_scope(path: Path) -> Scope:
    if path.is_symlink():
        raise ScopeError(f"scope file must not be a symbolic link: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScopeError(f"cannot read scope file {path}: {exc}") from exc
    try:
        return Scope.model_validate(raw)
    except Exception as exc:
        raise ScopeError(f"invalid scope file {path}: {exc}") from exc


def scope_to_json(scope: Scope) -> str:
    return json.dumps(scope.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
