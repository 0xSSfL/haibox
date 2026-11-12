"""Production GUI runtime for HAIBOX.

The GUI is an optional capability of an existing engagement runner.  The
runtime keeps every invariant that the disposable prototype proved:

* a session belongs to one engagement and runs in that engagement's own
  isolated container;
* the engagement must have an empty external target scope, and the canonical
  scope file must match the engagement metadata;
* the container must be attached to exactly the engagement network;
* a session is only replaced after the previous server is confirmed
  terminated, and a foreign Xpra server is never signalled;
* the credential is rotated per session, kept in mode-0600 files, and removed
  when the session ends;
* the host reaches the session through a Unix-domain socket in an
  owner-controlled 0700 directory, and the local peer is authenticated.
"""

from haibox.gui.credentials import (
    ensure_private_directory,
    generate_password,
    read_credential,
    remove_credential,
    write_credential,
)
from haibox.gui.errors import (
    GuiCredentialError,
    GuiError,
    GuiPreflightError,
    GuiRelayError,
)
from haibox.gui.relay import GuiRelay
from haibox.gui.session import GuiSessionManager, GuiSessionStatus, ServerReport
from haibox.gui.spec import (
    APPROVED_GUI_IMAGE,
    DENIED_CLIENT_FLAGS,
    DENIED_SERVER_FLAGS,
    GuiLimits,
    GuiSessionSpec,
)

__all__ = [
    "APPROVED_GUI_IMAGE",
    "DENIED_CLIENT_FLAGS",
    "DENIED_SERVER_FLAGS",
    "GuiCredentialError",
    "GuiError",
    "GuiLimits",
    "GuiPreflightError",
    "GuiRelay",
    "GuiRelayError",
    "GuiSessionManager",
    "GuiSessionSpec",
    "GuiSessionStatus",
    "ServerReport",
    "ensure_private_directory",
    "generate_password",
    "read_credential",
    "remove_credential",
    "write_credential",
]
