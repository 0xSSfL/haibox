"""nftables policy engine for per-engagement scope enforcement.

Each engagement bridge gets an independent nftables table (``inet
haibox-<id>``).  The table is applied *after* the Docker network is created
and *before* any runner container is started.  Teardown removes the table so
host rules remain clean.

Design principles (ADR-0003, ADR-0010):
- Fail-closed: if ``apply()`` fails the caller must abort the engagement.
- Exclusions win over the allowlist (same as the advisory ScopeMatcher).
- Cloud-metadata (169.254.169.254), loopback, and link-local addresses are
  always dropped regardless of scope content.
- Same-bridge inter-container traffic is always permitted (runners in the
  same engagement may communicate).
- All other traffic is dropped by the chain's default policy.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

from haibox.errors import RuntimeFailure
from haibox.models import Scope
from haibox.runtime.process import CommandRunner

_BRIDGE_RE = re.compile(r"^[a-zA-Z0-9_.-]{1,15}$")

# Addresses that must never be reachable from an engagement container.
_ALWAYS_DROP_V4: tuple[str, ...] = (
    "127.0.0.0/8",       # loopback
    "169.254.0.0/16",    # link-local (includes cloud metadata)
    "169.254.169.254",   # EC2 / GCP / Azure IMDS — explicit for clarity
)
_ALWAYS_DROP_V6: tuple[str, ...] = (
    "::1",        # IPv6 loopback
    "fe80::/10",  # IPv6 link-local
)

# Maximum engagement-ID suffix used in table/chain names.
_MAX_ID_LEN = 48
# nftables table family.
_FAMILY = "inet"


@dataclass(frozen=True)
class PolicyRule:
    """One compiled nftables verdict line (without trailing newline)."""

    verdict: str  # "accept" or "drop"
    comment: str
    # At most one of the following is set.
    cidr: str | None = None      # e.g. "192.168.1.0/24"
    address: str | None = None   # e.g. "169.254.169.254"
    port: int | None = None      # destination TCP/UDP port


class NftablesPolicy:
    """Generate and apply an nftables rule-set for one engagement.

    Parameters
    ----------
    scope:
        The engagement ``Scope`` (allowed targets, exclusions, allowed ports).
    bridge:
        The Docker bridge interface name (e.g. ``"br-abc123"``).  Traffic
        arriving on this interface is forwarded through the host.
    engagement_id:
        A short alphanumeric slug used as the nftables table suffix.  Must
        match ``[a-z0-9-]+`` and be at most 48 characters.
    """

    def __init__(self, scope: Scope, bridge: str, engagement_id: str) -> None:
        if not bridge or not _BRIDGE_RE.fullmatch(bridge):
            raise ValueError(f"invalid bridge interface name: {bridge!r}")
        if not engagement_id or len(engagement_id) > _MAX_ID_LEN:
            raise ValueError(
                f"engagement_id must be 1–{_MAX_ID_LEN} characters, got {engagement_id!r}"
            )
        self.scope = scope
        self.bridge = bridge
        self.engagement_id = engagement_id
        self._table = f"haibox-{engagement_id}"

    # ---------------------------------------------------------------- public

    @property
    def table_name(self) -> str:
        """The full nftables table name (without family prefix)."""
        return self._table

    def generate_ruleset(self) -> str:
        """Return a complete nftables ruleset string suitable for ``nft -f -``."""
        lines: list[str] = []

        lines.append(f"# HAIBOX per-engagement policy — {self.engagement_id}")
        lines.append(f"table {_FAMILY} {self._table} {{")
        lines.append("")
        lines.append("    chain forward {")
        lines.append("        type filter hook forward priority 0; policy drop;")
        lines.append("")

        # 1. Non-engagement traffic bypass (never drop unrelated host flows).
        lines.append("        # Non-engagement traffic bypass.")
        lines.append(
            f'        iifname != "{self.bridge}" oifname != "{self.bridge}" accept'
        )
        lines.append("")

        # 2. Always permit established / related packets (stateful).
        lines.append("        # Allow established/related connections.")
        lines.append(
            "        ct state established,related accept"
        )
        lines.append("")

        # 3. Inter-container: same-bridge traffic is always allowed.
        lines.append("        # Same-engagement inter-container traffic.")
        lines.append(
            f'        iifname "{self.bridge}" oifname "{self.bridge}" accept'
            ' comment "same-bridge"'
        )
        lines.append("")

        # 3. Always drop protected address ranges (before allowlist).
        lines.append("        # Protected ranges — always drop.")
        for cidr in _ALWAYS_DROP_V4:
            addr_type = "daddr"
            if ipaddress.ip_network(cidr, strict=False).version == 4:
                addr_type = "ip daddr"
            lines.append(f"        {addr_type} {cidr} drop comment \"protected\"")
        for cidr in _ALWAYS_DROP_V6:
            lines.append(f"        ip6 daddr {cidr} drop comment \"protected\"")
        lines.append("")

        # 4. Explicit exclusions from scope (drop before allowlist).
        if self.scope.excluded:
            lines.append("        # Scope exclusions — drop.")
            for entry in self.scope.excluded:
                rule_lines = self._entry_to_drop_lines(entry)
                lines.extend(f"        {r}" for r in rule_lines)
            lines.append("")

        # 5. Allowlist: scope.allowed × scope.allowed_ports → accept.
        if self.scope.allowed:
            lines.append("        # Scope allowlist — accept.")
            for entry in self.scope.allowed:
                rule_lines = self._entry_to_accept_lines(
                    entry, self.scope.allowed_ports
                )
                lines.extend(f"        {r}" for r in rule_lines)
            lines.append("")

        # 6. Implicit default drop (from chain policy above); add an explicit
        #    comment so the ruleset is self-documenting.
        lines.append("        # Default: drop (chain policy).")
        lines.append("    }")
        lines.append("}")
        lines.append("")

        return "\n".join(lines)

    def apply(self, runner: CommandRunner) -> None:
        """Load the ruleset into the kernel via ``nft -f -``.

        Raises :class:`~haibox.errors.RuntimeFailure` if ``nft`` fails.
        The caller *must* treat a failure as fatal and not start containers.
        """
        ruleset = self.generate_ruleset()
        result = runner.run(
            ["nft", "-f", "-"],
            input_text=ruleset,
            timeout=15,
        )
        if not result.ok:
            raise RuntimeFailure(
                f"nft policy apply failed (exit {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )

    def remove(self, runner: CommandRunner) -> None:
        """Delete the engagement table from the kernel.

        Idempotent: if the table does not exist, the error is ignored.
        """
        result = runner.run(
            ["nft", "delete", "table", _FAMILY, self._table],
            timeout=10,
        )
        if not result.ok:
            # "No such file or directory" (ENOENT) → already removed; ignore.
            stderr = result.stderr.lower()
            if "no such" not in stderr and "not found" not in stderr:
                raise RuntimeFailure(
                    f"nft policy remove failed (exit {result.returncode}):\n"
                    f"{result.stderr.strip()}"
                )

    # --------------------------------------------------------------- helpers

    @staticmethod
    def _parse_entry(entry: str) -> tuple[str, str]:
        """Return ``(family, nft_address)`` for a scope entry.

        Only IP addresses and CIDRs are supported at the network layer;
        hostnames are ignored (they must be resolved at advisory layer).
        Returns ``("skip", "")`` for non-IP entries.
        """
        value = entry.strip()
        # Try CIDR first.
        if "/" in value:
            try:
                net = ipaddress.ip_network(value, strict=False)
                family = "ip" if net.version == 4 else "ip6"
                return family, str(net)
            except ValueError:
                return "skip", ""
        # Try bare address.
        try:
            addr = ipaddress.ip_address(value)
            family = "ip" if addr.version == 4 else "ip6"
            return family, str(addr)
        except ValueError:
            return "skip", ""

    @classmethod
    def _entry_to_drop_lines(cls, entry: str) -> list[str]:
        family, addr = cls._parse_entry(entry)
        if family == "skip":
            return [f"# (hostname exclusion not enforced at L4: {entry!r})"]
        return [f"{family} daddr {addr} drop comment \"excluded\""]

    @classmethod
    def _entry_to_accept_lines(cls, entry: str, allowed_ports: list[int]) -> list[str]:
        family, addr = cls._parse_entry(entry)
        if family == "skip":
            return [f"# (hostname allowlist not enforced at L4: {entry!r})"]
        if not allowed_ports:
            return [f"{family} daddr {addr} accept comment \"allowed\""]
        # Accept only the specified destination ports.
        lines: list[str] = []
        for port in allowed_ports:
            lines.append(
                f"{family} daddr {addr} tcp dport {port} accept"
                f" comment \"allowed:{port}/tcp\""
            )
            lines.append(
                f"{family} daddr {addr} udp dport {port} accept"
                f" comment \"allowed:{port}/udp\""
            )
        return lines
