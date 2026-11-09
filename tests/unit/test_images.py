"""Image catalog, manifest, builder, verifier, and scanner tests."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from haibox.errors import ImageError
from haibox.images.builder import ImageBuilder, tools_digest
from haibox.images.catalog import ImageCatalog
from haibox.images.scan import ImageScanner, ScanResult
from haibox.images.verify import ImageVerifier, verification_script
from haibox.models import ImageManifest, ImageTool
from haibox.runtime.base import ExecResult
from tests.fakes import FakeRuntime, ScriptedRunner, process_fail, process_ok


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


def test_scanner_detects_trivy() -> None:
    runner = ScriptedRunner(lambda args, kwargs: process_ok("scan output"))
    scanner = ImageScanner(runner)
    assert scanner.detect() == "trivy"
    result = scanner.scan("haibox/web-security:0.1.0")
    assert result == ScanResult(tool="trivy", exit_code=0, output="scan output")
    args = runner.calls[0]
    assert args[:2] == ["trivy", "image"]
    assert "haibox/web-security:0.1.0" in args


def test_scanner_passes_a_scoped_ignore_file(tmp_path: Path) -> None:
    ignorefile = tmp_path / "trivyignore.yaml"
    ignorefile.write_text("secrets: []\n", encoding="utf-8")
    runner = ScriptedRunner(lambda args, kwargs: process_ok("scan output"))
    result = ImageScanner(runner).scan("image", ignorefile=ignorefile)
    assert result.ok
    args = runner.calls[0]
    assert args[args.index("--ignorefile") + 1] == str(ignorefile)
    assert args[-1] == "image"


def test_scanner_rejects_a_missing_ignore_file(tmp_path: Path) -> None:
    scanner = ImageScanner(ScriptedRunner(lambda args, kwargs: process_ok()))
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
    class GrypeRunner(ScriptedRunner):
        def which(self, program: str) -> str | None:
            return "/usr/bin/grype" if program == "grype" else None

    runner = GrypeRunner(lambda args, kwargs: process_ok("grype output"))
    scanner = ImageScanner(runner)
    assert scanner.detect() == "grype"
    result = scanner.scan("image")
    assert result.tool == "grype"
    assert runner.calls[0][:2] == ["grype", "image"]


def test_scanner_missing_is_an_error() -> None:
    scanner = ImageScanner(ScriptedRunner(which=None))
    assert scanner.detect() is None
    with pytest.raises(ImageError):
        scanner.scan("image")


def test_scanner_findings_are_not_ok() -> None:
    scanner = ImageScanner(ScriptedRunner(lambda args, kwargs: process_fail("CVE")))
    result = scanner.scan("image")
    assert not result.ok
    assert "CVE" in result.output


def test_scan_result_property() -> None:
    assert ScanResult("trivy", 0, "").ok
    assert not ScanResult("trivy", 1, "").ok
