"""Expected, user-facing errors.

Unexpected exceptions are allowed to propagate so that bugs remain visible.
Commands catch :class:`HAIBOXError` and turn it into a clean message and a
non-zero exit code.
"""

from __future__ import annotations


class HAIBOXError(Exception):
    """Base class for expected platform errors."""

    exit_code = 1


class ConfigError(HAIBOXError):
    """Invalid or missing configuration."""


class ValidationError(HAIBOXError):
    """Invalid user input or persisted data."""


class ScopeError(HAIBOXError):
    """Invalid scope definition."""


class EngagementError(HAIBOXError):
    """Engagement lifecycle error."""


class RuntimeFailure(HAIBOXError):
    """The container runtime is unavailable or returned an error."""


class ContainerError(RuntimeFailure):
    """A container operation was refused or failed."""


class ImageError(HAIBOXError):
    """An image build, verification, or scan failed."""


class SecretError(HAIBOXError):
    """Secret store error."""


class EvidenceError(HAIBOXError):
    """Evidence store error."""


class VpnError(HAIBOXError):
    """VPN provider or connection error."""


class AuditError(HAIBOXError):
    """Audit log error."""
