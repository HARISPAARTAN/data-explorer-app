"""The server config, the CLI flags, the stlite settings and the kit tokens agree."""

from __future__ import annotations

import json
import re
import tomllib
from pathlib import Path
from typing import Any

import pytest

from data_explorer import cli

TOKEN_OF = {
    "theme.backgroundColor": "--bg",
    "theme.secondaryBackgroundColor": "--surface",
    "theme.textColor": "--text",
    "theme.primaryColor": "--accent",
}


@pytest.fixture(scope="module")
def server(repo_root: Path) -> dict[str, Any]:
    parsed = tomllib.loads((repo_root / ".streamlit" / "config.toml").read_text(encoding="utf-8"))
    return {f"{section}.{key}": value for section, values in parsed.items() for key, value in values.items()}


@pytest.fixture(scope="module")
def page(repo_root: Path) -> dict[str, Any]:
    html = (repo_root / "web" / "index.html").read_text(encoding="utf-8")
    match = re.search(r'<script type="application/json" id="app-config">(.*?)</script>', html, re.S)
    assert match is not None
    parsed: dict[str, Any] = json.loads(match.group(1))
    return parsed


def flag_value(value: object) -> str:
    return str(value).lower() if isinstance(value, bool) else str(value)


def test_client_and_browser_keys_agree(server: dict[str, Any], page: dict[str, Any]) -> None:
    shared = {key: value for key, value in server.items() if key.split(".")[0] in ("client", "browser")}
    assert page["streamlitConfig"] == shared
    assert shared == {
        "client.toolbarMode": "viewer",
        "client.showSidebarNavigation": False,
        "browser.gatherUsageStats": False,
    }


def test_dark_theme_agrees(server: dict[str, Any], page: dict[str, Any]) -> None:
    assert server["theme.base"] == "dark"
    dark = {key: value for key, value in server.items() if key.startswith("theme.") and key != "theme.base"}
    assert page["themes"]["dark"] == dark
    assert set(page["themes"]) == {"dark", "light"} and set(page["themes"]["light"]) == set(dark) == set(
        TOKEN_OF
    )


def test_cli_flags_carry_the_whole_config(server: dict[str, Any]) -> None:
    flags = dict(flag.removeprefix("--").split("=", 1) for flag in cli.CONFIG_FLAGS)
    assert flags == {key: flag_value(value) for key, value in server.items()}


def test_theme_colours_come_from_the_kit_tokens(repo_root: Path, page: dict[str, Any]) -> None:
    css = (repo_root / "web" / "kit" / "tokens.css").read_text(encoding="utf-8")
    split = css.index(':root[data-theme="light"]')
    blocks = {"dark": css[:split], "light": css[split:]}
    for theme, block in blocks.items():
        for key, token in TOKEN_OF.items():
            match = re.search(rf"{token}\s*:\s*(#[0-9A-Fa-f]{{6}})\b", block)
            assert match is not None, f"{token} in the {theme} tokens"
            assert page["themes"][theme][key].upper() == match.group(1).upper(), (theme, key)
