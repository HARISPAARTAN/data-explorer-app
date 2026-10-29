"""The workflows and Dependabot keep the documented CI contract (read as text, no YAML parser)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

USES = re.compile(r"^\s*-?\s*uses:\s*(\S+)\s*$", re.M)


@pytest.fixture(scope="module")
def ci(repo_root: Path) -> str:
    return (repo_root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def pages(repo_root: Path) -> str:
    return (repo_root / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def dependabot(repo_root: Path) -> str:
    return (repo_root / ".github" / "dependabot.yml").read_text(encoding="utf-8")


def jobs(text: str) -> list[str]:
    body = text.split("\njobs:\n", 1)[1]
    return re.findall(r"^  ([a-z0-9-]+):\s*$", body, re.M)


def job(text: str, name: str) -> str:
    body = text.split("\njobs:\n", 1)[1]
    match = re.search(rf"^  {re.escape(name)}:\s*$(.*?)(?=^  [a-z0-9-]+:\s*$|\Z)", body, re.M | re.S)
    assert match is not None, name
    return match.group(1)


def test_ci_jobs_and_matrix(ci: str) -> None:
    assert jobs(ci) == ["lint", "test", "core-py314", "docker", "stlite-local"]
    test = job(ci, "test")
    assert "os: [ubuntu-24.04, windows-latest]" in test
    assert 'python: ["3.11", "3.12", "3.13"]' in test
    assert "fail-fast: false" in test
    assert "uv run pytest -q" in test
    assert 'python-version: "3.14"' in job(ci, "core-py314")
    assert "uv run --python 3.14 pytest tests/core -q" in job(ci, "core-py314")
    for name in ["lint", "core-py314", "docker", "stlite-local"]:
        assert "runs-on: ubuntu-24.04" in job(ci, name), name


def test_lint_runs_every_static_check(ci: str, tool: Callable[[str], ModuleType]) -> None:
    lint = job(ci, "lint")
    for command in [
        "uv sync --locked",
        "uv run ruff check .",
        "uv run ruff format --check .",
        "uv run mypy",
        "uv run python tools/sync_web.py --check",
        "uv run python tools/sync_kit.py --check --kit-dir .kit-src/dist",
        "uv run python tools/checks/scrub.py",
    ]:
        assert command in lint, command
    assert "fetch-depth: 0" in lint  # the scrub reads every commit message
    assert "repository: HARISPAARTAN/portfolio-kit" in lint
    assert f"ref: {tool('tools/sync_kit.py').KIT_TAG}" in lint
    assert "path: .kit-src" in lint


def test_one_uv_version_everywhere(ci: str, repo_root: Path) -> None:
    dockerfile = (repo_root / "Dockerfile").read_text(encoding="utf-8")
    docker_uv = re.search(r"ghcr\.io/astral-sh/uv:(\d+\.\d+\.\d+)@", dockerfile)
    assert docker_uv is not None
    setups = re.findall(r"uses: astral-sh/setup-uv@v\d+\n\s+with:\n\s+version: \"([\d.]+)\"", ci)
    assert len(setups) == ci.count("astral-sh/setup-uv@") == 3
    assert set(setups) == {docker_uv.group(1)}


def test_every_uv_sync_uses_the_lock(ci: str) -> None:
    syncs = re.findall(r"uv sync[^\n]*", ci)
    assert syncs and all("--locked" in line for line in syncs)


def test_docker_job(ci: str) -> None:
    docker = job(ci, "docker")
    assert "docker build -t data-explorer-app:ci ." in docker
    assert "http://127.0.0.1:8501/_stcore/health" in docker
    assert "seq 1 60" in docker
    assert "docker logs" in docker and "docker rm -f" in docker
    assert docker.count("if: always()") == 2


@pytest.mark.parametrize("workflow", ["ci", "pages"])
def test_smoke_jobs(workflow: str, ci: str, pages: str) -> None:
    text = job(ci, "stlite-local") if workflow == "ci" else job(pages, "smoke")
    assert "node-version: 22" in text
    assert "npm install --no-save --no-audit --no-fund playwright@1.64.1" in text
    assert "npx playwright install --with-deps chromium" in text
    assert "node tools/checks/stlite_smoke.mjs" in text
    assert "OUT: ${{ runner.temp }}/smoke" in text
    assert "actions/upload-artifact@" in text and "if: always()" in text
    assert "PLAYWRIGHT_FROM" not in text


def test_pages_deploys_web_only(pages: str) -> None:
    assert jobs(pages) == ["deploy", "smoke"]
    deploy = job(pages, "deploy")
    assert "python3 tools/sync_web.py --check" in deploy
    assert "path: web\n" in deploy
    assert "pages: write" in deploy and "id-token: write" in deploy
    assert "uses: actions/deploy-pages@" in deploy
    smoke = job(pages, "smoke")
    assert "needs: deploy" in smoke
    assert "URL: ${{ needs.deploy.outputs.page_url }}" in smoke


@pytest.mark.parametrize("name", ["ci", "pages"])
def test_permissions_actions_and_secrets(name: str, ci: str, pages: str) -> None:
    text = ci if name == "ci" else pages
    assert "\npermissions:\n  contents: read\n" in text
    actions = USES.findall(text)
    assert actions
    for action in actions:
        assert re.fullmatch(r"[\w.-]+/[\w./-]+@v\d+", action), action
    assert "secrets." not in text and "GITHUB_TOKEN" not in text


def test_dependabot(dependabot: str) -> None:
    ecosystems = re.findall(r"package-ecosystem: (\S+)", dependabot)
    assert ecosystems == ["uv", "github-actions", "docker"]
    uv_block = dependabot.split("package-ecosystem: github-actions")[0]
    for name in ["streamlit", "pandas", "altair", "openpyxl"]:
        assert f"- dependency-name: {name}\n" in uv_block, name
    assert dependabot.count("interval: weekly") == 3
