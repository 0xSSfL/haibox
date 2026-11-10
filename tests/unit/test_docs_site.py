"""Keep the HAIBOX homepage's toolkit cards aligned with the image catalog."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).parents[2]
IMAGES_DIR = ROOT / "images"
HOMEPAGE = ROOT / "docs" / "index.md"
MKDOCS_CONFIG = ROOT / "mkdocs.yml"
DOCS_DIR = ROOT / "docs"

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


def _load_mkdocs_config() -> dict[str, object]:
    class MkDocsLoader(yaml.SafeLoader):
        pass

    MkDocsLoader.add_multi_constructor(
        "tag:yaml.org,2002:python/name:", lambda loader, suffix, node: None
    )
    return yaml.load(MKDOCS_CONFIG.read_text(encoding="utf-8"), Loader=MkDocsLoader)


def _navigation_paths(items: list[dict[str, object]]) -> list[str]:
    paths = []
    for item in items:
        value = next(iter(item.values()))
        if isinstance(value, str):
            paths.append(value)
        else:
            paths.extend(_navigation_paths(value))
    return paths


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


def test_navigation_uses_five_groups_without_dropping_documents() -> None:
    config = _load_mkdocs_config()
    navigation = config["nav"]
    group_names = [next(iter(item)) for item in navigation]
    nav_paths = _navigation_paths(navigation)
    document_paths = {
        path.relative_to(DOCS_DIR).as_posix()
        for path in DOCS_DIR.rglob("*.md")
        if path.relative_to(DOCS_DIR).as_posix() != "README.md"
        and path.relative_to(DOCS_DIR).parts[0] != "superpowers"
    }

    assert group_names == ["Home", "Getting Started", "Toolkits", "Security", "Development"]
    assert set(nav_paths) == document_paths
    assert all((DOCS_DIR / path).is_file() for path in nav_paths)


def test_footer_has_branded_links_and_copyright() -> None:
    config = _load_mkdocs_config()
    footer_path = ROOT / "overrides" / "partials" / "footer.html"
    assert footer_path.is_file()

    footer = footer_path.read_text(encoding="utf-8")
    assert config["copyright"] == "© 2026 HAIBOX contributors · Built by 0xSSfL"
    assert config["theme"]["custom_dir"] == "overrides"
    assert config["extra"]["generator"] is False
    for label in ("Documentation", "Toolkits", "Security", "GitHub", "MIT License"):
        assert f">{label}</a>" in footer
    assert "{{ base_url.rstrip('/') }}/user-guide/" in footer
    assert "{{ base_url.rstrip('/') }}/#toolkits" in footer
    assert "{{ base_url.rstrip('/') }}/threat-model/" in footer
    assert "{{ base_url }}/" not in footer
    assert '{{ config.repo_url }}/blob/main/LICENSE' in footer


def test_homepage_raw_html_links_use_published_urls() -> None:
    homepage = HOMEPAGE.read_text(encoding="utf-8")

    assert 'href="user-guide.md"' not in homepage
    assert 'href="threat-model.md"' not in homepage
