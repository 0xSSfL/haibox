"""Fixed, validated GUI session specifications.

A GUI session is a property of one engagement.  The specification is built
from the engagement and never from free-form user input: display, port,
runtime directory, and resource limits are fixed values with narrow validation,
so no caller can turn the GUI runtime into a generic container command channel.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from haibox.errors import ValidationError
from haibox.models import Engagement
from haibox.paths import validate_engagement_id

DISPLAY_RE = re.compile(r"^:\d{1,3}$")
IMAGE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/@:+-]*$")

DEFAULT_DISPLAY = ":100"
DEFAULT_PORT = 14500
DEFAULT_RUNTIME_DIR = "/tmp/xpra-runtime"
DEFAULT_PASSWORD_FILE = f"{DEFAULT_RUNTIME_DIR}/xpra-auth"
DEFAULT_LOG_FILE = "/tmp/xpra.log"

#: Xpra server versions this runtime is qualified for.  A container that
#: reports anything else is refused: the deny-by-default flags and the file
#: authentication behaviour were verified against this series.
SUPPORTED_XPRA_VERSIONS: tuple[str, ...] = ("6.5",)

#: The only image identity a GUI session may use.  The engagement image must
#: match this reference exactly; a GUI session never runs an arbitrary image.
APPROVED_GUI_IMAGE = "haibox/gui:0.1.0"

#: Forwarding features that are always disabled on the Xpra server.
DENIED_SERVER_FLAGS: tuple[str, ...] = (
    "--clipboard=no",
    "--file-transfer=no",
    "--printing=no",
    "--speaker=disabled",
    "--microphone=disabled",
    "--webcam=no",
    "--notifications=no",
    "--system-tray=no",
    "--dbus=no",
    "--dbus-control=no",
    "--start-new-commands=no",
    "--sharing=no",
    "--html=no",
    "--mdns=no",
)

#: Client-side flags that mirror the denied server features.
DENIED_CLIENT_FLAGS: tuple[str, ...] = DENIED_SERVER_FLAGS


@dataclass(frozen=True)
class GuiLimits:
    """Resource and concurrency limits for one GUI session."""

    cpus: float = 2.0
    memory: str = "2g"
    pids_limit: int = 512
    max_sessions: int = 1
    max_connections: int = 1
    connect_timeout: int = 30
    stream_idle_timeout: int = 120
    stream_write_timeout: int = 10
    shutdown_timeout: int = 10

    def __post_init__(self) -> None:
        if not 0 < self.cpus <= 64:
            raise ValidationError("gui cpus must be between 0 and 64")
        if not re.fullmatch(r"[1-9][0-9]*[bkmg]?", self.memory, re.IGNORECASE):
            raise ValidationError("gui memory must look like '512m' or '2g'")
        if not 16 <= self.pids_limit <= 4096:
            raise ValidationError("gui pids_limit must be between 16 and 4096")
        if not 1 <= self.max_sessions <= 4:
            raise ValidationError("gui max_sessions must be between 1 and 4")
        if not 1 <= self.max_connections <= 8:
            raise ValidationError("gui max_connections must be between 1 and 8")
        for name in (
            "connect_timeout",
            "stream_idle_timeout",
            "stream_write_timeout",
            "shutdown_timeout",
        ):
            value = getattr(self, name)
            if not 1 <= value <= 3600:
                raise ValidationError(f"gui {name} must be between 1 and 3600 seconds")


@dataclass(frozen=True)
class GuiSessionSpec:
    """The immutable description of one engagement-bound GUI session."""

    engagement_id: str
    container: str
    image: str
    display: str = DEFAULT_DISPLAY
    port: int = DEFAULT_PORT
    runtime_dir: str = DEFAULT_RUNTIME_DIR
    password_file: str = DEFAULT_PASSWORD_FILE
    log_file: str = DEFAULT_LOG_FILE
    limits: GuiLimits = field(default_factory=GuiLimits)
    server_flags: tuple[str, ...] = DENIED_SERVER_FLAGS
    client_flags: tuple[str, ...] = DENIED_CLIENT_FLAGS

    def __post_init__(self) -> None:
        try:
            valid = validate_engagement_id(self.engagement_id)
        except Exception as exc:  # noqa: BLE001 - surfaced as a validation error
            raise ValidationError(str(exc)) from exc
        if valid != self.engagement_id:
            raise ValidationError("engagement id is not normalized")
        if self.container != f"haibox-{self.engagement_id}":
            raise ValidationError(
                f"gui container must be haibox-{self.engagement_id}, "
                f"not {self.container!r}"
            )
        if not IMAGE_RE.fullmatch(self.image) or self.image.startswith("-"):
            raise ValidationError(f"invalid gui image reference: {self.image!r}")
        if self.image != APPROVED_GUI_IMAGE:
            raise ValidationError(
                f"gui sessions require the approved image {APPROVED_GUI_IMAGE!r}"
            )
        if not DISPLAY_RE.fullmatch(self.display):
            raise ValidationError(f"invalid gui display: {self.display!r}")
        if not 1024 <= self.port <= 65535:
            raise ValidationError("gui port must be between 1024 and 65535")
        for name in ("runtime_dir", "password_file", "log_file"):
            value = getattr(self, name)
            if not value.startswith("/") or ".." in value:
                raise ValidationError(f"gui {name} must be an absolute path without '..'")
        if self.runtime_dir != DEFAULT_RUNTIME_DIR:
            raise ValidationError(
                f"gui runtime directory is fixed at {DEFAULT_RUNTIME_DIR!r}"
            )
        if self.password_file != DEFAULT_PASSWORD_FILE:
            raise ValidationError(
                f"gui credential file is fixed at {DEFAULT_PASSWORD_FILE!r}"
            )
        if self.log_file != DEFAULT_LOG_FILE:
            raise ValidationError(f"gui log file is fixed at {DEFAULT_LOG_FILE!r}")
        if tuple(self.server_flags) != DENIED_SERVER_FLAGS:
            raise ValidationError(
                "the gui server deny list is fixed and cannot be changed"
            )
        if tuple(self.client_flags) != DENIED_CLIENT_FLAGS:
            raise ValidationError(
                "the gui client deny list is fixed and cannot be changed"
            )

    @classmethod
    def from_engagement(cls, engagement: Engagement) -> GuiSessionSpec:
        """Build the fixed specification for an engagement."""

        return cls(
            engagement_id=engagement.id,
            container=engagement.runtime.container_name,
            image=engagement.image,
        )

    @property
    def bind_tcp(self) -> str:
        """The container loopback bind address for the Xpra server."""

        return f"127.0.0.1:{self.port}"

    @property
    def auth_argument(self) -> str:
        """The file authentication argument, with the password as a filename."""

        return f"auth=file:filename={self.password_file}"

    def server_args(self) -> tuple[str, ...]:
        """The fixed Xpra server command line."""

        return (
            "xpra",
            "start",
            self.display,
            "--daemon=no",
            f"--socket-dirs={self.runtime_dir}",
            f"--bind-tcp={self.bind_tcp},{self.auth_argument}",
            "--start=xterm",
            *self.server_flags,
        )

    def client_args(self) -> tuple[str, ...]:
        """The fixed Xpra client flags that mirror the denied features."""

        return self.client_flags
