"""Errors raised by the GUI runtime."""

from __future__ import annotations

from haibox.errors import HAIBOXError


class GuiError(HAIBOXError):
    """A GUI session could not be started, verified, or stopped."""


class GuiPreflightError(GuiError):
    """The engagement is not eligible for a GUI session."""


class GuiCredentialError(GuiError):
    """A GUI session credential could not be created, read, or revoked."""


class GuiRelayError(GuiError):
    """The GUI relay could not accept or serve a local client."""
