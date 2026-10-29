"""The workflows and Dependabot keep the documented CI contract (read as text, no YAML parser)."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

# "uses: owner/name@ref", optionally followed by a "# v1.2.3" comment that names the tag a commit pin stands for.
USES = re.compile(r"^[ \t]*-?[ \t]*uses:[ \t]*(\S+)[ \t]*(?:#[^\n]*)?$", re.M)
ACTION_REF = re.compile(r"[\w.-]+/[\w./-]+@(?:v\d+|[0-9a-f]{40})")

TIMEOUTS = {
    "ci": {"lint": 15, "test": 30, "core-py314": 20, "docker": 20, "stlite-local": 30},
    "pages": {"deploy": 15, "smoke": 30},
}


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


def steps_of(text: str, action: str) -> list[str]:
    """The step bodies (up to the next step) that follow each ``uses: <action>@``."""
    return [part.split("\n      - ", 1)[0] for part in text.split(f"uses: {action}@")[1:]]


def test_only_the_two_documented_workflows_exist(repo_root: Path) -> None:
    folder = repo_root / ".github" / "workflows"
    assert sorted(path.name for path in folder.iterdir()) == ["ci.yml", "pages.yml"]


@pytest.mark.parametrize("name", ["ci", "pages"])
def test_every_job_has_the_expected_timeout(name: str, ci: str, pages: str) -> None:
    text = ci if name == "ci" else pages
    assert jobs(text) == list(TIMEOUTS[name])
    for job_name, minutes in TIMEOUTS[name].items():
        found = re.findall(r"^    timeout-minutes: (\d+)$", job(text, job_name), re.M)
        assert found == [str(minutes)], job_name


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
    setups = re.findall(
        r"uses: astral-sh/setup-uv@(?:v\d+|[0-9a-f]{40})[ \t]*(?:#[^\n]*)?\n\s+with:\n\s+version: \"([\d.]+)\"",
        ci,
    )
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
    curls = [line for line in docker.splitlines() if "curl " in line]
    assert len(curls) == 3 and all("--max-time 5" in line for line in curls)


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


@pytest.mark.parametrize(
    ("workflow", "artifact", "folder"),
    [("ci", "stlite-smoke", "smoke"), ("pages", "stlite-smoke-live", "smoke-live")],
)
def test_smoke_artifact_is_the_out_directory(
    workflow: str, artifact: str, folder: str, ci: str, pages: str
) -> None:
    text = job(ci, "stlite-local") if workflow == "ci" else job(pages, "smoke")
    (upload,) = steps_of(text, "actions/upload-artifact")
    out = re.findall(r"^\s+OUT: (.+)$", text, re.M)
    assert out == ["${{ runner.temp }}/" + folder]
    assert re.findall(r"^\s+name: (\S+)$", upload, re.M) == [artifact]
    assert re.findall(r"^\s+path: (.+)$", upload, re.M) == out
    assert re.findall(r"^\s+retention-days: (\d+)$", upload, re.M) == ["14"]


def test_local_smoke_names_its_url(ci: str) -> None:
    stlite = job(ci, "stlite-local")
    assert "          URL: http://127.0.0.1:8000/\n" in stlite
    assert "-d web" in stlite and "--bind 127.0.0.1" in stlite


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
    assert actions and len(actions) == text.count("uses:")
    for action in actions:
        assert ACTION_REF.fullmatch(action), action
    for forbidden in ["pull_request_target", "secrets.", "GITHUB_TOKEN"]:
        assert forbidden not in text, forbidden


@pytest.mark.parametrize("name", ["ci", "pages"])
def test_write_permissions_only_in_the_pages_deploy_job(name: str, ci: str, pages: str) -> None:
    text = ci if name == "ci" else pages
    if name == "pages":
        text = text.replace(job(pages, "deploy"), "")
    assert re.search(r":[ \t]*write", text) is None


@pytest.mark.parametrize("name", ["ci", "pages"])
def test_every_checkout_drops_its_credentials(name: str, ci: str, pages: str) -> None:
    text = ci if name == "ci" else pages
    checkouts = steps_of(text, "actions/checkout")
    assert len(checkouts) == text.count("actions/checkout@") == (6 if name == "ci" else 2)
    for step in checkouts:
        assert re.search(r"^ {10}persist-credentials: false$", step, re.M), step


def test_concurrency(ci: str, pages: str) -> None:
    assert "  cancel-in-progress: ${{ github.event_name == 'pull_request' }}\n" in ci
    assert "  group: pages\n  cancel-in-progress: false\n" in pages


def test_dependabot(dependabot: str) -> None:
    ecosystems = re.findall(r"package-ecosystem: (\S+)", dependabot)
    assert ecosystems == ["uv", "github-actions", "docker"]
    uv_block = dependabot.split("package-ecosystem: github-actions")[0]
    for name in ["streamlit", "pandas", "altair", "openpyxl"]:
        assert f"- dependency-name: {name}\n" in uv_block, name
    assert dependabot.count("interval: weekly") == 3


def test_dependabot_prefixes_and_action_group(dependabot: str) -> None:
    blocks = {
        name: block
        for block in dependabot.split("\n  - ")[1:]
        for name in re.findall(r"^package-ecosystem: (\S+)", block)
    }
    prefixes = {
        name: re.findall(r"^    commit-message:\n      prefix: \"([^\"]+)\"$", block, re.M)
        for name, block in blocks.items()
    }
    assert prefixes == {"uv": ["build(deps)"], "github-actions": ["ci"], "docker": ["build(deps)"]}
    assert 'patterns: ["*"]' in blocks["github-actions"]  # one PR for all action bumps
