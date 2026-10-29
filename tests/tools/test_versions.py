"""Installed versions, pyproject pins, _versions.py and the stlite page agree (ADR 0004)."""

from __future__ import annotations

import tomllib
from importlib.metadata import version
from pathlib import Path

from data_explorer import __version__, _versions


def test_package_version() -> None:
    assert __version__ == "0.1.0"
    assert version("data-explorer-app") == __version__


def test_installed_versions_equal_the_browser_pins() -> None:
    assert version("streamlit") == _versions.STREAMLIT
    assert version("pandas") == _versions.PANDAS
    assert version("altair") == _versions.ALTAIR
    assert version("openpyxl") == _versions.OPENPYXL


def test_pyproject_pins_equal_versions_module(repo_root: Path) -> None:
    project = tomllib.loads((repo_root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = set(project["dependencies"])
    for name, pin in (
        ("streamlit", _versions.STREAMLIT),
        ("pandas", _versions.PANDAS),
        ("altair", _versions.ALTAIR),
        ("openpyxl", _versions.OPENPYXL),
    ):
        assert f"{name}=={pin}" in dependencies
    assert project["version"] == __version__


def test_stlite_page_pins(repo_root: Path) -> None:
    html = (repo_root / "web" / "index.html").read_text(encoding="utf-8")
    assert html.count(f"@stlite/browser@{_versions.STLITE}") == 2
    assert html.count("@stlite/browser@") == 2
    base = f"https://cdn.jsdelivr.net/npm/@stlite/browser@{_versions.STLITE}/build/"
    assert f"const STLITE_CSS = '{base}stlite.css';" in html
    assert f"const STLITE_JS = '{base}stlite.js';" in html
    assert html.count(f"openpyxl=={_versions.OPENPYXL}") == 1


def test_browser_runtime_constants() -> None:
    assert _versions.PYODIDE.split(".")[0] == _versions.PYODIDE_PYTHON.replace(".", "")
    assert _versions.STLITE == "1.12.0" and _versions.PYODIDE == "314.0.3"
