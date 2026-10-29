"""The Dockerfile and .dockerignore keep the documented image layout (Docker itself runs only in CI)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

DIGEST = re.compile(r"@sha256:[0-9a-f]{64}\b")


@pytest.fixture(scope="module")
def dockerfile(repo_root: Path) -> str:
    return (repo_root / "Dockerfile").read_text(encoding="utf-8")


def instructions(text: str) -> list[str]:
    joined = re.sub(r"\\\n\s*", " ", text)
    return [
        line.strip() for line in joined.splitlines() if line.strip() and not line.lstrip().startswith("#")
    ]


def test_every_image_is_pinned_by_digest(dockerfile: str) -> None:
    images = [
        line.split()[1] for line in instructions(dockerfile) if line.startswith("FROM ") and "@" in line
    ] + re.findall(r"--from=(\S+@sha256:\S+)", dockerfile)
    assert len(images) == 2
    assert all(DIGEST.search(image) for image in images)
    assert images[0].startswith("python:3.12-slim@") and images[1].startswith("ghcr.io/astral-sh/uv:0.11.8@")
    for image in images:
        digest = image.split("@", 1)[1]
        assert dockerfile.count(digest) == 2, (
            f"{digest} must appear in the header comment and in the instruction"
        )
    assert re.search(r"resolved \d{4}-\d{2}-\d{2}", dockerfile)


def test_stages_user_and_entrypoint(dockerfile: str, repo_root: Path) -> None:
    lines = instructions(dockerfile)
    assert [line for line in lines if line.startswith("FROM ")][1:] == ["FROM base AS deps", "FROM base"]
    assert (
        "ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never UV_PROJECT_ENVIRONMENT=/app/.venv"
        in lines
    )
    assert "RUN uv sync --locked --no-dev --no-install-project --no-editable" in lines
    assert "RUN uv sync --locked --no-dev --no-editable" in lines
    assert "USER app" in lines and any("--uid 10001" in line and line.endswith(" app") for line in lines)
    assert "EXPOSE 8501" in lines
    assert "COPY .streamlit/config.toml ./.streamlit/config.toml" in lines
    entry = next(line for line in lines if line.startswith("ENTRYPOINT "))
    assert entry == (
        'ENTRYPOINT ["streamlit", "run", "src/data_explorer/app/streamlit_app.py", '
        '"--server.port=8501", "--server.address=0.0.0.0", "--server.headless=true"]'
    )
    assert (repo_root / "src/data_explorer/app/streamlit_app.py").is_file()


def test_layer_order(dockerfile: str) -> None:
    lines = instructions(dockerfile)
    syncs = [n for n, line in enumerate(lines) if line.startswith("RUN uv sync ")]
    assert len(syncs) == 2
    manifest = lines.index("COPY pyproject.toml uv.lock ./")
    sources = lines.index("COPY src ./src")
    assert manifest < syncs[0] < sources < syncs[1]
    useradd = next(n for n, line in enumerate(lines) if line.startswith("RUN useradd "))
    assert useradd < lines.index("USER app")


def test_health_check_uses_python(dockerfile: str) -> None:
    health = next(line for line in instructions(dockerfile) if line.startswith("HEALTHCHECK "))
    assert "--interval=30s --timeout=5s --start-period=20s" in health
    assert "CMD python -c" in health and "http://127.0.0.1:8501/_stcore/health" in health
    assert "curl" not in health


def test_env_and_no_secrets(dockerfile: str) -> None:
    env = " ".join(line for line in instructions(dockerfile) if line.startswith("ENV "))
    for setting in ("PATH=/app/.venv/bin:$PATH", "PYTHONUNBUFFERED=1", "DATA_EXPLORER_LOG_LEVEL=INFO"):
        assert setting in env
    assert not re.search(r"(?i)(token|secret|password)\s*=", dockerfile)


def test_dockerignore(repo_root: Path) -> None:
    entries = (repo_root / ".dockerignore").read_text(encoding="utf-8").split()
    for excluded in (".git", ".github", ".venv", "tests", "fixtures", "tools", "docs", "web"):
        assert excluded in entries
    for needed in ("src", "pyproject.toml", "uv.lock", "README.md", "LICENSE", ".streamlit"):
        assert needed not in entries
