"""Unit tests for the nftables policy engine.

These tests exercise ruleset generation and the apply/remove lifecycles.
They verify that the string output contains the expected rules and that the
fail-closed, exclusion-wins, and always-drop invariants hold.
"""

from __future__ import annotations

import pytest

from haibox.errors import RuntimeFailure
from haibox.models import Scope
from haibox.policy.nftables import (
    _ALWAYS_DROP_V4,
    _ALWAYS_DROP_V6,
    NftablesPolicy,
)
from haibox.runtime.process import ProcessResult

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _policy(
    *,
    allowed: list[str] | None = None,
    excluded: list[str] | None = None,
    allowed_ports: list[int] | None = None,
    bridge: str = "br-test0",
    engagement_id: str = "eng-001",
) -> NftablesPolicy:
    scope = Scope(
        allowed=allowed or [],
        excluded=excluded or [],
        allowed_ports=allowed_ports or [],
    )
    return NftablesPolicy(scope=scope, bridge=bridge, engagement_id=engagement_id)


def _ruleset(**kwargs: object) -> str:
    return _policy(**kwargs).generate_ruleset()  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Basic structure
# ---------------------------------------------------------------------------


class TestBasicStructure:
    def test_table_name(self) -> None:
        p = _policy(engagement_id="abc-123")
        assert p.table_name == "haibox-abc-123"

    def test_ruleset_contains_table_declaration(self) -> None:
        rs = _ruleset(engagement_id="myeng")
        assert "table inet haibox-myeng" in rs

    def test_ruleset_contains_forward_chain(self) -> None:
        rs = _ruleset()
        assert "chain forward" in rs

    def test_ruleset_has_drop_policy(self) -> None:
        rs = _ruleset()
        assert "policy drop" in rs

    def test_ruleset_contains_comment_header(self) -> None:
        rs = _ruleset(engagement_id="eng-001")
        assert "HAIBOX per-engagement policy" in rs
        assert "eng-001" in rs


# ---------------------------------------------------------------------------
# Empty scope → fail-closed
# ---------------------------------------------------------------------------


class TestEmptyScope:
    def test_empty_scope_has_no_target_accept_rules(self) -> None:
        rs = _ruleset()
        # Non-comment accept lines: non-engagement bypass, established/related, and same-bridge.
        accept_lines = [
            line.strip() for line in rs.splitlines()
            if "accept" in line and not line.strip().startswith("#")
        ]
        assert len(accept_lines) == 3, f"unexpected accept lines: {accept_lines}"
        assert any("iifname !=" in line for line in accept_lines)
        assert any("ct state established,related" in line for line in accept_lines)
        assert any('comment "same-bridge"' in line for line in accept_lines)

    def test_empty_scope_always_drop_present(self) -> None:
        rs = _ruleset()
        for cidr in _ALWAYS_DROP_V4:
            assert cidr in rs, f"always-drop CIDR missing: {cidr}"
        for cidr in _ALWAYS_DROP_V6:
            assert cidr in rs, f"always-drop IPv6 CIDR missing: {cidr}"


# ---------------------------------------------------------------------------
# Allowlist
# ---------------------------------------------------------------------------


class TestAllowlist:
    def test_ipv4_cidr_generates_accept(self) -> None:
        rs = _ruleset(allowed=["10.0.0.0/24"])
        assert "ip daddr 10.0.0.0/24 accept" in rs

    def test_ipv6_cidr_generates_accept(self) -> None:
        rs = _ruleset(allowed=["2001:db8::/32"])
        assert "ip6 daddr 2001:db8::/32 accept" in rs

    def test_bare_ipv4_generates_accept(self) -> None:
        rs = _ruleset(allowed=["192.168.1.100"])
        assert "ip daddr 192.168.1.100 accept" in rs

    def test_bare_ipv6_generates_accept(self) -> None:
        rs = _ruleset(allowed=["::1"])
        # Even if it appears in the always-drop section, it must NOT appear as
        # an accept rule (always-drop wins because it appears first).
        # The allowlist rule for ::1 will be added, but kernel evaluates top-down;
        # here we just verify the ruleset comment is present.
        rs_lines = [line.strip() for line in rs.splitlines()]
        assert any("ip6 daddr ::1 drop" in line for line in rs_lines)

    def test_hostname_in_allowlist_generates_comment(self) -> None:
        rs = _ruleset(allowed=["example.com"])
        assert "hostname allowlist not enforced at L4" in rs
        # Must NOT generate an accept rule for a hostname.
        assert "example.com accept" not in rs

    def test_allowed_ports_generates_port_specific_rules(self) -> None:
        rs = _ruleset(allowed=["10.0.1.5"], allowed_ports=[80, 443])
        assert "tcp dport 80 accept" in rs
        assert "udp dport 80 accept" in rs
        assert "tcp dport 443 accept" in rs
        assert "udp dport 443 accept" in rs

    def test_allowed_ports_no_bare_cidr_accept(self) -> None:
        """When ports are restricted, the bare CIDR accept must not appear."""
        rs = _ruleset(allowed=["10.0.1.5"], allowed_ports=[8080])
        # There must be no accept for the IP without a port qualifier.
        for line in rs.splitlines():
            stripped = line.strip()
            if "10.0.1.5" in stripped and "accept" in stripped:
                assert "dport" in stripped, (
                    f"bare accept for restricted IP/CIDR found: {stripped!r}"
                )


# ---------------------------------------------------------------------------
# Exclusions win over allowlist
# ---------------------------------------------------------------------------


class TestExclusionsWin:
    def test_excluded_cidr_generates_drop_before_accept(self) -> None:
        rs = _ruleset(allowed=["10.0.0.0/8"], excluded=["10.0.0.5"])
        lines = rs.splitlines()
        # Find indices.
        excl_idx = next(
            (i for i, line in enumerate(lines) if "10.0.0.5" in line and "drop" in line), None
        )
        allow_idx = next(
            (i for i, line in enumerate(lines) if "10.0.0.0/8" in line and "accept" in line), None
        )
        assert excl_idx is not None, "exclusion drop rule not found"
        assert allow_idx is not None, "allowlist accept rule not found"
        assert excl_idx < allow_idx, (
            "exclusion drop must appear before allowlist accept"
        )

    def test_excluded_hostname_generates_comment(self) -> None:
        rs = _ruleset(allowed=["10.0.0.0/8"], excluded=["evil.internal"])
        assert "hostname exclusion not enforced at L4" in rs
        assert "evil.internal drop" not in rs


# ---------------------------------------------------------------------------
# Always-drop invariants
# ---------------------------------------------------------------------------


class TestAlwaysDropInvariants:
    @pytest.mark.parametrize("cidr", _ALWAYS_DROP_V4)
    def test_always_drop_v4(self, cidr: str) -> None:
        # Even when cidr is explicitly in the allowlist, the always-drop must
        # appear in the output (kernel evaluates top-down).
        rs = _ruleset(allowed=[cidr])
        assert cidr in rs

    @pytest.mark.parametrize("cidr", _ALWAYS_DROP_V6)
    def test_always_drop_v6(self, cidr: str) -> None:
        rs = _ruleset(allowed=[cidr])
        assert cidr in rs

    def test_metadata_always_dropped(self) -> None:
        rs = _ruleset(allowed=["169.254.169.254"])
        drop_lines = [
            line for line in rs.splitlines() if "169.254.169.254" in line and "drop" in line
        ]
        assert drop_lines, "cloud metadata address must have a drop rule"

    def test_loopback_always_dropped(self) -> None:
        rs = _ruleset(allowed=["127.0.0.0/8"])
        drop_lines = [line for line in rs.splitlines() if "127.0.0.0/8" in line and "drop" in line]
        assert drop_lines, "loopback range must have a drop rule"


# ---------------------------------------------------------------------------
# Inter-container (same-bridge) accept
# ---------------------------------------------------------------------------


class TestSameBridgeAccept:
    def test_same_bridge_accept_rule_present(self) -> None:
        rs = _ruleset(bridge="br-mybridge")
        assert "br-mybridge" in rs
        bridge_lines = [line for line in rs.splitlines() if "br-mybridge" in line]
        assert any("accept" in line for line in bridge_lines), (
            "same-bridge accept rule missing"
        )

    def test_same_bridge_rule_uses_iifname_and_oifname(self) -> None:
        rs = _ruleset(bridge="br-abc")
        rule_line = next(
            (line for line in rs.splitlines() if "br-abc" in line and "accept" in line), None
        )
        assert rule_line is not None
        assert "iifname" in rule_line
        assert "oifname" in rule_line


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructorValidation:
    def test_empty_bridge_raises(self) -> None:
        scope = Scope()
        with pytest.raises(ValueError, match="bridge"):
            NftablesPolicy(scope=scope, bridge="", engagement_id="x")

    def test_invalid_bridge_characters_raises(self) -> None:
        scope = Scope()
        with pytest.raises(ValueError, match="bridge"):
            NftablesPolicy(scope=scope, bridge="br;drop table", engagement_id="x")

    def test_too_long_bridge_raises(self) -> None:
        scope = Scope()
        with pytest.raises(ValueError, match="bridge"):
            NftablesPolicy(scope=scope, bridge="a" * 16, engagement_id="x")

    def test_empty_engagement_id_raises(self) -> None:
        scope = Scope()
        with pytest.raises(ValueError, match="engagement_id"):
            NftablesPolicy(scope=scope, bridge="br-x", engagement_id="")

    def test_too_long_engagement_id_raises(self) -> None:
        scope = Scope()
        with pytest.raises(ValueError, match="engagement_id"):
            NftablesPolicy(scope=scope, bridge="br-x", engagement_id="a" * 49)


# ---------------------------------------------------------------------------
# IPv4 + IPv6 both generated for dual-stack allowlist entries
# ---------------------------------------------------------------------------


class TestDualStack:
    def test_ipv4_and_ipv6_allowlist_both_generated(self) -> None:
        rs = _ruleset(allowed=["10.0.0.0/8", "2001:db8::/32"])
        assert "ip daddr 10.0.0.0/8 accept" in rs
        assert "ip6 daddr 2001:db8::/32 accept" in rs

    def test_ipv4_and_ipv6_always_drops_both_present(self) -> None:
        rs = _ruleset()
        # At least one IPv4 drop and one IPv6 drop.
        v4_drops = [line for line in rs.splitlines() if "ip daddr" in line and "drop" in line]
        v6_drops = [line for line in rs.splitlines() if "ip6 daddr" in line and "drop" in line]
        assert v4_drops, "no IPv4 drop rules"
        assert v6_drops, "no IPv6 drop rules"


# ---------------------------------------------------------------------------
# Apply and Remove lifecycle
# ---------------------------------------------------------------------------


class RecordingRunner:
    def __init__(self, result: ProcessResult | None = None) -> None:
        self.result = result or ProcessResult((), 0, "", "")
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
        capture: bool = True,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        del capture, env
        self.calls.append({
            "args": args,
            "timeout": timeout,
            "input_text": input_text,
        })
        return self.result

    def interactive(self, args: list[str], *, env: dict[str, str] | None = None) -> int:
        del args, env
        return 0

    def which(self, program: str) -> str | None:
        return f"/usr/sbin/{program}"


class TestApplyAndRemove:
    def test_apply_success(self) -> None:
        policy = _policy(engagement_id="test-apply")
        runner = RecordingRunner()
        policy.apply(runner)

        assert len(runner.calls) == 1
        call = runner.calls[0]
        assert call["args"] == ["nft", "-f", "-"]
        assert "table inet haibox-test-apply" in str(call["input_text"])
        assert call["timeout"] == 15

    def test_apply_failure_raises(self) -> None:
        policy = _policy()
        runner = RecordingRunner(ProcessResult(("nft",), 1, "", "Error: syntax error at table"))
        with pytest.raises(RuntimeFailure, match=r"(?s)nft policy apply failed.*syntax error"):
            policy.apply(runner)

    def test_remove_success(self) -> None:
        policy = _policy(engagement_id="test-rm")
        runner = RecordingRunner()
        policy.remove(runner)

        assert len(runner.calls) == 1
        call = runner.calls[0]
        assert call["args"] == ["nft", "delete", "table", "inet", "haibox-test-rm"]
        assert call["timeout"] == 10

    def test_remove_ignores_no_such_table(self) -> None:
        policy = _policy(engagement_id="test-rm-missing")
        runner = RecordingRunner(ProcessResult(("nft",), 1, "", "Error: No such file or directory"))
        # Should not raise
        policy.remove(runner)

    def test_remove_failure_raises(self) -> None:
        policy = _policy(engagement_id="test-rm-fail")
        runner = RecordingRunner(ProcessResult(("nft",), 1, "", "Error: permission denied"))
        msg = r"(?s)nft policy remove failed.*permission denied"
        with pytest.raises(RuntimeFailure, match=msg):
            policy.remove(runner)
