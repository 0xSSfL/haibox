"""Subprocess execution without a shell."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from haibox.errors import RuntimeFailure

# Environment variables that could silently redirect the Docker client to a
# different daemon.  The runtime always passes an explicit context or host.
_DOCKER_ENV_VARS = (
    "DOCKER_HOST",
    "DOCKER_CONTEXT",
    "DOCKER_TLS_VERIFY",
    "DOCKER_CERT_PATH",
    "DOCKER_API_VERSION",
)


@dataclass(frozen=True)
class ProcessResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0


class CommandRunner(Protocol):
    def run(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
        capture: bool = True,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ProcessResult: ...

    def interactive(
        self, args: list[str], *, env: dict[str, str] | None = None
    ) -> int: ...

    def which(self, program: str) -> str | None: ...


def _base_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ)
    for key in _DOCKER_ENV_VARS:
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


class SubprocessRunner:
    """Real runner used by the CLI and integration tests."""

    def run(
        self,
        args: list[str],
        *,
        timeout: int | None = None,
        capture: bool = True,
        input_text: str | None = None,
        env: dict[str, str] | None = None,
    ) -> ProcessResult:
        command = [str(arg) for arg in args]
        try:
            completed = subprocess.run(  # noqa: S603 - explicit argv, no shell
                command,
                input=input_text,
                capture_output=capture,
                text=True,
                timeout=timeout,
                env=_base_env(env),
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeFailure(f"command not found: {command[0]}") from exc
        except PermissionError as exc:
            raise RuntimeFailure(f"command is not executable: {command[0]}") from exc
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else ""
            stderr = exc.stderr if isinstance(exc.stderr, str) else ""
            return ProcessResult(
                args=tuple(command),
                returncode=124,
                stdout=stdout,
                stderr=stderr or f"timed out after {timeout}s",
                timed_out=True,
            )
        return ProcessResult(
            args=tuple(command),
            returncode=completed.returncode,
            stdout=completed.stdout or "",
            stderr=completed.stderr or "",
        )

    def interactive(
        self, args: list[str], *, env: dict[str, str] | None = None
    ) -> int:
        command = [str(arg) for arg in args]
        try:
            completed = subprocess.run(  # noqa: S603 - explicit argv, no shell
                command,
                env=_base_env(env),
                check=False,
            )
        except FileNotFoundError as exc:
            raise RuntimeFailure(f"command not found: {command[0]}") from exc
        return completed.returncode

    def which(self, program: str) -> str | None:
        return shutil.which(program)


def find_program(program: str, runner: CommandRunner | None = None) -> Path | None:
    found = (runner or SubprocessRunner()).which(program)
    return Path(found) if found else None
