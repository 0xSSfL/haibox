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
    error: str | None = None

    @property
    def ok(self) -> bool:
        """A scan passes only when it covered the image and found nothing."""
        return (
            self.exit_code == 0
            and self.covered
            and self.findings == 0
            and self.error is None
        )


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
            if trivy.covered and trivy.error is None:
                return trivy
            if "grype" in tools:
                grype = self._scan_grype(image, timeout=timeout)
                if grype.covered and grype.error is None:
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
                    # A Trivy operational or inconsistent result is not cleared
                    # by a clean Grype report.
                    return ScanResult(
                        tool="grype",
                        exit_code=1 if findings or trivy.error else 0,
                        output=output,
                        covered=True,
                        findings=findings,
                        error=trivy.error,
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
            "--list-all-pkgs",
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
                output=self._process_error("trivy", process, include_stdout=True),
                covered=False,
                error=f"trivy produced no parseable JSON report (exit {process.returncode})",
            )

        coverage_problem = _trivy_coverage_problem(report, process.stderr)
        findings = _trivy_findings(report)
        exit_problem = _trivy_exit_problem(process.returncode, findings)
        covered = coverage_problem is None and exit_problem is None
        output = _trivy_summary(
            report, coverage_problem, exit_problem, findings
        )
        if exit_problem:
            output = f"{self._process_error('trivy', process)}\n{output}".strip()
        return ScanResult(
            tool="trivy",
            exit_code=1 if coverage_problem or exit_problem or findings else 0,
            output=output,
            covered=covered,
            findings=findings,
            error=exit_problem,
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
                output=self._process_error("grype", process, include_stdout=True),
                covered=False,
                error=f"grype produced no parseable JSON report (exit {process.returncode})",
            )

        coverage_problem = _grype_coverage_problem(report)
        findings = _grype_findings(report)
        exit_problem = _grype_exit_problem(process.returncode, findings)
        covered = coverage_problem is None and exit_problem is None
        output = _grype_summary(
            report, coverage_problem, exit_problem, findings
        )
        if exit_problem:
            output = f"{self._process_error('grype', process)}\n{output}".strip()
        return ScanResult(
            tool="grype",
            exit_code=1 if coverage_problem or exit_problem or findings else 0,
            output=output,
            covered=covered,
            findings=findings,
            error=exit_problem,
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
    def _process_error(
        tool: str,
        process: ProcessResult,
        *,
        include_stdout: bool = False,
    ) -> str:
        detail = process.stderr.strip()
        if include_stdout and not detail:
            detail = process.stdout.strip()
        message = f"{tool}: scanner failed (exit {process.returncode})"
        return f"{message}\n{detail}" if detail else message

    @staticmethod
    def _combined_uncovered(left: ScanResult, right: ScanResult) -> ScanResult:
        errors = [error for error in (left.error, right.error) if error]
        return ScanResult(
            tool=f"{left.tool}+{right.tool}",
            exit_code=1,
            output=f"{left.output}\n{right.output}".strip(),
            covered=False,
            findings=left.findings + right.findings,
            error="; ".join(errors) or None,
        )


def _os_label(info: Any, name_key: str, version_key: str) -> str:
    if not isinstance(info, dict):
        return "unknown OS"
    name = str(info.get(name_key, "")).strip()
    version = str(info.get(version_key, "")).strip()
    return f"{name} {version}".strip() or "unknown OS"


def _trivy_coverage_problem(report: dict[str, Any], stderr: str) -> str | None:
    """Return why the Trivy report does not prove OS package coverage."""
    if "unsupported os" in stderr.lower():
        return "Trivy reported the image OS as unsupported"

    metadata = report.get("Metadata")
    os_info = metadata.get("OS") if isinstance(metadata, dict) else None
    if not isinstance(os_info, dict):
        return "the report has no OS metadata"
    family = str(os_info.get("Family") or "").strip()
    version = str(os_info.get("Name") or "").strip()
    if not family or not version:
        return "the report has an incomplete OS identity"

    results = report.get("Results")
    if not isinstance(results, list):
        return "the report has no Results list"

    os_results = [
        result
        for result in results
        if isinstance(result, dict) and result.get("Class") == "os-pkgs"
    ]
    if not os_results:
        # An empty report is not proof that the image is package-free.
        return (
            "the report has no os-pkgs result; a package-free image must be "
            "verified separately"
        )

    for result in os_results:
        package_type = str(result.get("Type") or "").strip()
        if not package_type:
            return "an os-pkgs result has no package manager type"
        packages = result.get("Packages")
        if not isinstance(packages, list) or not packages:
            return "an os-pkgs result has no package inventory"
        if not any(
            isinstance(package, dict) and str(package.get("Name") or "").strip()
            for package in packages
        ):
            return "the OS package inventory is malformed"
    return None


def _trivy_exit_problem(returncode: int, findings: int) -> str | None:
    """Reject exit codes that contradict the report contents."""
    if returncode not in (0, 1):
        return f"Trivy exited {returncode} instead of 0 or 1"
    if returncode == 1 and findings == 0:
        return "Trivy exited 1 but reported no HIGH/CRITICAL findings"
    if returncode == 0 and findings > 0:
        return "Trivy exited 0 but reported HIGH/CRITICAL findings"
    return None


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


def _trivy_summary(
    report: dict[str, Any],
    coverage_problem: str | None,
    exit_problem: str | None,
    findings: int,
) -> str:
    metadata = report.get("Metadata")
    os_info = metadata.get("OS") if isinstance(metadata, dict) else None
    label = _os_label(os_info, "Family", "Name")
    if coverage_problem:
        lines = [
            f"trivy: OS packages were not scanned ({label}).",
            f"  {coverage_problem}.",
        ]
        if findings:
            lines.append(
                f"  {findings} HIGH/CRITICAL non-OS finding(s) were still reported."
            )
        return "\n".join(lines)

    lines = [f"trivy: {label}"]
    if exit_problem:
        lines.append(f"trivy: {exit_problem}.")
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


def _grype_coverage_problem(report: dict[str, Any]) -> str | None:
    """Return why the Grype report does not prove package coverage.

    Grype's JSON document does not list every scanned package. Coverage is
    accepted only from a complete image target inventory (identity, layers, and
    size), an identified distro and version, a valid vulnerability database,
    and structurally complete match records. Anything less fails closed.
    """
    matches = report.get("matches")
    if not isinstance(matches, list):
        return "the report has no matches list"

    source = report.get("source")
    if not isinstance(source, dict) or source.get("type") != "image":
        return "the report is not an image scan"
    target = source.get("target")
    if not isinstance(target, dict):
        return "the report has no image target inventory"
    image_id = str(target.get("imageID") or "").strip()
    manifest_digest = str(target.get("manifestDigest") or "").strip()
    if not image_id and not manifest_digest:
        return "the image target has no identity"
    layers = target.get("layers")
    if not isinstance(layers, list) or not layers:
        return "the image target has no layer inventory"
    if not any(
        isinstance(layer, dict)
        and (layer.get("digest") or layer.get("mediaType"))
        for layer in layers
    ):
        return "the image layer inventory is malformed"
    image_size = target.get("imageSize")
    if not isinstance(image_size, int) or image_size <= 0:
        return "the image target has no content size"

    distro = report.get("distro")
    if not isinstance(distro, dict):
        return "the report has no distro"
    name = str(distro.get("name") or "").strip()
    version = str(distro.get("version") or "").strip()
    if not name or name.lower() == "unknown":
        return "the report has no identified distro"
    if not version:
        return "the report has no distro version"

    descriptor = report.get("descriptor")
    if not isinstance(descriptor, dict):
        return "the report has no descriptor"
    db = descriptor.get("db")
    if not isinstance(db, dict):
        return "the report has no vulnerability database"
    if db.get("error"):
        return "the vulnerability database reported an error"
    status = db.get("status")
    if not isinstance(status, dict):
        return "the vulnerability database has no status"
    if status.get("error"):
        return "the vulnerability database status reported an error"
    if status.get("valid") is not True:
        return "the vulnerability database is not valid"

    for match in matches:
        if not isinstance(match, dict):
            return "a match is not an object"
        vulnerability = match.get("vulnerability")
        if not isinstance(vulnerability, dict):
            return "a match has no vulnerability"
        if not str(vulnerability.get("id") or "").strip():
            return "a match has no vulnerability id"
        if not str(vulnerability.get("severity") or "").strip():
            return "a match has no severity"
        artifact = match.get("artifact")
        if not isinstance(artifact, dict):
            return "a match has no package artifact"
        if not str(artifact.get("name") or "").strip():
            return "a match artifact has no name"
        if not str(artifact.get("version") or "").strip():
            return "a match artifact has no version"
        if not str(artifact.get("type") or "").strip():
            return "a match artifact has no package type"
    return None


def _grype_exit_problem(returncode: int, findings: int) -> str | None:
    """Reject exit codes that contradict the report contents."""
    if returncode not in (0, 2):
        return f"Grype exited {returncode} instead of 0 or 2"
    if returncode == 2 and findings == 0:
        return "Grype exited 2 but reported no HIGH/CRITICAL findings"
    if returncode == 0 and findings > 0:
        return "Grype exited 0 but reported HIGH/CRITICAL findings"
    return None


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


def _grype_summary(
    report: dict[str, Any],
    coverage_problem: str | None,
    exit_problem: str | None,
    findings: int,
) -> str:
    distro = _grype_distro(report)
    label = _os_label(distro, "name", "version")
    if coverage_problem:
        lines = [
            f"grype: OS packages were not scanned ({label}).",
            f"  {coverage_problem}.",
        ]
        if findings:
            lines.append(
                f"  {findings} HIGH/CRITICAL non-OS finding(s) were still reported."
            )
        return "\n".join(lines)

    lines = [f"grype: {label}"]
    if exit_problem:
        lines.append(f"grype: {exit_problem}.")
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
