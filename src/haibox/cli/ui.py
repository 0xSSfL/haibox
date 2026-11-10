"""Shared terminal UI: theme, colour policy, and small output helpers.

The theme is intentionally small and semantic. Commands should use the named
styles instead of hard-coded colours so that ``--no-color``, ``NO_COLOR``, and
quiet mode behave consistently.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.prompt import Confirm, IntPrompt, Prompt
from rich.theme import Theme

THEME = Theme(
    {
        "haibox.brand": "bold cyan",
        "haibox.heading": "bold #eab308",
        "haibox.section": "bold #eab308",
        "haibox.ok": "bold green",
        "haibox.warn": "bold #f59e0b",
        "haibox.err": "bold red",
        "haibox.info": "bold #38bdf8",
        "haibox.muted": "dim #64748b",
        "haibox.key": "bold cyan",
        "haibox.value": "white",
        "haibox.accent": "bold #eab308",
        "haibox.prompt": "bold cyan",
        "haibox.border": "#2b3d52",
        "haibox.success": "bold green",
        "haibox.failure": "bold red",
        "haibox.tag": "bold #38bdf8",
        "haibox.gold": "bold #eab308",
    }
)


@dataclass
class UiOptions:
    """Process-wide output policy set by the root CLI callback."""

    quiet: bool = False
    color: bool | None = None
    json_output: bool = False
    assume_yes: bool = False
    debug: bool = False
    verbose: int = 0


_options = UiOptions()
_console: Console | None = None
_error_console: Console | None = None


def configure(
    *,
    quiet: bool = False,
    color: bool | None = None,
    json_output: bool = False,
    assume_yes: bool = False,
    debug: bool = False,
    verbose: int = 0,
) -> None:
    """Replace the process-wide UI policy and drop cached consoles."""

    global _options, _console, _error_console
    _options = UiOptions(
        quiet=quiet,
        color=color,
        json_output=json_output,
        assume_yes=assume_yes,
        debug=debug,
        verbose=verbose,
    )
    _console = None
    _error_console = None


def options() -> UiOptions:
    return _options


def _no_color() -> bool:
    if _options.color is False:
        return True
    if _options.color is True:
        return False
    return "NO_COLOR" in os.environ


def get_console(*, stderr: bool = False) -> Console:
    """Return the shared console, honouring colour and quiet policy.

    Errors always go to a non-quiet stderr console so that ``--quiet`` cannot
    hide a failure.
    """

    global _console, _error_console
    if stderr:
        if _error_console is None:
            _error_console = Console(
                theme=THEME,
                stderr=True,
                no_color=_no_color(),
                highlight=False,
                markup=True,
            )
        return _error_console
    if _console is None:
        _console = Console(
            theme=THEME,
            no_color=_no_color(),
            quiet=_options.quiet,
            highlight=False,
            markup=True,
        )
    return _console


class _ConsoleProxy:
    """Late-bound console so ``from haibox.cli.ui import console`` follows policy."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_console(), name)


console = _ConsoleProxy()


def info(message: str) -> None:
    if not _options.quiet:
        get_console().print(message)


def success(message: str) -> None:
    if not _options.quiet:
        get_console().print(f"[haibox.ok]✓[/haibox.ok] {message}")


def warn(message: str) -> None:
    if not _options.quiet:
        get_console().print(f"[haibox.warn]![/haibox.warn] {message}")


def error(message: str) -> None:
    get_console(stderr=True).print(f"[haibox.err]error:[/haibox.err] {message}")


def heading(message: str) -> None:
    if not _options.quiet:
        get_console().rule(f"[haibox.heading]{message}[/haibox.heading]")


def muted(message: str) -> None:
    if not _options.quiet:
        get_console().print(f"[haibox.muted]{message}[/haibox.muted]")


def confirm(question: str, *, default: bool = False) -> bool:
    """Ask unless ``--yes`` was supplied."""

    if _options.assume_yes:
        return True
    return Confirm.ask(f"[haibox.prompt]{question}[/haibox.prompt]", default=default)


def ask(question: str, *, default: str | None = None) -> str:
    prompt = f"[haibox.prompt]{question}[/haibox.prompt]"
    if default is None:
        return Prompt.ask(prompt)
    return Prompt.ask(prompt, default=default)


def ask_int(question: str, *, default: int | None = None) -> int:
    prompt = f"[haibox.prompt]{question}[/haibox.prompt]"
    if default is None:
        return IntPrompt.ask(prompt)
    return IntPrompt.ask(prompt, default=default)


def choose(question: str, choices: list[tuple[str, str]], *, default: str | None = None) -> str:
    """Numbered menu; returns the key of the chosen entry."""

    if not choices:
        raise ValueError("choose() requires at least one choice")
    get_console().print(f"\n[haibox.heading]▸ {question}[/haibox.heading]")
    for index, (_key, label) in enumerate(choices, start=1):
        get_console().print(f"  [haibox.accent]{index:>2}[/haibox.accent]. {label}")
    keys = [key for key, _ in choices]
    while True:
        raw = Prompt.ask(
            "[haibox.prompt]Select[/haibox.prompt]",
            default=default if default is not None else "",
        )
        if raw in keys:
            return raw
        try:
            position = int(raw)
        except ValueError:
            warn(f"unknown selection: {raw}")
            continue
        if 1 <= position <= len(choices):
            return choices[position - 1][0]
        warn(f"selection must be between 1 and {len(choices)}")


def banner(subtitle: str = "isolation-first pentest platform") -> None:
    if _options.quiet:
        return
    get_console().print(
        "[haibox.brand]██╗  ██╗ █████╗ ██╗██████╗  ██████╗ ██╗  ██╗[/haibox.brand]"
    )
    get_console().print(
        "[haibox.brand]██║  ██║██╔══██╗██║██╔══██╗██╔═══██╗╚██╗██╔╝[/haibox.brand]"
    )
    get_console().print(
        "[haibox.brand]███████║███████║██║██████╔╝██║   ██║ ╚███╔╝ [/haibox.brand]"
    )
    get_console().print(
        "[haibox.brand]██╔══██║██╔══██║██║██╔══██╗██║   ██║ ██╔██╗ [/haibox.brand]"
    )
    get_console().print(
        "[haibox.brand]██║  ██║██║  ██║██║██████╔╝╚██████╔╝██╔╝ ██╗[/haibox.brand]"
    )
    get_console().print(
        "[haibox.brand]╚═╝  ╚═╝╚═╝  ╚═╝╚═╝╚═════╝  ╚═════╝ ╚═╝  ╚═╝[/haibox.brand]"
    )
    get_console().print(f"[haibox.muted]{subtitle}[/haibox.muted]\n")
