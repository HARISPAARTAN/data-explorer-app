"""The docs agree with the code: samples, environment variables, versions, mounted files, filter JSON, ADRs."""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from data_explorer import _versions
from data_explorer.core.filters import SortKey, ViewSpec, parse_filter, view_to_json
from data_explorer.core.io import SAMPLES, load_sample
from data_explorer.core.profile import profile_dataset

ADRS = [
    "0001-stlite-for-the-live-demo.md",
    "0002-pure-core-thin-streamlit-shell.md",
    "0003-flat-filter-grammar.md",
    "0004-browser-server-version-parity.md",
    "0005-text-only-downloads.md",
]
ROW = re.compile(r"^\| `([^`]+)` \| (numeric|datetime|boolean|categorical|text) \|", re.M)
SVG = "{http://www.w3.org/2000/svg}"


def read(repo_root: Path, name: str) -> str:
    return (repo_root / "docs" / name).read_text(encoding="utf-8")


def section(text: str, heading: str) -> str:
    start = text.index(f"\n{heading}\n") + 1
    ends = [pos for pos in (text.find("\n## ", start), text.find("\n### ", start)) if pos != -1]
    return text[start : min(ends) if ends else len(text)]


@pytest.mark.parametrize("key", sorted(SAMPLES))
def test_data_model_describes_each_sample(repo_root: Path, key: str) -> None:
    info = SAMPLES[key]
    text = section(read(repo_root, "data-model.md"), f"### {info.title} (`{info.file_name}`)")
    df, _ = load_sample(key)
    rows = ROW.findall(text)
    assert [name for name, _ in rows] == list(df.columns)
    assert dict(rows) == {column.name: column.kind for column in profile_dataset(df).columns}
    assert f"{len(df):,} rows × {len(df.columns)} columns" in text
    for defect in info.defects:
        assert f"- {defect}\n" in text, defect


def test_filter_json_example(repo_root: Path) -> None:
    text = section(read(repo_root, "data-model.md"), "## Filter JSON")
    blocks = re.findall(r"```(?:text|json)\n(.*?)\n```", text, re.S)
    assert len(blocks) == 3
    view = ViewSpec(parse_filter(blocks[0]), ("store", "units"), (SortKey("units", True),))
    assert blocks[1] == view_to_json(view)
    assert json.loads(blocks[2]) == json.loads(blocks[1])


def test_handover_names_every_environment_variable(repo_root: Path) -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((repo_root / "src" / "data_explorer").rglob("*.py"))
    )
    names = set(re.findall(r"DATA_EXPLORER_[A-Z_]+", source))
    assert names == {
        "DATA_EXPLORER_MAX_MB",
        "DATA_EXPLORER_MAX_ROWS",
        "DATA_EXPLORER_MAX_COLS",
        "DATA_EXPLORER_LOG_LEVEL",
    }
    handover = section(read(repo_root, "handover.md"), "## Environment variables")
    for name in names:
        assert f"| `{name}` |" in handover, name


@pytest.mark.parametrize("name", ["handover.md", "adr/0004-browser-server-version-parity.md"])
def test_pinned_versions_are_named(repo_root: Path, name: str) -> None:
    text = read(repo_root, name)
    for fact in [
        f"@stlite/browser@{_versions.STLITE}",
        f"Pyodide {_versions.PYODIDE}",
        f"Python {_versions.PYODIDE_PYTHON}",
        f"Streamlit {_versions.STREAMLIT}",
        f"pandas {_versions.PANDAS}",
        f"Altair {_versions.ALTAIR}",
        f"openpyxl {_versions.OPENPYXL}",
    ]:
        assert fact in text, fact


def test_architecture_lists_the_mounted_files(repo_root: Path) -> None:
    html = (repo_root / "web" / "index.html").read_text(encoding="utf-8")
    block = re.search(r'<script type="application/json" id="app-config">(.*?)</script>', html, re.S)
    assert block is not None
    files = json.loads(block.group(1))["files"]
    text = section(read(repo_root, "architecture.md"), "## Two runtimes")
    for browser_path in files:
        assert f"| `{browser_path}` |" in text, browser_path
    assert text.count("\n| `") == len(files) == 22


@pytest.mark.parametrize("name", ADRS)
def test_adr_layout(repo_root: Path, name: str) -> None:
    text = read(repo_root, f"adr/{name}")
    assert text.startswith(f"# ADR {name[:4]}: ")
    assert "\nStatus: accepted (2026-10-29)\n" in text
    for heading in ["## Context", "## Decision", "## Consequences", "## Alternatives considered"]:
        assert f"\n{heading}\n" in text, heading


def test_exactly_the_five_adrs(repo_root: Path) -> None:
    assert sorted(path.name for path in (repo_root / "docs" / "adr").iterdir()) == ADRS


def test_architecture_diagram(repo_root: Path) -> None:
    root = ET.parse(repo_root / "docs" / "architecture.svg").getroot()
    assert root.tag == f"{SVG}svg" and root.get("viewBox") == "0 0 960 520"
    assert root.find(f"{SVG}title") is not None and root.find(f"{SVG}desc") is not None
    texts = " ".join("".join(node.itertext()) for node in root.iter(f"{SVG}text"))
    for label in [
        f"Streamlit {_versions.STREAMLIT}",
        f"stlite {_versions.STLITE}",
        f"Pyodide {_versions.PYODIDE}",
        "app/",
        "core/",
        "CSV or XLSX bytes",
        "CSV, JSON, Markdown",
        "tools/sync_web.py, checked in CI",
        "cdn.jsdelivr.net",
    ]:
        assert label in texts, label
