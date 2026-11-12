"""Built-in and user profile tests."""

from __future__ import annotations

import pytest

from haibox.errors import ConfigError
from haibox.paths import Paths
from haibox.profiles import list_profiles, load_profile


def test_builtin_profiles_are_available(paths: Paths) -> None:
    profiles = list_profiles(paths)
    assert set(profiles) == {
        "ad-security",
        "core",
        "full",
        "gui",
        "network-security",
        "osint",
        "web-security",
    }
    assert profiles["web-security"].status == "active"
    assert profiles["core"].status == "active"
    assert profiles["network-security"].status == "active"
    assert profiles["ad-security"].status == "experimental"
    assert profiles["osint"].status == "experimental"
    assert profiles["full"].status == "experimental"
    assert profiles["gui"].status == "experimental"


def test_gui_profile_shape(paths: Paths) -> None:
    profile = load_profile("gui", paths)
    assert profile.name == "gui"
    assert profile.image == "haibox/gui:0.1.0"
    assert profile.network == "isolated"
    assert profile.capabilities == []
    assert "xpra" in profile.tools


def test_web_security_profile_shape(paths: Paths) -> None:
    profile = load_profile("web-security", paths)
    assert profile.name == "web-security"
    assert profile.image == "haibox/web-security:0.1.0"
    assert profile.network == "isolated"
    assert profile.capabilities == ["NET_RAW"]
    assert "ffuf" in profile.tools


def test_user_profile_overrides_builtin(paths: Paths) -> None:
    paths.ensure()
    (paths.profiles_dir / "web-security.yaml").write_text(
        "\n".join(
            [
                "api_version: haibox/v1",
                "name: web-security",
                "description: local",
                "image: local/web:9.9.9",
                "status: active",
                "network: isolated",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    profile = load_profile("web-security", paths)
    assert profile.image == "local/web:9.9.9"


def test_invalid_profile_yaml_is_reported(paths: Paths) -> None:
    paths.ensure()
    (paths.profiles_dir / "broken.yaml").write_text("name: [\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        list_profiles(paths)


def test_invalid_capability_is_rejected(paths: Paths) -> None:
    paths.ensure()
    (paths.profiles_dir / "bad.yaml").write_text(
        "\n".join(
            [
                "api_version: haibox/v1",
                "name: bad",
                "image: haibox/bad:0.1.0",
                "network: isolated",
                "capabilities:",
                "  - SYS_ADMIN",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        list_profiles(paths)


def test_forbidden_environment_is_rejected(paths: Paths) -> None:
    paths.ensure()
    (paths.profiles_dir / "bad-env.yaml").write_text(
        "\n".join(
            [
                "api_version: haibox/v1",
                "name: bad-env",
                "image: haibox/bad:0.1.0",
                "network: isolated",
                "environment:",
                "  DOCKER_HOST: unix:///var/run/docker.sock",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError):
        list_profiles(paths)


@pytest.mark.parametrize(
    "name",
    ["", "../evil", "evil/../web-security", "Web-Security", "web_security", "a" * 41],
)
def test_profile_name_traversal_is_rejected(paths: Paths, name: str) -> None:
    with pytest.raises(ConfigError):
        load_profile(name, paths)


def test_unknown_profile_lists_available_names(paths: Paths) -> None:
    with pytest.raises(ConfigError) as excinfo:
        load_profile("missing", paths)
    message = str(excinfo.value)
    assert "unknown profile" in message
    assert "web-security" in message
