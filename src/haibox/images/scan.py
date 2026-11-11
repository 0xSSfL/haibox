"""Optional host-side vulnerability scanner adapters.

Scanning is deliberately not part of the image build. A missing scanner is a
clear, actionable error rather than a silent pass.

Trivy is preferred because the catalog images and their scoped ignore files are
Trivy-native. Trivy does not scan every distribution: it reports Fedora as
unsupported and does not detect Arch Linux as an OS. When the Trivy report does
not cover OS packages, the adapter falls back to Grype, which supports both. If
no available scanner can cover the image OS, the scan fails instead of treating
an empty report as clean.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from haibox.errors import ImageError
from haibox.runtime.process import CommandRunner, ProcessResult, SubprocessRunner

_HIGH_SEVERITIES = {"HIGH", "CRITICAL"}


@dataclass(frozen=True)
class ScanResult:
    tool: str
    exit_code: int
    output: str
    covered: bool = True
    findings: int = 0

    @property
    def ok(self) -> bool:
        """A scan passes only when it covered the image and found nothing."""
        return self.exit_code == 0 and self.covered and self.findings == 0


class ImageScanner:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or SubprocessRunner()

    def detect(self) -> str | None:
        tools = self._available_tools()
        return tools[0] if tools else None

    def _available_tools(self) -> list[str]:
        return [tool for tool in ("trivy", "grype") if self.runner.which(tool)]

    def scan(
        self,
        image: str,
        *,
        timeout: int = 1800,
        ignorefile: Path | None = None,
    ) -> ScanResult:
        tools = self._available_tools()
        if not tools:
            raise ImageError(
                "no image scanner found; install trivy or grype on the Docker host"
            )

        if "trivy" in tools:
            trivy = self._scan_trivy(image, timeout=timeout, ignorefile=ignorefile)
            if trivy.covered:
                return trivy
            if "grype" in tools:
                grype = self._scan_grype(image, timeout=timeout)
                if grype.covered:
                    # Trivy still scans language packages and files for secrets
                    # when it cannot scan OS packages. Keep those findings so
                    # the fallback cannot hide what Trivy already reported.
                    findings = grype.findings + trivy.findings
                    output = f"{trivy.output}\n{grype.output}".strip()
                    if trivy.findings:
                        output += (
                            f"\ntrivy: {trivy.findings} HIGH/CRITICAL finding(s) "
                            "outside OS coverage are included."
                        )
                    return ScanResult(
                        tool="grype",
                        exit_code=1 if findings else 0,
                        output=output,
                        covered=True,
                        findings=findings,
                    )
                return self._combined_uncovered(trivy, grype)
            return trivy

        return self._scan_grype(image, timeout=timeout)

    # ------------------------------------------------------------------ trivy
    def _scan_trivy(
        self,
        image: str,
        *,
        timeout: int,
        ignorefile: Path | None,
    ) -> ScanResult:
        args = [
            "trivy",
            "image",
            # --quiet would hide the "Unsupported os" warning used below.
            "--severity",
            "HIGH,CRITICAL",
            "--format",
            "json",
            "--exit-code",
            "1",
        ]
        if ignorefile is not None:
            if not ignorefile.is_file():
                raise ImageError(f"scan ignore file not found: {ignorefile}")
            args.extend(["--ignorefile", str(ignorefile)])
        args.append(image)

        process = self.runner.run(args, timeout=timeout)
        report = self._parse_json(process)
        if report is None:
            return ScanResult(
                tool="trivy",
                exit_code=process.returncode or 1,
                output=self._process_error("trivy", process),
                covered=False,
            )

        covered = _trivy_covered(report, process.stderr)
        findings = _trivy_findings(report)
        output = _trivy_summary(report, covered, findings)
        if process.returncode not in (0, 1):
            covered = False
            output = f"{self._process_error('trivy', process)}\n{output}".strip()
        return ScanResult(
            tool="trivy",
            exit_code=1 if not covered or findings else 0,
            output=output,
            covered=covered,
            findings=findings,
        )

    # ------------------------------------------------------------------ grype
    def _scan_grype(self, image: str, *, timeout: int) -> ScanResult:
        args = ["grype", image, "--output", "json", "--fail-on", "high"]
        process = self.runner.run(args, timeout=timeout)
        report = self._parse_json(process)
        if report is None:
            return ScanResult(
                tool="grype",
                exit_code=process.returncode or 1,
                output=self._process_error("grype", process),
                covered=False,
            )

        covered = _grype_covered(report)
        findings = _grype_findings(report)
        output = _grype_summary(report, covered, findings)
        # Grype exits 2 when --fail-on matches a vulnerability and 1 on an
        # operational error. Exit 2 with no parsed finding is still a failure.
        if process.returncode not in (0, 2) or (process.returncode == 2 and not findings):
            covered = False
            output = f"{self._process_error('grype', process)}\n{output}".strip()
        return ScanResult(
            tool="grype",
            exit_code=1 if not covered or findings else 0,
            output=output,
            covered=covered,
            findings=findings,
        )

    @staticmethod
    def _parse_json(process: ProcessResult) -> dict[str, Any] | None:
        text = process.stdout.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    @staticmethod
    def _process_error(tool: str, process: ProcessResult) -> str:
        detail = (process.stderr or process.stdout).strip()
        message = f"{tool}: scanner failed (exit {process.returncode})"
        return f"{message}\n{detail}" if detail else message

    @staticmethod
    def _combined_uncovered(left: ScanResult, right: ScanResult) -> ScanResult:
        return ScanResult(
            tool=f"{left.tool}+{right.tool}",
            exit_code=1,
            output=f"{left.output}\n{right.output}".strip(),
            covered=False,
        )


def _os_label(info: Any, name_key: str, version_key: str) -> str:
    if not isinstance(info, dict):
        return "unknown OS"
    name = str(info.get(name_key, "")).strip()
    version = str(info.get(version_key, "")).strip()
    return f"{name} {version}".strip() or "unknown OS"


def _trivy_covered(report: dict[str, Any], stderr: str) -> bool:
    metadata = report.get("Metadata")
    os_info = metadata.get("OS") if isinstance(metadata, dict) else None
    if not isinstance(os_info, dict) or not os_info.get("Family"):
        return False
    # Trivy detects some distributions (Fedora) but cannot scan them. It
    # reports that on stderr and still exits 0 with an empty result set.
    return "unsupported os" not in stderr.lower()


def _trivy_findings(report: dict[str, Any]) -> int:
    count = 0
    for result in report.get("Results") or []:
        if not isinstance(result, dict):
            continue
        for vuln in result.get("Vulnerabilities") or []:
            if (
                isinstance(vuln, dict)
                and str(vuln.get("Severity", "")).upper() in _HIGH_SEVERITIES
            ):
                count += 1
        for secret in result.get("Secrets") or []:
            if (
                isinstance(secret, dict)
                and str(secret.get("Severity", "")).upper() in _HIGH_SEVERITIES
            ):
                count += 1
    return count


def _trivy_summary(report: dict[str, Any], covered: bool, findings: int) -> str:
    metadata = report.get("Metadata")
    os_info = metadata.get("OS") if isinstance(metadata, dict) else None
    if not covered:
        label = _os_label(os_info, "Family", "Name")
        lines = [
            f"trivy: OS packages were not scanned ({label}).",
            "  Trivy does not support this image OS; use a scanner that does.",
        ]
        if findings:
            lines.append(
                f"  {findings} HIGH/CRITICAL non-OS finding(s) were still reported."
            )
        return "\n".join(lines)

    lines = [f"trivy: {_os_label(os_info, 'Family', 'Name')}"]
    lines.append(f"HIGH/CRITICAL: {findings}")
    if not findings:
        lines.append("  No HIGH/CRITICAL findings.")
        return "\n".join(lines)

    finding_lines: list[str] = []
    for result in report.get("Results") or []:
        if not isinstance(result, dict):
            continue
        for vuln in result.get("Vulnerabilities") or []:
            if not isinstance(vuln, dict):
                continue
            severity = str(vuln.get("Severity", "")).upper()
            if severity not in _HIGH_SEVERITIES:
                continue
            vuln_id = vuln.get("VulnerabilityID", "?")
            package = vuln.get("PkgName", "?")
            installed = vuln.get("InstalledVersion", "?")
            fixed = vuln.get("FixedVersion") or "no fix"
            finding_lines.append(
                f"  {severity:<8} {vuln_id}  {package} {installed} -> {fixed}"
            )
        for secret in result.get("Secrets") or []:
            if not isinstance(secret, dict):
                continue
            severity = str(secret.get("Severity", "")).upper()
            if severity not in _HIGH_SEVERITIES:
                continue
            rule = secret.get("RuleID", "?")
            title = secret.get("Title", "secret")
            target = result.get("Target", "?")
            finding_lines.append(
                f"  {severity:<8} secret:{rule}  {title}  ({target})"
            )
    lines.extend(sorted(finding_lines))
    return "\n".join(lines)


def _grype_distro(report: dict[str, Any]) -> dict[str, Any]:
    distro = report.get("distro")
    if isinstance(distro, dict):
        return distro
    source = report.get("source")
    if isinstance(source, dict):
        candidate = source.get("distro")
        if isinstance(candidate, dict):
            return candidate
    return {}


def _grype_covered(report: dict[str, Any]) -> bool:
    distro = _grype_distro(report)
    name = str(distro.get("name", "")).strip()
    if not name or name.lower() == "unknown":
        return False

    descriptor = report.get("descriptor")
    if isinstance(descriptor, dict):
        db = descriptor.get("db")
        if isinstance(db, dict):
            status = db.get("status")
            if isinstance(status, dict) and status.get("valid") is False:
                return False
    return True


def _grype_findings(report: dict[str, Any]) -> int:
    count = 0
    for match in report.get("matches") or []:
        if not isinstance(match, dict):
            continue
        vuln = match.get("vulnerability")
        if (
            isinstance(vuln, dict)
            and str(vuln.get("severity", "")).upper() in _HIGH_SEVERITIES
        ):
            count += 1
    return count


def _grype_summary(report: dict[str, Any], covered: bool, findings: int) -> str:
    distro = _grype_distro(report)
    if not covered:
        return (
            "grype: OS packages were not scanned "
            f"({_os_label(distro, 'name', 'version')}).\n"
            "  Grype could not identify a supported image OS."
        )

    lines = [f"grype: {_os_label(distro, 'name', 'version')}"]
    lines.append(f"HIGH/CRITICAL: {findings}")
    if not findings:
        lines.append("  No HIGH/CRITICAL findings.")
        return "\n".join(lines)

    finding_lines: list[str] = []
    for match in report.get("matches") or []:
        if not isinstance(match, dict):
            continue
        vuln = match.get("vulnerability")
        if not isinstance(vuln, dict):
            continue
        severity = str(vuln.get("severity", "")).upper()
        if severity not in _HIGH_SEVERITIES:
            continue
        artifact = match.get("artifact")
        artifact = artifact if isinstance(artifact, dict) else {}
        vuln_id = vuln.get("id", "?")
        package = artifact.get("name", "?")
        installed = artifact.get("version", "?")
        fix = vuln.get("fix")
        versions = fix.get("versions") if isinstance(fix, dict) else None
        fixed = ", ".join(str(item) for item in versions) if versions else "no fix"
        finding_lines.append(
            f"  {severity:<8} {vuln_id}  {package} {installed} -> {fixed}"
        )
    lines.extend(sorted(finding_lines))
    return "\n".join(lines)
