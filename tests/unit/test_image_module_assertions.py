"""Tests for the web-security Go module metadata checks.

The image build refuses to ship a binary that embeds a vulnerable module
version.  The check lives in a script so it can be exercised here without a
Docker build, including the negative case: a deliberately forbidden
module/version combination has to fail the check.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

IMAGE_DIR = Path(__file__).resolve().parents[2] / "images" / "web-security"
SCRIPT = IMAGE_DIR / "check-modules.sh"
REQUIREMENTS = IMAGE_DIR / "module-requirements.txt"
FORBIDDEN = IMAGE_DIR / "forbidden-modules.txt"
DOCKERFILE = IMAGE_DIR / "Dockerfile"

_HEADER = "/usr/local/bin/{tool}: go1.26.10\n\tpath\t/usr/local/bin/{tool}\n"


def _run(
    modinfo_dir: Path, requirements: Path = REQUIREMENTS, forbidden: Path = FORBIDDEN
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["sh", str(SCRIPT), str(modinfo_dir), str(requirements), str(forbidden)],
        capture_output=True,
        text=True,
        check=False,
    )


def _requirements() -> list[tuple[str, str, str]]:
    entries: list[tuple[str, str, str]] = []
    for line in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        tool, module, version = line.split()
        entries.append((tool, module, version))
    return entries


def _write_modinfo(directory: Path, tool: str, deps: list[tuple[str, str]]) -> None:
    text = _HEADER.format(tool=tool)
    for module, version in deps:
        text += f"\tdep\t{module}\t{version}\th1:checksum\n"
    (directory / f"{tool}.modinfo").write_text(text, encoding="utf-8")


def _clean_metadata(directory: Path) -> None:
    """Write module metadata that satisfies every requirement."""
    deps: dict[str, list[tuple[str, str]]] = {}
    for tool, module, version in _requirements():
        deps.setdefault(tool, []).append((module, version))
    for tool, tool_deps in deps.items():
        _write_modinfo(directory, tool, tool_deps)


def test_committed_lists_are_readable() -> None:
    assert SCRIPT.is_file()
    assert REQUIREMENTS.is_file()
    assert FORBIDDEN.is_file()
    assert _requirements()


def test_script_accepts_metadata_that_matches_the_requirements(tmp_path: Path) -> None:
    _clean_metadata(tmp_path)
    result = _run(tmp_path)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_script_rejects_a_forbidden_module_version(tmp_path: Path) -> None:
    """The negative regression test for the forbidden-version sweep."""
    _clean_metadata(tmp_path)
    # The tool keeps every required version and additionally embeds a
    # vulnerable one, so only the forbidden sweep can fail.
    _write_modinfo(
        tmp_path,
        "dalfox",
        [("github.com/labstack/echo/v4", "v4.16.1"), ("github.com/labstack/echo/v4", "v4.15.2")],
    )
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "github.com/labstack/echo/v4" in result.stderr
    assert "4.15.2" in result.stderr
    assert "does not embed" not in result.stderr


def test_script_rejects_a_forbidden_entry_that_is_not_first(tmp_path: Path) -> None:
    """The sweep must pair every module with its own version."""
    _clean_metadata(tmp_path)
    _write_modinfo(
        tmp_path,
        "katana",
        [("github.com/jackc/pgx/v5", "v5.9.0"), ("github.com/jackc/pgx/v5", "v5.7.2")],
    )
    forbidden = tmp_path / "forbidden.txt"
    forbidden.write_text(
        "\n".join(
            [
                "# a clean entry first",
                "github.com/andybalholm/brotli 1.2.7",
                "github.com/jackc/pgx/v5 5.7.2",
                "golang.org/x/net 0.59.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = _run(tmp_path, forbidden=forbidden)
    assert result.returncode != 0
    assert "github.com/jackc/pgx/v5" in result.stderr
    assert "5.7.2" in result.stderr


def _compare(tmp_path: Path, pinned: str, current: str) -> subprocess.CompletedProcess[str]:
    pinned_file = tmp_path / "go.mod.pinned"
    pinned_file.write_text(pinned, encoding="utf-8")
    current_file = tmp_path / "go.mod"
    current_file.write_text(current, encoding="utf-8")
    return subprocess.run(
        ["sh", str(SCRIPT), "compare", str(current_file), str(pinned_file)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_compare_mode_accepts_an_unchanged_file(tmp_path: Path) -> None:
    result = _compare(tmp_path, "module example.com/x\n", "module example.com/x\n")
    assert result.returncode == 0
    assert "unchanged" in result.stdout


def test_compare_mode_rejects_a_rewritten_requirement_file(tmp_path: Path) -> None:
    """A build that rewrites a pinned requirement has to fail."""
    result = _compare(
        tmp_path,
        "module example.com/x\n\nrequire example.com/y v1.0.0\n",
        "module example.com/x\n\nrequire example.com/y v0.9.0\n",
    )
    assert result.returncode != 0
    assert "modified" in result.stderr


def test_compare_mode_rejects_a_missing_file(tmp_path: Path) -> None:
    result = subprocess.run(
        ["sh", str(SCRIPT), "compare", str(tmp_path / "missing"), str(tmp_path / "also-missing")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "cannot compare" in result.stderr


def test_script_rejects_a_missing_required_version(tmp_path: Path) -> None:
    _clean_metadata(tmp_path)
    _write_modinfo(tmp_path, "ffuf", [("golang.org/x/net", "v0.43.0")])
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "ffuf" in result.stderr
    assert "golang.org/x/net" in result.stderr


def test_script_rejects_metadata_without_the_tool(tmp_path: Path) -> None:
    _clean_metadata(tmp_path)
    (tmp_path / "ffuf.modinfo").unlink()
    result = _run(tmp_path)
    assert result.returncode != 0
    assert "ffuf" in result.stderr


def test_script_reports_a_missing_list(tmp_path: Path) -> None:
    _clean_metadata(tmp_path)
    result = _run(tmp_path, forbidden=tmp_path / "missing.txt")
    assert result.returncode != 0
    assert "missing.txt" in result.stderr


def test_forbidden_list_covers_the_critical_module_versions() -> None:
    entries = {
        (line.split()[0], line.split()[1])
        for line in FORBIDDEN.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for module, version in (
        ("github.com/labstack/echo/v4", "4.15.2"),
        ("github.com/jackc/pgx/v5", "5.7.2"),
        ("google.golang.org/grpc", "1.82.1"),
    ):
        assert (module, version) in entries


def test_dockerfile_uses_the_checked_script() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "check-modules.sh" in dockerfile
    assert "module-requirements.txt" in dockerfile
    assert "forbidden-modules.txt" in dockerfile
    # The inline sweep that split the pairs on whitespace is gone.
    assert "for pair in ${forbidden}" not in dockerfile
    assert "assert_fixed" not in dockerfile


def test_dockerfile_builds_with_readonly_modules() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    assert "-mod=readonly" in dockerfile
    assert "-mod=mod" not in dockerfile
    # The immutability check runs the same tested script the unit tests cover.
    assert "check-modules.sh compare go.mod" in dockerfile
    assert "check-modules.sh compare go.sum" in dockerfile
    assert "cmp -s go.mod" not in dockerfile
    assert "cmp -s go.sum" not in dockerfile


@pytest.mark.parametrize(
    "name", ["ffuf", "gobuster", "httpx", "subfinder", "katana", "dalfox", "nuclei"]
)
def test_every_go_tool_has_a_requirement_entry(name: str) -> None:
    tools = {tool for tool, _, _ in _requirements()}
    assert name in tools
