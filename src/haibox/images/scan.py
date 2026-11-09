"""Optional host-side vulnerability scanner adapters.

Scanning is deliberately not part of the image build.  A missing scanner is a
clear, actionable error rather than a silent pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from haibox.errors import ImageError
from haibox.runtime.process import CommandRunner, SubprocessRunner


@dataclass(frozen=True)
class ScanResult:
    tool: str
    exit_code: int
    output: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


class ImageScanner:
    def __init__(self, runner: CommandRunner | None = None) -> None:
        self.runner = runner or SubprocessRunner()

    def detect(self) -> str | None:
        for tool in ("trivy", "grype"):
            if self.runner.which(tool):
                return tool
        return None

    def scan(
        self,
        image: str,
        *,
        timeout: int = 1800,
        ignorefile: Path | None = None,
    ) -> ScanResult:
        tool = self.detect()
        if tool is None:
            raise ImageError(
                "no image scanner found; install trivy or grype on the Docker host"
            )
        if tool == "trivy":
            args = [
                "trivy",
                "image",
                "--quiet",
                "--severity",
                "HIGH,CRITICAL",
                "--exit-code",
                "1",
            ]
            if ignorefile is not None:
                if not ignorefile.is_file():
                    raise ImageError(f"scan ignore file not found: {ignorefile}")
                args.extend(["--ignorefile", str(ignorefile)])
            args.append(image)
        else:
            args = ["grype", image, "--fail-on", "high"]
        result = self.runner.run(args, timeout=timeout)
        output = (result.stdout + result.stderr).strip()
        return ScanResult(tool=tool, exit_code=result.returncode, output=output)
