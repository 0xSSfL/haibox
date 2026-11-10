"""Keep the HAIBOX homepage's toolkit cards aligned with the image catalog."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
IMAGES_DIR = ROOT / "images"
HOMEPAGE = ROOT / "docs" / "index.md"

CARD_PATTERN = re.compile(
    r'<article\b(?=[^>]*\bclass="toolkit-card")'
    r'(?=[^>]*\bdata-image="([^"]+)")[^>]*>(.*?)</article>',
    re.DOTALL,
)
TOOL_PATTERN = re.compile(r'<span\b[^>]*\bclass="toolkit-tag"[^>]*>([^<]+)</span>')
BADGE_PATTERN = re.compile(
    r'<span\b[^>]*\bclass="toolkit-badge (badge-active|badge-exp)"[^>]*>'
    r'\s*([^<]+)\s*</span>'
)


def _read_manifests() -> dict[str, dict[str, object]]:
    manifests = {}
    for path in sorted(IMAGES_DIR.glob("*/manifest.yaml")):
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
        manifests[manifest["name"]] = manifest
    return manifests


def _available_tools(
    image_name: str,
    manifests: dict[str, dict[str, object]],
    seen: frozenset[str] = frozenset(),
) -> set[str]:
    if image_name in seen:
        return set()

    manifest = manifests[image_name]
    tools = {tool["name"] for tool in manifest["tools"]}
    base = manifest.get("base", "")
    next_seen = seen | {image_name}
    if isinstance(base, str) and base.startswith("haibox/"):
        base_image = base.split("/", maxsplit=1)[1].split(":", maxsplit=1)[0]
        tools.update(_available_tools(base_image, manifests, next_seen))
    return tools


def test_homepage_toolkit_cards_match_manifests() -> None:
    manifests = _read_manifests()
    homepage = HOMEPAGE.read_text(encoding="utf-8")
    cards = CARD_PATTERN.findall(homepage)

    assert {image_name for image_name, _ in cards} == set(manifests)
    assert len(cards) == 6

    expected_badges = {
        "active": ("badge-active", "Active"),
        "experimental": ("badge-exp", "Experimental"),
    }
    for image_name, card_html in cards:
        manifest = manifests[image_name]
        displayed_tools = {tool.strip() for tool in TOOL_PATTERN.findall(card_html)}
        assert displayed_tools <= _available_tools(image_name, manifests)

        badge = BADGE_PATTERN.search(card_html)
        assert badge is not None
        assert (badge.group(1), badge.group(2).strip()) == expected_badges[manifest["status"]]


def test_homepage_icons_use_local_svg_sprite() -> None:
    homepage = HOMEPAGE.read_text(encoding="utf-8")
    sprite_path = ROOT / "docs" / "assets" / "icons.svg"
    sprite = sprite_path.read_text(encoding="utf-8") if sprite_path.exists() else ""
    symbol_ids = set(re.findall(r'<symbol\b[^>]*\bid="([^"]+)"', sprite))
    referenced_ids = re.findall(
        r'<use\b[^>]*\bhref="assets/icons\.svg#([^"]+)"', homepage
    )

    assert "{% include" not in homepage
    assert len(referenced_ids) >= 15
    assert set(referenced_ids) <= symbol_ids
    assert len(re.findall(r'<svg\b[^>]*>\s*<use\b', homepage)) >= 15
