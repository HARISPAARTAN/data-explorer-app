"""core never imports streamlit, imports only allowed packages and never changes its input frames."""

from __future__ import annotations

import ast
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from data_explorer.core.charts import bar, correlation_heatmap, histogram, line, scatter
from data_explorer.core.export import to_csv_bytes
from data_explorer.core.filters import SortKey, ViewSpec, apply_filter, apply_view, parse_filter
from data_explorer.core.profile import profile_dataset
from data_explorer.core.quality import (
    constant_columns,
    duplicates,
    iqr_outliers,
    missing_matrix,
    missing_summary,
    outlier_rows,
    quality_report,
    zero_iqr_columns,
)

CORE_MODULES = ["io", "profile", "quality", "filters", "charts", "export"]
ALLOWED = {"numpy", "pandas", "altair", "openpyxl", "data_explorer"}


def test_core_imports_with_streamlit_blocked() -> None:
    code = (
        "import sys\n"
        "sys.modules['streamlit'] = None\n"
        + "".join(f"import data_explorer.core.{name}\n" for name in CORE_MODULES)
        + "print('core ok')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "core ok"


def imported(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                names.append("." * node.level + (node.module or ""))
            elif node.module:
                names.append(node.module)
                names.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def test_core_imports_only_allowed_packages(repo_root: Path) -> None:
    files = sorted((repo_root / "src" / "data_explorer" / "core").glob("*.py"))
    assert files, "no files scanned"
    for path in files:
        for name in imported(path):
            if name.startswith("."):
                assert not name.startswith(".."), f"{path.name} imports {name}"
                continue
            top = name.split(".")[0]
            if top == "data_explorer":
                assert (
                    name in ("data_explorer", "data_explorer.__version__")
                    or name == "data_explorer.core"
                    or name.startswith("data_explorer.core.")
                ), f"{path.name} imports {name}"
            assert top in sys.stdlib_module_names or top in ALLOWED, f"{path.name} imports {name}"


def test_app_code_never_imports_streamlit_testing(repo_root: Path) -> None:
    package = repo_root / "src" / "data_explorer"
    files = sorted(package.rglob("*.py"))
    assert files, "no files scanned"
    for path in files:
        names = imported(path)
        assert not [name for name in names if name.startswith("streamlit.testing")], path
    cli = package / "cli.py"
    if cli.exists():
        assert {name.split(".")[0] for name in imported(cli)} <= set(sys.stdlib_module_names) | {
            "click",
            "data_explorer",
        }


@pytest.fixture
def frame(small_df: pd.DataFrame) -> pd.DataFrame:
    return small_df.assign(twice=small_df["amount"] * 2)


CALLS: dict[str, Callable[[pd.DataFrame], Any]] = {
    "profile_dataset": profile_dataset,
    "missing_summary": missing_summary,
    "missing_matrix": lambda df: missing_matrix(df, bins=5),
    "duplicates": lambda df: duplicates(df, ("colour",)),
    "constant_columns": constant_columns,
    "iqr_outliers": iqr_outliers,
    "zero_iqr_columns": zero_iqr_columns,
    "outlier_rows": lambda df: outlier_rows(df, "amount"),
    "quality_report": quality_report,
    "apply_filter": lambda df: apply_filter(df, parse_filter('`amount` > 10 AND `colour` IN ("red")')),
    "apply_view": lambda df: apply_view(
        df, ViewSpec(columns=("colour", "amount"), sort=(SortKey("amount", True),))
    ),
    "histogram": lambda df: histogram(df, "amount", 5),
    "bar": lambda df: bar(df, "colour", "amount", "sum", 5),
    "line": lambda df: line(df, "day", "amount", "mean", "D", "colour"),
    "scatter": lambda df: scatter(df, "amount", "twice", "colour"),
    "correlation_heatmap": correlation_heatmap,
    "to_csv_bytes": lambda df: to_csv_bytes(df, "semicolon"),
}


@pytest.mark.parametrize("name", list(CALLS))
def test_public_functions_leave_their_input_unchanged(frame: pd.DataFrame, name: str) -> None:
    before = frame.copy(deep=True)
    CALLS[name](frame)
    pd.testing.assert_frame_equal(frame, before)
    assert list(frame.index) == list(before.index)
