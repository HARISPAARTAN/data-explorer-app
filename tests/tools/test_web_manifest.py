"""web/index.html mounts exactly the 22 files of docs/architecture.md and frames them as documented."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from data_explorer import _versions

EXPECTED_FILES = {
    "streamlit_app.py": "py/data_explorer/app/streamlit_app.py",
    "pages/2_Overview.py": "py/data_explorer/app/pages/2_Overview.py",
    "pages/3_Quality.py": "py/data_explorer/app/pages/3_Quality.py",
    "pages/4_Explore.py": "py/data_explorer/app/pages/4_Explore.py",
    "pages/5_Visualise.py": "py/data_explorer/app/pages/5_Visualise.py",
    "pages/6_Download.py": "py/data_explorer/app/pages/6_Download.py",
    "data_explorer/__init__.py": "py/data_explorer/__init__.py",
    "data_explorer/_versions.py": "py/data_explorer/_versions.py",
    "data_explorer/core/__init__.py": "py/data_explorer/core/__init__.py",
    "data_explorer/core/io.py": "py/data_explorer/core/io.py",
    "data_explorer/core/profile.py": "py/data_explorer/core/profile.py",
    "data_explorer/core/quality.py": "py/data_explorer/core/quality.py",
    "data_explorer/core/filters.py": "py/data_explorer/core/filters.py",
    "data_explorer/core/charts.py": "py/data_explorer/core/charts.py",
    "data_explorer/core/export.py": "py/data_explorer/core/export.py",
    "data_explorer/app/__init__.py": "py/data_explorer/app/__init__.py",
    "data_explorer/app/state.py": "py/data_explorer/app/state.py",
    "data_explorer/app/ui.py": "py/data_explorer/app/ui.py",
    "data_explorer/app/cache.py": "py/data_explorer/app/cache.py",
    "data_explorer/samples/retail_orders.csv": "py/data_explorer/samples/retail_orders.csv",
    "data_explorer/samples/sensor_readings.csv": "py/data_explorer/samples/sensor_readings.csv",
    "data_explorer/samples/client_survey.xlsx": "py/data_explorer/samples/client_survey.xlsx",
}
FALLBACK = (
    "The live demo cannot start in this browser",
    "This demo runs Python inside your browser with WebAssembly and module workers. This browser does not "
    "support them or has them switched off, or the runtime could not be downloaded.",
    "Try a current version of Chrome, Edge, Firefox or Safari, look at the screenshots below, or run the app "
    "yourself: <code>uv sync</code> and <code>uv run data-explorer run</code>, or "
    "<code>docker build -t data-explorer .</code> and <code>docker run -p 8501:8501 data-explorer</code>.",
)
LOADING = (
    "Starting Python in your browser. The first visit downloads the Python runtime and libraries from a public "
    "CDN; later visits load them from the browser cache. Your files are read inside this browser and are not "
    "uploaded anywhere."
)
FOOTER = "Rebuilt from memory as a demo. The original client&#39;s name and data are not used."


@pytest.fixture(scope="module")
def html(repo_root: Path) -> str:
    return (repo_root / "web" / "index.html").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def config(html: str) -> dict[str, Any]:
    match = re.search(r'<script type="application/json" id="app-config">(.*?)</script>', html, re.S)
    assert match is not None
    parsed: dict[str, Any] = json.loads(match.group(1))
    return parsed


def test_the_22_mounted_files(config: dict[str, Any]) -> None:
    assert config["files"] == EXPECTED_FILES
    assert len(config["files"]) == 22 and len(set(config["files"].values())) == 22


def test_every_url_exists_and_every_synced_file_is_mounted(repo_root: Path, config: dict[str, Any]) -> None:
    web = repo_root / "web"
    for url in config["files"].values():
        assert (web / url).is_file(), url
    synced = {path.relative_to(web).as_posix() for path in (web / "py").rglob("*") if path.is_file()}
    assert synced == set(config["files"].values())


def test_entrypoint_and_requirements(config: dict[str, Any]) -> None:
    assert config["entrypoint"] == "streamlit_app.py"
    assert config["requirements"] == ["pandas", "altair", f"openpyxl=={_versions.OPENPYXL}"]
    assert set(config) == {"entrypoint", "requirements", "streamlitConfig", "themes", "files"}


def test_texts_of_the_frame(html: str) -> None:
    assert "<title>Meridian Data Explorer · live demo</title>" in html
    assert "mountBanner({ repoUrl: REPO_URL })" in html
    assert "const REPO_URL = 'https://github.com/HARISPAARTAN/data-explorer-app';" in html
    for text in FALLBACK:
        assert html.count(text) == 2, text  # the template and <noscript>
    assert html.count(LOADING) == 1
    assert html.count(FOOTER) == 3
    assert 'src="assets/upload-1440.png"' in html and 'src="assets/visualise-1440.png"' in html


def test_stlite_is_requested_only_after_the_checks(html: str) -> None:
    script = html[html.index('<script type="module">') :]
    assert script.index("typeof WebAssembly !== 'object'") < script.index("import(STLITE_JS)")
    assert script.index("supportsModuleWorkers()") < script.index("import(STLITE_JS)")
    assert "get type()" in script
    head = html[: html.index("</head>")]
    assert "cdn.jsdelivr.net" not in head


def test_no_csp_no_sri_no_storage_writes_no_cookies(html: str) -> None:
    lowered = html.lower()
    assert "content-security-policy" not in lowered and "integrity=" not in lowered
    assert "pyodideurl" not in lowered
    assert (
        "localstorage" not in lowered and "sessionstorage" not in lowered and "document.cookie" not in lowered
    )


def test_outside_hosts(html: str) -> None:
    hosts = set(re.findall(r"https://([^/'\"\s]+)", html))
    assert hosts == {"cdn.jsdelivr.net", "github.com"}


def test_local_references_exist(repo_root: Path, html: str) -> None:
    web = repo_root / "web"
    for reference in (
        "kit/fonts/fonts.css",
        "kit/tokens.css",
        "kit/base.css",
        "kit/theme-boot.js",
        "kit/kit.js",
    ):
        assert reference in html and (web / reference).is_file(), reference
