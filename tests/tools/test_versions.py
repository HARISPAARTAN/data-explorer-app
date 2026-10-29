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
