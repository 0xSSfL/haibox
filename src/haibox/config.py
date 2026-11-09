"""Load and write the user configuration."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError as PydanticValidationError

from haibox.errors import ConfigError
from haibox.models import HAIBOXConfig
from haibox.paths import Paths


def load_config(paths: Paths, config_file: Path | None = None) -> HAIBOXConfig:
    path = config_file or paths.config_file
    if not path.exists():
        return HAIBOXConfig()
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"cannot read configuration {path}: {exc}") from exc
    if raw is None:
        return HAIBOXConfig()
    if not isinstance(raw, dict):
        raise ConfigError(f"configuration {path} must be a YAML mapping")
    try:
        return HAIBOXConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigError(f"invalid configuration {path}: {exc}") from exc


def write_default_config(paths: Paths, force: bool = False) -> Path:
    path = paths.config_file
    if path.exists() and not force:
        raise ConfigError(f"configuration already exists: {path} (use --force to replace)")
    paths.ensure()
    payload = HAIBOXConfig().model_dump(mode="json")
    text = yaml.safe_dump(payload, sort_keys=False)
    fd, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}-", suffix=".tmp", dir=str(path.parent)
    )
    temp = Path(temp_name)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temp.replace(path)
        path.chmod(0o600)
    except OSError as exc:
        temp.unlink(missing_ok=True)
        raise ConfigError(f"cannot write configuration {path}: {exc}") from exc
    return path
