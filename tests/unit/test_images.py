"""Image catalog, manifest, builder, verifier, and scanner tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from haibox.errors import ImageError
from haibox.images.builder import ImageBuilder, tools_digest
from haibox.images.catalog import ImageCatalog, default_images_root
from haibox.images.scan import ImageScanner, ScanResult
from haibox.images.verify import ImageVerifier, verification_script
from haibox.models import ImageManifest, ImageTool
from haibox.runtime.base import ExecResult
from haibox.runtime.process import ProcessResult
from tests.fakes import FakeRuntime, ScriptedRunner


def _manifest(**overrides: object) -> ImageManifest:
    values: dict[str, object] = {
        "name": "test-image",
        "version": "0.1.0",
        "base": "debian:12-slim",
        "tools": [ImageTool(name="ffuf", version="v2.3.0", verify="ffuf -V")],
    }
    values.update(overrides)
    return ImageManifest(**values)  # type: ignore[arg-type]


def test_web_security_manifest_is_valid() -> None:
    catalog = ImageCatalog()
    manifest = catalog.load("web-security")
    assert manifest.name == "web-security"
    assert manifest.version == "0.1.0"
    assert manifest.status == "active"
    assert "@sha256:" in manifest.base
    assert manifest.image_ref == "haibox/web-security:0.1.0"
    assert catalog.dockerfile_path(manifest).is_file()
    assert catalog.context_path(manifest).is_dir()
    assert len({tool.name for tool in manifest.tools}) == len(manifest.tools)


def test_catalog_lists_images() -> None:
    manifests = ImageCatalog().list()
    assert set(manifests) == {
        "ad-security",
        "core",
        "full",
        "network-security",
        "osint",
        "web-security",
    }
    assert manifests["network-security"].depends_on == ["core"]
    assert manifests["full"].depends_on == [
        "core",
        "network-security",
        "web-security",
        "ad-security",
        "osint",
    ]


def test_catalog_rejects_missing_and_invalid_names(tmp_path: Path) -> None:
    catalog = ImageCatalog(tmp_path)
    with pytest.raises(ImageError):
        catalog.load("missing")
    with pytest.raises(ImageError):
        catalog.load("../escape")


def test_catalog_rejects_a_name_mismatch(tmp_path: Path) -> None:
    directory = tmp_path / "foo"
    directory.mkdir()
    (directory / "manifest.yaml").write_text(
        "api_version: haibox/v1\nname: bar\nversion: 0.1.0\nbase: debian:12-slim\n",
        encoding="utf-8",
    )
    with pytest.raises(ImageError):
        ImageCatalog(tmp_path).load("foo")


def test_catalog_rejects_invalid_yaml(tmp_path: Path) -> None:
    directory = tmp_path / "foo"
    directory.mkdir()
    (directory / "manifest.yaml").write_text("name: [\n", encoding="utf-8")
    with pytest.raises(ImageError):
        ImageCatalog(tmp_path).load("foo")


def test_manifest_rejects_escaping_paths() -> None:
    with pytest.raises(ValueError):
        _manifest(dockerfile="../Dockerfile")
    with pytest.raises(ValueError):
        _manifest(context="/tmp")
    with pytest.raises(ValueError):
        _manifest(base="-bad")


def test_manifest_rejects_duplicate_tools() -> None:
    with pytest.raises(ValueError):
        _manifest(
            tools=[
                ImageTool(name="ffuf", version="v1", verify="ffuf -V"),
                ImageTool(name="ffuf", version="v2", verify="ffuf -V"),
            ]
        )


def test_manifest_rejects_self_dependency() -> None:
    with pytest.raises(ValueError):
        _manifest(depends_on=["test-image"])


def test_manifest_rejects_invalid_dependency_names() -> None:
    with pytest.raises(ValueError):
        _manifest(depends_on=["../escape"])
    with pytest.raises(ValueError):
        _manifest(depends_on=["core", "core"])


def test_tools_digest_is_stable_and_version_sensitive() -> None:
    first = _manifest()
    second = _manifest()
    changed = _manifest(
        tools=[ImageTool(name="ffuf", version="v9.9.9", verify="ffuf -V")]
    )
    assert tools_digest(first) == tools_digest(second)
    assert tools_digest(first) != tools_digest(changed)


def test_builder_passes_the_manifest_to_the_runtime() -> None:
    catalog = ImageCatalog()
    manifest = catalog.load("web-security")
    runtime = FakeRuntime()
    output = ImageBuilder(catalog, runtime).build(
        manifest, no_cache=True, platform="linux/amd64"
    )
    assert output == runtime.build_output
    call = runtime.called("build_image")[0]
    assert call[0] == "haibox/web-security:0.1.0"
    assert call[1].endswith("Dockerfile")
    assert call[2].endswith("web-security")
    assert call[3] == "linux/amd64"
    assert call[4] is True
    assert call[5]["haibox.image.name"] == "web-security"
    assert call[5]["haibox.image.tools-sha256"] == tools_digest(manifest)
    assert call[6]["DEBIAN_SNAPSHOT"] == manifest.build_args["DEBIAN_SNAPSHOT"]


def test_builder_builds_dependencies_first() -> None:
    catalog = ImageCatalog()
    manifest = catalog.load("network-security")
    runtime = FakeRuntime()
    output = ImageBuilder(catalog, runtime).build(manifest)
    assert output == f"{runtime.build_output}\n{runtime.build_output}"
    tags = [call[0] for call in runtime.called("build_image")]
    assert tags == ["haibox/core:0.1.0", "haibox/network-security:0.1.0"]


def test_builder_can_reuse_existing_dependencies() -> None:
    catalog = ImageCatalog()
    manifest = catalog.load("network-security")
    runtime = FakeRuntime()
    ImageBuilder(catalog, runtime).build(manifest, reuse_existing=True)
    tags = [call[0] for call in runtime.called("build_image")]
    assert tags == ["haibox/network-security:0.1.0"]
    assert runtime.called("image_exists") == [("haibox/core:0.1.0",)]


def test_builder_rejects_dependency_cycles(tmp_path: Path) -> None:
    for name, dependency in (("alpha", "beta"), ("beta", "alpha")):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "Dockerfile").write_text("FROM scratch\n", encoding="utf-8")
        (directory / "manifest.yaml").write_text(
            "\n".join(
                [
                    "api_version: haibox/v1",
                    f"name: {name}",
                    "version: 0.1.0",
                    "base: scratch",
                    f"depends_on: [{dependency}]",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
    catalog = ImageCatalog(tmp_path)
    with pytest.raises(ImageError, match="cycle"):
        ImageBuilder(catalog, FakeRuntime()).build(catalog.load("alpha"))


def test_verifier_runs_the_manifest_commands() -> None:
    catalog = ImageCatalog()
    manifest = catalog.load("web-security")
    runtime = FakeRuntime()
    runtime.ephemeral_result = ExecResult(exit_code=0, stdout="verified\n", stderr="")
    output = ImageVerifier(catalog, runtime).verify(manifest)
    assert output == "verified\n"
    call = runtime.called("run_ephemeral")[0]
    assert call[0] == "haibox/web-security:0.1.0"
    script = call[1][1]
    assert "id -u" in script
    assert "/opt/nuclei-templates" in script
    assert "ffuf -V" in script
    assert call[3] == "none"
    assert call[4] == "65534:65534"
    assert call[6] == "/bin/sh"


def test_verifier_reports_failure() -> None:
    catalog = ImageCatalog()
    manifest = catalog.load("web-security")
    runtime = FakeRuntime()
    runtime.ephemeral_result = ExecResult(exit_code=1, stdout="", stderr="missing tool")
    with pytest.raises(ImageError) as excinfo:
        ImageVerifier(catalog, runtime).verify(manifest)
    assert "missing tool" in str(excinfo.value)


def test_verification_script_only_checks_templates_when_present() -> None:
    script = verification_script(_manifest())
    assert "/opt/nuclei-templates" not in script
    assert "ffuf -V" in script


def _process(
    stdout: str = "",
    *,
    returncode: int = 0,
    stderr: str = "",
) -> ProcessResult:
    return ProcessResult(
        args=(), returncode=returncode, stdout=stdout, stderr=stderr
    )


def _trivy_report(
    *,
    family: str | None = "debian",
    version: str = "13.7",
    vulnerabilities: list[dict[str, Any]] | None = None,
    secrets: list[dict[str, Any]] | None = None,
) -> str:
    metadata: dict[str, Any] = {}
    if family is not None:
        metadata["OS"] = {"Family": family, "Name": version}
    results: list[dict[str, Any]] = []
    if family is not None:
        result: dict[str, Any] = {
            "Target": "image (os)",
            "Class": "os-pkgs",
            "Type": family,
        }
        if vulnerabilities:
            result["Vulnerabilities"] = vulnerabilities
        if secrets:
            result["Secrets"] = secrets
        results.append(result)
    return json.dumps({"Metadata": metadata, "Results": results})


def _grype_report(
    *,
    distro: str = "fedora",
    version: str = "44",
    matches: list[dict[str, Any]] | None = None,
    db_valid: bool = True,
) -> str:
    return json.dumps(
        {
            "distro": {"name": distro, "version": version, "idLike": []},
            "matches": matches or [],
            "descriptor": {"db": {"status": {"valid": db_valid}}},
        }
    )


def _vuln(vuln_id: str = "CVE-2024-0001", severity: str = "HIGH") -> dict[str, Any]:
    return {
        "VulnerabilityID": vuln_id,
        "PkgName": "libc",
        "InstalledVersion": "1.0",
        "FixedVersion": "1.1",
        "Severity": severity,
    }


def _match(
    vuln_id: str = "CVE-2024-0001", severity: str = "High"
) -> dict[str, Any]:
    return {
        "vulnerability": {
            "id": vuln_id,
            "severity": severity,
            "fix": {"versions": ["1.1"], "state": "fixed"},
        },
        "artifact": {"name": "libc", "version": "1.0", "type": "rpm"},
    }


class _ToolRunner(ScriptedRunner):
    """ScriptedRunner whose installed tools are explicit."""

    def __init__(self, handler, tools: set[str]) -> None:
        super().__init__(handler)
        self.tools = tools

    def which(self, program: str) -> str | None:
        return f"/usr/bin/{program}" if program in self.tools else None


def test_scanner_detects_trivy() -> None:
    runner = _ToolRunner(
        lambda args, kwargs: _process(_trivy_report()), {"trivy", "grype"}
    )
    scanner = ImageScanner(runner)
    assert scanner.detect() == "trivy"
    result = scanner.scan("haibox/web-security:0.1.0")
    assert result.tool == "trivy"
    assert result.covered
    assert result.findings == 0
    assert result.ok
    args = runner.calls[0]
    assert args[:2] == ["trivy", "image"]
    assert args[-1] == "haibox/web-security:0.1.0"
    assert "--exit-code" in args


def test_scanner_passes_a_scoped_ignore_file(tmp_path: Path) -> None:
    ignorefile = tmp_path / "trivyignore.yaml"
    ignorefile.write_text("secrets: []\n", encoding="utf-8")
    runner = _ToolRunner(lambda args, kwargs: _process(_trivy_report()), {"trivy"})
    result = ImageScanner(runner).scan("image", ignorefile=ignorefile)
    assert result.ok
    args = runner.calls[0]
    assert args[args.index("--ignorefile") + 1] == str(ignorefile)
    assert args[-1] == "image"


def test_scanner_rejects_a_missing_ignore_file(tmp_path: Path) -> None:
    scanner = ImageScanner(
        _ToolRunner(lambda args, kwargs: _process(_trivy_report()), {"trivy"})
    )
    with pytest.raises(ImageError):
        scanner.scan("image", ignorefile=tmp_path / "missing.yaml")


def test_web_security_scan_suppressions_are_scoped() -> None:
    catalog = ImageCatalog()
    ignorefile = catalog.scan_ignorefile(catalog.load("web-security"))
    assert ignorefile is not None
    assert ignorefile.name == "trivyignore.yaml"
    policy = yaml.safe_load(ignorefile.read_text(encoding="utf-8"))
    entries = policy["secrets"]
    assert entries
    for entry in entries:
        assert entry["statement"]
        assert entry["paths"]
        assert all(
            path.startswith("/opt/nuclei-templates/") for path in entry["paths"]
        )


def test_scanner_detects_grype() -> None:
    runner = _ToolRunner(
        lambda args, kwargs: _process(_grype_report()), {"grype"}
    )
    scanner = ImageScanner(runner)
    assert scanner.detect() == "grype"
    result = scanner.scan("image")
    assert result.tool == "grype"
    assert result.covered
    assert result.ok
    assert runner.calls[0][:2] == ["grype", "image"]
    assert "--fail-on" in runner.calls[0]


def test_scanner_missing_is_an_error() -> None:
    scanner = ImageScanner(_ToolRunner(lambda args, kwargs: _process(), set()))
    assert scanner.detect() is None
    with pytest.raises(ImageError):
        scanner.scan("image")


def test_scanner_findings_are_not_ok() -> None:
    report = _trivy_report(vulnerabilities=[_vuln()])
    runner = _ToolRunner(lambda args, kwargs: _process(report, returncode=1), {"trivy"})
    scanner = ImageScanner(runner)
    result = scanner.scan("image")
    assert result.covered
    assert result.findings == 1
    assert not result.ok
    assert "CVE-2024-0001" in result.output


def test_scanner_counts_high_and_critical_trivy_secrets() -> None:
    report = _trivy_report(
        secrets=[{"RuleID": "private-key", "Severity": "CRITICAL", "Title": "key"}]
    )
    runner = _ToolRunner(lambda args, kwargs: _process(report, returncode=1), {"trivy"})
    result = ImageScanner(runner).scan("image")
    assert result.findings == 1
    assert "private-key" in result.output
    assert not result.ok


def test_scanner_ignores_medium_trivy_findings() -> None:
    report = _trivy_report(vulnerabilities=[_vuln(severity="MEDIUM")])
    runner = _ToolRunner(lambda args, kwargs: _process(report), {"trivy"})
    result = ImageScanner(runner).scan("image")
    assert result.findings == 0
    assert result.ok


def test_scanner_rejects_a_trivy_report_without_an_os() -> None:
    report = _trivy_report(family=None)
    runner = _ToolRunner(lambda args, kwargs: _process(report), {"trivy"})
    result = ImageScanner(runner).scan("image")
    assert not result.covered
    assert not result.ok


def test_scanner_rejects_an_unsupported_trivy_os() -> None:
    report = _trivy_report(family="fedora", version="44")
    runner = _ToolRunner(
        lambda args, kwargs: _process(
            report, stderr='WARN Unsupported os family="fedora"'
        ),
        {"trivy"},
    )
    result = ImageScanner(runner).scan("image")
    assert not result.covered
    assert not result.ok
    assert "not scanned" in result.output


def test_scanner_rejects_unparseable_scanner_output() -> None:
    runner = _ToolRunner(
        lambda args, kwargs: _process("not json", returncode=2), {"trivy"}
    )
    result = ImageScanner(runner).scan("image")
    assert not result.covered
    assert not result.ok


def test_scanner_falls_back_to_grype_when_trivy_is_unsupported() -> None:
    def handler(args: list[str], kwargs: dict[str, Any]) -> ProcessResult:
        if args[0] == "trivy":
            return _process(
                _trivy_report(family="fedora", version="44"),
                stderr='WARN Unsupported os family="fedora"',
            )
        return _process(_grype_report())

    runner = _ToolRunner(handler, {"trivy", "grype"})
    result = ImageScanner(runner).scan("image")
    assert result.tool == "grype"
    assert result.covered
    assert result.ok
    assert [call[0] for call in runner.calls] == ["trivy", "grype"]


def test_scanner_fallback_reports_grype_findings() -> None:
    def handler(args: list[str], kwargs: dict[str, Any]) -> ProcessResult:
        if args[0] == "trivy":
            return _process(
                _trivy_report(family="fedora", version="44"),
                stderr='WARN Unsupported os family="fedora"',
            )
        return _process(_grype_report(matches=[_match()]), returncode=2)

    runner = _ToolRunner(handler, {"trivy", "grype"})
    result = ImageScanner(runner).scan("image")
    assert result.tool == "grype"
    assert result.covered
    assert result.findings == 1
    assert not result.ok


def test_scanner_fallback_keeps_trivy_findings_outside_os_coverage() -> None:
    def handler(args: list[str], kwargs: dict[str, Any]) -> ProcessResult:
        if args[0] == "trivy":
            return _process(
                _trivy_report(
                    family="fedora",
                    version="44",
                    secrets=[
                        {
                            "RuleID": "private-key",
                            "Severity": "CRITICAL",
                            "Title": "key",
                        }
                    ],
                ),
                returncode=1,
                stderr='WARN Unsupported os family="fedora"',
            )
        return _process(_grype_report())

    runner = _ToolRunner(handler, {"trivy", "grype"})
    result = ImageScanner(runner).scan("image")
    assert result.tool == "grype"
    assert result.covered
    assert result.findings == 1
    assert not result.ok
    assert "outside OS coverage" in result.output


def test_scanner_fails_when_no_scanner_covers_the_os() -> None:
    def handler(args: list[str], kwargs: dict[str, Any]) -> ProcessResult:
        if args[0] == "trivy":
            return _process(
                _trivy_report(family="fedora", version="44"),
                stderr='WARN Unsupported os family="fedora"',
            )
        return _process(_grype_report(distro=""))

    runner = _ToolRunner(handler, {"trivy", "grype"})
    result = ImageScanner(runner).scan("image")
    assert result.tool == "trivy+grype"
    assert not result.covered
    assert not result.ok


def test_scanner_rejects_a_grype_report_without_a_distro() -> None:
    runner = _ToolRunner(
        lambda args, kwargs: _process(_grype_report(distro="", version="")),
        {"grype"},
    )
    result = ImageScanner(runner).scan("image")
    assert not result.covered
    assert not result.ok


def test_scanner_rejects_an_invalid_grype_database() -> None:
    runner = _ToolRunner(
        lambda args, kwargs: _process(_grype_report(db_valid=False)), {"grype"}
    )
    result = ImageScanner(runner).scan("image")
    assert not result.covered
    assert not result.ok


def test_scanner_counts_high_and_critical_grype_matches() -> None:
    report = _grype_report(
        matches=[_match(), _match(vuln_id="CVE-2024-0002", severity="Critical")]
    )
    runner = _ToolRunner(lambda args, kwargs: _process(report, returncode=2), {"grype"})
    result = ImageScanner(runner).scan("image")
    assert result.findings == 2
    assert result.covered
    assert not result.ok


def test_scanner_rejects_grype_exit_two_without_findings() -> None:
    runner = _ToolRunner(
        lambda args, kwargs: _process(_grype_report(), returncode=2), {"grype"}
    )
    result = ImageScanner(runner).scan("image")
    assert not result.covered
    assert not result.ok


def test_scan_result_requires_coverage_and_no_findings() -> None:
    assert ScanResult("trivy", 0, "").ok
    assert not ScanResult("trivy", 1, "").ok
    assert not ScanResult("trivy", 0, "", covered=False).ok
    assert not ScanResult("trivy", 0, "", findings=1).ok


def test_default_images_root_prefers_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "custom-images"
    override.mkdir()
    monkeypatch.setenv("HAIBOX_IMAGES_DIR", str(override))
    assert default_images_root() == override.resolve()


def test_default_images_root_prefers_packaged(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("HAIBOX_IMAGES_DIR", raising=False)
    fake_packaged = tmp_path / "haibox" / "data" / "images"
    fake_packaged.mkdir(parents=True)
    fake_catalog_file = tmp_path / "haibox" / "images" / "catalog.py"
    fake_catalog_file.parent.mkdir(parents=True)
    fake_catalog_file.touch()

    monkeypatch.setattr("haibox.images.catalog.__file__", str(fake_catalog_file))
    assert default_images_root() == fake_packaged.resolve()


def test_default_images_root_falls_back_to_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HAIBOX_IMAGES_DIR", raising=False)
    root = default_images_root()
    assert root.is_dir()
    assert (root / "core" / "manifest.yaml").is_file()

