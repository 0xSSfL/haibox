"""Build an image from a validated manifest."""

from __future__ import annotations

import hashlib
import json

from haibox.errors import ImageError
from haibox.images.catalog import ImageCatalog
from haibox.models import ImageManifest
from haibox.runtime.base import ContainerRuntime


def tools_digest(manifest: ImageManifest) -> str:
    payload = json.dumps(
        [tool.model_dump(mode="json") for tool in manifest.tools],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class ImageBuilder:
    """Build an image and its declared local base images.

    A manifest may list ``depends_on`` entries. Dependencies are built first so
    a Dockerfile can use ``FROM haibox/<dependency>:<version>`` without relying
    on an untracked local tag. Diamond dependencies are built once per call, and
    cycles are rejected before any Docker command runs.
    """

    def __init__(self, catalog: ImageCatalog, runtime: ContainerRuntime) -> None:
        self.catalog = catalog
        self.runtime = runtime
        self._built: dict[str, str] = {}
        self._visiting: set[str] = set()
        self._reuse_existing = False

    def build(
        self,
        manifest: ImageManifest,
        *,
        no_cache: bool = False,
        platform: str | None = None,
        reuse_existing: bool = False,
    ) -> str:
        self._built.clear()
        self._visiting.clear()
        self._reuse_existing = reuse_existing
        return self._build(manifest, no_cache=no_cache, platform=platform)

    def _build(
        self,
        manifest: ImageManifest,
        *,
        no_cache: bool,
        platform: str | None,
    ) -> str:
        if manifest.name in self._built:
            return self._built[manifest.name]
        if manifest.name in self._visiting:
            chain = " -> ".join(sorted(self._visiting | {manifest.name}))
            raise ImageError(f"image dependency cycle detected: {chain}")
        self._visiting.add(manifest.name)
        try:
            outputs: list[str] = []
            for dependency in manifest.depends_on:
                dependency_manifest = self.catalog.load(dependency)
                if self._reuse_existing and self.runtime.image_exists(
                    dependency_manifest.image_ref
                ):
                    continue
                outputs.append(
                    self._build(
                        dependency_manifest,
                        no_cache=no_cache,
                        platform=platform,
                    )
                )
            outputs.append(self._build_one(manifest, no_cache=no_cache, platform=platform))
            output = "\n".join(part for part in outputs if part)
            self._built[manifest.name] = output
            return output
        finally:
            self._visiting.discard(manifest.name)

    def _build_one(
        self,
        manifest: ImageManifest,
        *,
        no_cache: bool,
        platform: str | None,
    ) -> str:
        tag = self.catalog.image_ref(manifest)
        dockerfile = self.catalog.dockerfile_path(manifest)
        context = self.catalog.context_path(manifest)
        labels = {
            "org.opencontainers.image.title": f"HAIBOX {manifest.name}",
            "org.opencontainers.image.version": manifest.version,
            "org.opencontainers.image.licenses": "MIT",
            "haibox.image.name": manifest.name,
            "haibox.image.version": manifest.version,
            "haibox.image.tools-sha256": tools_digest(manifest),
        }
        return self.runtime.build_image(
            tag,
            str(dockerfile),
            str(context),
            platform=platform,
            no_cache=no_cache,
            labels=labels,
            build_args=dict(manifest.build_args),
        )
