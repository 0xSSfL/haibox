"""Discover and validate image definitions from the repository."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError as PydanticValidationError

from haibox.errors import ImageError
from haibox.models import ImageManifest


def default_images_root() -> Path:
    """Resolve the image-definition directory.

    ``HAIBOX_IMAGES_DIR`` wins, then the image catalog bundled in the installed
    wheel (``haibox/data/images``), then the source checkout that contains the
    package.  Bundling the catalog keeps ``haibox image`` working when the CLI
    is installed outside a repository.
    """

    override = os.environ.get("HAIBOX_IMAGES_DIR")
    if override:
        return Path(override).expanduser().resolve()
    packaged = Path(__file__).resolve().parents[1] / "data" / "images"
    if packaged.is_dir():
        return packaged
    # src/haibox/images/catalog.py -> parents[3] is the repository root.
    return Path(__file__).resolve().parents[3] / "images"


class ImageCatalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_images_root()).expanduser().resolve()

    def _manifest_path(self, name: str) -> Path:
        return self.root / name / "manifest.yaml"

    def load(self, name: str) -> ImageManifest:
        if not name or "/" in name or name.startswith("."):
            raise ImageError(f"invalid image name: {name!r}")
        path = self._manifest_path(name)
        if not path.is_file():
            raise ImageError(f"image definition not found: {name}")
        try:
            raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise ImageError(f"cannot read image manifest {path}: {exc}") from exc
        if not isinstance(raw, dict):
            raise ImageError(f"image manifest {path} must be a YAML mapping")
        try:
            manifest = ImageManifest.model_validate(raw)
        except PydanticValidationError as exc:
            raise ImageError(f"invalid image manifest {path}: {exc}") from exc
        if manifest.name != name:
            raise ImageError(
                f"image manifest {path} declares name {manifest.name!r}, expected {name!r}"
            )
        return manifest

    def list(self) -> dict[str, ImageManifest]:
        if not self.root.is_dir():
            return {}
        manifests: dict[str, ImageManifest] = {}
        for path in sorted(self.root.iterdir()):
            if path.is_dir() and (path / "manifest.yaml").is_file():
                manifest = self.load(path.name)
                manifests[manifest.name] = manifest
        return manifests

    def image_dir(self, manifest: ImageManifest) -> Path:
        return self.root / manifest.name

    def dockerfile_path(self, manifest: ImageManifest) -> Path:
        image_dir = self.image_dir(manifest)
        path = (image_dir / manifest.dockerfile).resolve()
        try:
            path.relative_to(image_dir.resolve())
        except ValueError as exc:
            raise ImageError("Dockerfile path escapes the image directory") from exc
        if not path.is_file():
            raise ImageError(f"Dockerfile not found: {path}")
        return path

    def context_path(self, manifest: ImageManifest) -> Path:
        image_dir = self.image_dir(manifest)
        path = (image_dir / manifest.context).resolve()
        try:
            path.relative_to(image_dir.resolve())
        except ValueError as exc:
            raise ImageError("build context escapes the image directory") from exc
        if not path.is_dir():
            raise ImageError(f"build context not found: {path}")
        return path

    def scan_ignorefile(self, manifest: ImageManifest) -> Path | None:
        """Return the image-specific Trivy ignore file, when present.

        Suppressions are optional and live next to the image definition so a
        scanner policy is reviewed with the image it applies to. The file is
        only used for Trivy; Grype does not scan for secrets.
        """

        image_dir = self.image_dir(manifest).resolve()
        path = (image_dir / "trivyignore.yaml").resolve()
        try:
            path.relative_to(image_dir)
        except ValueError as exc:
            raise ImageError("scan ignore file escapes the image directory") from exc
        return path if path.is_file() else None

    def image_ref(self, manifest: ImageManifest) -> str:
        return manifest.image_ref
