"""Profile loading.

Profiles are declarative YAML.  Built-ins ship inside the package; users can
override them in ``<config_dir>/profiles`` without editing installed files.
"""

from __future__ import annotations

import re
from importlib import resources
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from haibox.errors import ConfigError
from haibox.models import Profile
from haibox.paths import Paths

_PROFILE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")


def _parse_profile(path: Path, raw: str) -> Profile:
    try:
        data: Any = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise ConfigError(f"invalid profile YAML {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"profile {path} must be a YAML mapping")
    try:
        return Profile.model_validate(data)
    except PydanticValidationError as exc:
        raise ConfigError(f"invalid profile {path}: {exc}") from exc


def _builtin_profiles() -> dict[str, Profile]:
    root = resources.files("haibox").joinpath("data", "profiles")
    profiles: dict[str, Profile] = {}
    try:
        entries = list(root.iterdir())
    except (FileNotFoundError, NotADirectoryError):
        return profiles
    for entry in entries:
        if not entry.name.endswith((".yaml", ".yml")):
            continue
        profile = _parse_profile(Path(entry.name), entry.read_text(encoding="utf-8"))
        profiles[profile.name] = profile
    return profiles


def list_profiles(paths: Paths) -> dict[str, Profile]:
    profiles = _builtin_profiles()
    user_dir = paths.profiles_dir
    if user_dir.is_dir():
        for path in sorted(user_dir.glob("*.yaml")):
            profile = _parse_profile(path, path.read_text(encoding="utf-8"))
            profiles[profile.name] = profile
    return dict(sorted(profiles.items()))


def load_profile(name: str, paths: Paths) -> Profile:
    # Validate before joining the name onto a path: a value such as
    # ``../profiles/evil`` must never be able to read outside the profile
    # directory.
    if not _PROFILE_NAME_RE.fullmatch(name):
        raise ConfigError(
            "profile name must be 1-40 lowercase letters, digits, or hyphens, "
            "and must start with a letter or digit"
        )
    user_path = paths.profiles_dir / f"{name}.yaml"
    if user_path.is_file():
        return _parse_profile(user_path, user_path.read_text(encoding="utf-8"))
    builtins = _builtin_profiles()
    if name in builtins:
        return builtins[name]
    user_names = {p.stem for p in paths.profiles_dir.glob("*.yaml")}
    available = ", ".join(sorted(set(builtins) | user_names))
    raise ConfigError(f"unknown profile {name!r}; available: {available or 'none'}")
