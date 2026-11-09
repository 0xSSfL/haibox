"""Scope parsing and fail-closed matching tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from haibox.errors import ScopeError
from haibox.models import Scope
from haibox.scope import (
    ScopeMatcher,
    load_scope,
    parse_target,
    scope_to_json,
)


def test_parse_url_with_invalid_port_is_a_scope_error() -> None:
    with pytest.raises(ScopeError):
        parse_target("https://example.com:notaport")


def test_parse_url_uses_the_url_port() -> None:
    parsed = parse_target("https://example.com:8443/login")
    assert parsed.host == "example.com"
    assert parsed.port == 8443


def test_parse_url_port_must_agree_with_explicit_port() -> None:
    with pytest.raises(ScopeError):
        parse_target("https://example.com:8443", port=443)


def test_parse_bare_ipv6_target_has_no_port() -> None:
    parsed = parse_target("2001:db8::1")
    assert parsed.host == "2001:db8::1"
    assert parsed.port is None


def test_parse_bracketed_ipv6_with_port() -> None:
    parsed = parse_target("[2001:db8::1]:443")
    assert parsed.host == "2001:db8::1"
    assert parsed.port == 443


def test_parse_host_and_port() -> None:
    parsed = parse_target("example.com:8080")
    assert parsed.host == "example.com"
    assert parsed.port == 8080


def test_parse_non_numeric_host_port_is_rejected() -> None:
    with pytest.raises(ScopeError):
        parse_target("example.com:http")


@pytest.mark.parametrize("port", [0, 65536, -1])
def test_parse_rejects_out_of_range_ports(port: int) -> None:
    with pytest.raises(ScopeError):
        parse_target("example.com", port=port)


def test_parse_rejects_invalid_url_ipv6() -> None:
    with pytest.raises(ScopeError):
        parse_target("http://[::1")


def test_parse_rejects_path_like_host() -> None:
    with pytest.raises(ScopeError):
        parse_target("example.com/path")


def test_exact_hostname_match_is_case_insensitive() -> None:
    matcher = ScopeMatcher(Scope(allowed=["Example.COM"]))
    assert matcher.check("example.com").allowed


def test_wildcard_matches_subdomains_but_not_the_apex() -> None:
    matcher = ScopeMatcher(Scope(allowed=["*.example.com"]))
    assert matcher.check("a.example.com").allowed
    assert matcher.check("a.b.example.com").allowed
    assert not matcher.check("example.com").allowed
    assert not matcher.check("notexample.com").allowed


def test_ip_and_cidr_matching() -> None:
    matcher = ScopeMatcher(Scope(allowed=["10.0.0.0/8", "192.0.2.10"]))
    assert matcher.check("10.2.3.4").allowed
    assert matcher.check("192.0.2.10").allowed
    assert not matcher.check("192.0.2.11").allowed
    assert not matcher.check("11.0.0.1").allowed


def test_ipv6_cidr_matching() -> None:
    matcher = ScopeMatcher(Scope(allowed=["2001:db8::/32"]))
    assert matcher.check("2001:db8::5").allowed
    assert not matcher.check("2001:db9::5").allowed


def test_exclusions_always_win() -> None:
    matcher = ScopeMatcher(
        Scope(allowed=["10.0.0.0/8"], excluded=["10.1.0.0/16", "10.2.3.4"])
    )
    assert not matcher.check("10.1.2.3").allowed
    assert not matcher.check("10.2.3.4").allowed
    assert matcher.check("10.2.3.5").allowed


def test_port_specific_exclusion_covers_portless_target() -> None:
    matcher = ScopeMatcher(
        Scope(allowed=["10.2.3.4"], excluded=["10.2.3.4:443"])
    )
    decision = matcher.check("10.2.3.4")
    assert not decision.allowed
    assert "excluded" in decision.reason
    assert not matcher.check("10.2.3.4", port=443).allowed
    assert matcher.check("10.2.3.4", port=80).allowed


def test_empty_allow_list_denies_everything() -> None:
    decision = ScopeMatcher(Scope()).check("example.com")
    assert not decision.allowed
    assert "no allowed targets" in decision.reason


def test_allowed_port_list_requires_a_port() -> None:
    matcher = ScopeMatcher(Scope(allowed=["example.com"], allowed_ports=[443]))
    decision = matcher.check("example.com")
    assert not decision.allowed
    assert "port is required" in decision.reason
    assert matcher.check("example.com", port=443).allowed
    assert not matcher.check("example.com", port=80).allowed


def test_rule_port_is_enforced() -> None:
    matcher = ScopeMatcher(Scope(allowed=["https://example.com:8443"]))
    assert matcher.check("https://example.com:8443").allowed
    assert not matcher.check("https://example.com:443").allowed
    assert not matcher.check("example.com").allowed


def test_assert_allowed_raises() -> None:
    matcher = ScopeMatcher(Scope(allowed=["example.com"]))
    assert matcher.assert_allowed("example.com").allowed
    with pytest.raises(ScopeError):
        matcher.assert_allowed("example.org")


def test_scope_json_round_trip(tmp_path: Path) -> None:
    scope = Scope(
        allowed=["example.com", "10.0.0.0/8"],
        excluded=["10.1.0.0/16"],
        allowed_ports=[443, 80],
        notes="round trip",
    )
    path = tmp_path / "scope.json"
    path.write_text(scope_to_json(scope), encoding="utf-8")
    loaded = load_scope(path)
    assert loaded == scope
    assert json.loads(scope_to_json(scope))["allowed_ports"] == [80, 443]


def test_scope_file_symlink_is_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real.json"
    real.write_text(scope_to_json(Scope(allowed=["example.com"])), encoding="utf-8")
    link = tmp_path / "scope.json"
    link.symlink_to(real)
    with pytest.raises(ScopeError):
        load_scope(link)


def test_scope_model_rejects_invalid_ports() -> None:
    with pytest.raises(ValueError):
        Scope(allowed=["example.com"], allowed_ports=[70000])
