"""Shared fixtures: repository paths, tool loading, fixture files, a small frame with known statistics and the samples."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Callable, Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import pandas as pd
import pytest
from hypothesis import settings

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
ENV_VARS = (
    "DATA_EXPLORER_MAX_MB",
    "DATA_EXPLORER_MAX_ROWS",
    "DATA_EXPLORER_MAX_COLS",
    "DATA_EXPLORER_LOG_LEVEL",
)

settings.register_profile("repo", deadline=None, derandomize=True, max_examples=100)
settings.load_profile("repo")


def _load_tool(relative: str) -> ModuleType:
    """Import a script under tools/ (not a package) from its path."""
    path = ROOT / relative
    name = "tool_" + path.stem.replace("-", "_")
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    for name in ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    yield


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return ROOT


@pytest.fixture(scope="session")
def tool() -> Callable[[str], ModuleType]:
    return _load_tool


@pytest.fixture(scope="session")
def fixture_bytes() -> Callable[[str], bytes]:
    def read(name: str) -> bytes:
        return (FIXTURES / name).read_bytes()

    return read


@pytest.fixture
def small_df() -> pd.DataFrame:
    """Twelve rows with known statistics: one missing value per column, row 11 repeats row 1."""
    days = (
        [f"2025-03-{day:02d}" for day in (1, 2, 3)] + [None] + [f"2025-03-{day:02d}" for day in range(5, 12)]
    )
    days.append("2025-03-02")
    return pd.DataFrame(
        {
            "amount": pd.Series(
                [10.0, 20.0, None, 0.0, -5.0, 15.0, 30.0, 25.0, 45.0, 50.0, 35.0, 20.0], dtype="float64"
            ),
            "day": pd.to_datetime(pd.Series(days), format="%Y-%m-%d").astype("datetime64[us]"),
            "flag": pd.array(
                [True, False, True, False, None, True, False, True, False, True, True, False], dtype="boolean"
            ),
            "colour": pd.Series(
                ["red", "blue", "green", "red", "blue", None, "red", "blue", "red", "green", "red", "blue"],
                dtype="str",
            ),
        }
    )


@pytest.fixture(scope="session")
def samples() -> dict[str, tuple[pd.DataFrame, Any]]:
    from data_explorer.core.io import SAMPLES, load_sample

    return {key: load_sample(key) for key in SAMPLES}


@pytest.fixture
def tight_limits() -> Any:
    from data_explorer.core.io import Limits

    return Limits(2_000, 50, 5)
