"""Verify an image by running its manifest commands in an ephemeral container."""

from __future__ import annotations

from haibox.errors import ImageError
from haibox.images.catalog import ImageCatalog
from haibox.models import ImageManifest
from haibox.runtime.base import ContainerRuntime


def verification_script(manifest: ImageManifest) -> str:
    lines = ["set -eu", 'test "$(id -u)" -ne 0']
    if any(tool.name == "nuclei-templates" for tool in manifest.tools):
        lines.append("test -r /opt/nuclei-templates")
    lines.extend(tool.verify for tool in manifest.tools)
    return "\n".join(lines)


class ImageVerifier:
    def __init__(self, catalog: ImageCatalog, runtime: ContainerRuntime) -> None:
        self.catalog = catalog
        self.runtime = runtime

    def verify(self, manifest: ImageManifest, *, timeout: int = 600) -> str:
        image = self.catalog.image_ref(manifest)
        result = self.runtime.run_ephemeral(
            image,
            ["-c", verification_script(manifest)],
            timeout=timeout,
            entrypoint="/bin/sh",
        )
        if not result.ok:
            detail = (result.stderr or result.stdout).strip()
            raise ImageError(
                f"image verification failed for {image} "
                f"(exit {result.exit_code}): {detail[-4000:]}"
            )
        return result.stdout
