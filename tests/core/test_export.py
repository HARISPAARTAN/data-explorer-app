"""core/export.py: both CSV dialects byte for byte, round trips, escaping, names, profiles, golden files."""

from __future__ import annotations

import dataclasses
import io
import json
import os
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from data_explorer.core.export import (
    FORMULA_PREFIXES,
    GENERATOR,
    export_file_name,
    profile_json,
    profile_markdown,
    profile_payload,
    to_csv_bytes,
)
from data_explorer.core.filters import SortKey, ViewSpec, parse_filter
from data_explorer.core.io import load_sample, load_table
from data_explorer.core.profile import profile_dataset
from data_explorer.core.quality import quality_report

GOLDEN = Path(__file__).resolve().parents[1] / "golden"


@pytest.fixture
def mixed() -> pd.DataFrame:
    days = pd.Series(
        ["2025-03-01", "2025-03-02", None, "2025-03-04", "2025-03-05", "2025-03-06", "2025-03-07"]
    )
    return pd.DataFrame(
        {
            "name": pd.Series(["=SUM(A1)", "+1", "-x", "@me", "\tx", "plain", None], dtype="str"),
            "n": [-1, 2, 3, 4, 5, 6, 7],
            "x": [1.5, -0.25, None, 0.0, 2.0, 3.0, 4.0],
            "day": pd.to_datetime(days, format="%Y-%m-%d").astype("datetime64[us]"),
        }
    )


def test_comma_dialect_bytes(mixed: pd.DataFrame) -> None:
    before = mixed.copy()
    data = to_csv_bytes(mixed)
    pd.testing.assert_frame_equal(mixed, before)
    assert data == (
        b"name,n,x,day\n"
        b"'=SUM(A1),-1,1.5,2025-03-01\n"
        b"'+1,2,-0.25,2025-03-02\n"
        b"'-x,3,,\n"
        b"'@me,4,0.0,2025-03-04\n"
        b"'\tx,5,2.0,2025-03-05\n"
        b"plain,6,3.0,2025-03-06\n"
        b",7,4.0,2025-03-07\n"
    )


def test_semicolon_dialect_bytes(mixed: pd.DataFrame) -> None:
    data = to_csv_bytes(mixed, "semicolon")
    assert data.startswith(b"\xef\xbb\xbf")
    lines = data[3:].decode("utf-8").split("\n")
    assert lines[:4] == ["name;n;x;day", "'=SUM(A1);-1;1,5;2025-03-01", "'+1;2;-0,25;2025-03-02", "'-x;3;;"]
    assert lines[4] == "'@me;4;0,0;2025-03-04" and lines[-1] == ""


def test_escaping_switch_carriage_return_and_numbers(mixed: pd.DataFrame) -> None:
    raw = to_csv_bytes(mixed, escape_formulas=False).decode("utf-8")
    assert "\n=SUM(A1),-1," in raw and "\n-x,3,," in raw
    carriage = to_csv_bytes(pd.DataFrame({"t": pd.Series(["\rx", "ok"], dtype="str")}))
    assert b"'\rx" in carriage and FORMULA_PREFIXES[-1] == "\r"
    numbers = to_csv_bytes(pd.DataFrame({"v": [-5, 3]}))
    assert numbers == b"v\n-5\n3\n"


def test_other_column_types() -> None:
    df = pd.DataFrame(
        {
            "flag": [True, False],
            "count": pd.array([1, None], dtype="Int64"),
            "at": pd.Series(pd.to_datetime(["2025-03-01 08:30", "2025-03-02 00:00"])).astype(
                "datetime64[us]"
            ),
            "fine": pd.Series(pd.to_datetime(["2025-03-01 08:30:00.250", None])).astype("datetime64[us]"),
        }
    )
    assert to_csv_bytes(df).decode("utf-8") == (
        "flag,count,at,fine\nTrue,1,2025-03-01T08:30:00,2025-03-01T08:30:00.250000\nFalse,,2025-03-02T00:00:00,\n"
    )


def test_unknown_dialect(mixed: pd.DataFrame) -> None:
    with pytest.raises(ValueError, match="Unknown CSV dialect"):
        to_csv_bytes(mixed, "tab")  # type: ignore[arg-type]


texts = st.one_of(
    st.none(),
    st.text(
        st.characters(codec="utf-8", exclude_categories=("Cs", "Cc"))
        | st.sampled_from(list("\t\n=+-@;,\"' ")),
        min_size=1,
        max_size=8,
    ),
)
frames = st.integers(min_value=1, max_value=30).flatmap(
    lambda n: st.tuples(
        st.lists(st.integers(min_value=-(10**12), max_value=10**12), min_size=n, max_size=n),
        st.lists(st.one_of(st.none(), st.floats(min_value=-1e12, max_value=1e12)), min_size=n, max_size=n),
        st.lists(texts, min_size=n, max_size=n),
    )
)


@given(frames, st.sampled_from(["comma", "semicolon"]), st.booleans())
def test_csv_round_trip(
    columns: tuple[list[int], list[float | None], list[str | None]], dialect: str, escape: bool
) -> None:
    ints, floats, strings = columns
    df = pd.DataFrame(
        {"n": ints, "f": pd.Series(floats, dtype="float64"), "t": pd.Series(strings, dtype="str")}
    )
    data = to_csv_bytes(df, dialect, escape)  # type: ignore[arg-type]
    sep, decimal, encoding = (",", ".", "utf-8") if dialect == "comma" else (";", ",", "utf-8-sig")
    back = pd.read_csv(
        io.BytesIO(data),
        sep=sep,
        decimal=decimal,
        encoding=encoding,
        dtype={"t": "str"},
        keep_default_na=False,
        na_values={"f": [""]},
    )
    assert back["n"].tolist() == ints
    pd.testing.assert_series_equal(back["f"], df["f"], check_exact=False, rtol=1e-12, atol=1e-12)
    expected = [
        "" if v is None else ("'" + v if escape and v.startswith(FORMULA_PREFIXES) else v) for v in strings
    ]
    assert back["t"].tolist() == expected


@pytest.mark.parametrize(
    ("source", "kind", "expected"),
    [
        ("retail_orders.csv", "csv", "retail_orders_filtered.csv"),
        ("client_survey.xlsx", "json", "client_survey_profile.json"),
        ("Sales Report (final).xlsx", "md", "Sales_Report_final_profile.md"),
        ("../../etc/passwd.csv", "csv", "passwd_filtered.csv"),
        ("C:\\Users\\someone\\data set.csv", "csv", "data_set_filtered.csv"),
        ("ünïcode.csv", "md", "n_code_profile.md"),
        ("....csv", "csv", "dataset_filtered.csv"),
        ("x" * 80 + ".csv", "json", "x" * 60 + "_profile.json"),
    ],
)
def test_export_file_name(source: str, kind: str, expected: str) -> None:
    assert export_file_name(source, kind) == expected  # type: ignore[arg-type]


def test_export_file_name_rejects_unknown_kinds() -> None:
    with pytest.raises(ValueError, match="Unknown export kind"):
        export_file_name("a.csv", "xlsx")  # type: ignore[arg-type]


@pytest.fixture
def loaded(fixture_bytes: Callable[[str], bytes]) -> tuple[pd.DataFrame, object]:
    return load_table(fixture_bytes("utf8_comma.csv"), "utf8_comma.csv")


def test_profile_payload_structure(loaded: tuple[pd.DataFrame, object]) -> None:
    df, report = loaded
    view = ViewSpec(parse_filter("`amount` > 12"), ("city", "amount"), (SortKey("amount", True),))
    payload = profile_payload(report, profile_dataset(df), quality_report(df), view, 17, scope="view")  # type: ignore[arg-type]
    assert payload["schema_version"] == 1 and payload["generator"] == GENERATOR == "data-explorer-app 0.1.0"
    assert sorted(payload) == [
        "columns",
        "generator",
        "quality",
        "schema_version",
        "shape",
        "source",
        "view",
        "warnings",
    ]
    assert "warnings" not in payload["source"]  # type: ignore[operator]
    assert payload["view"] == {
        "filter_text": "`amount` > 12",
        "columns": ["city", "amount"],
        "sort": [{"column": "amount", "descending": True}],
        "rows_in_view": 17,
        "scope": "view",
    }
    assert "memory_bytes" not in json.dumps(payload)
    text = profile_json(report, profile_dataset(df), quality_report(df), view, 17, scope="view")  # type: ignore[arg-type]
    assert json.loads(text) == payload and text.endswith("}\n")
    assert text == json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    with pytest.raises(ValueError, match="Unknown profile scope"):
        profile_json(report, profile_dataset(df), quality_report(df), view, 17, scope="all")  # type: ignore[arg-type]


def test_markdown_sections_and_escaping(fixture_bytes: Callable[[str], bytes]) -> None:
    df = pd.DataFrame({"a|b": pd.Series(["x|y", "x|y", "z"], dtype="str"), "n": [1, 1, 2]})
    _, base = load_table(fixture_bytes("two_numeric_columns.csv"), "two_numeric_columns.csv")
    report = dataclasses.replace(base, file_name="pipes.csv")
    text = profile_markdown(report, profile_dataset(df), quality_report(df), ViewSpec(), 3)
    headings = [line for line in text.splitlines() if line.startswith("#")]
    assert headings == [
        "# Data profile: pipes.csv",
        "## Source",
        "## Shape",
        "## View",
        "## Columns",
        "## Missing values",
        "## Duplicates",
        "## Constant columns",
        "## Outliers (IQR rule, k = 1.5)",
    ]
    assert "| a\\|b | categorical |" in text and "x\\|y (2)" in text
    assert "- Filter: none, all rows are in the view" in text and "No missing values." in text
    assert "1 duplicate rows in 1 groups, compared on all columns." in text
    filtered = profile_markdown(
        report, profile_dataset(df), quality_report(df), ViewSpec(parse_filter("`n` = 1")), 2
    )
    assert "- Filter: `` `n` = 1 ``" in filtered and "- Rows in view: 2" in filtered


def test_profiles_are_deterministic(samples: dict[str, tuple[pd.DataFrame, object]]) -> None:
    df, report = samples["sensor_readings"]
    args = (report, profile_dataset(df), quality_report(df), ViewSpec(), len(df))
    assert profile_json(*args) == profile_json(*args)  # type: ignore[arg-type]
    assert profile_markdown(*args) == profile_markdown(*args)  # type: ignore[arg-type]


def golden(name: str, text: str) -> None:
    path = GOLDEN / name
    if os.environ.get("UPDATE_GOLDEN") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    assert path.exists(), (
        f"{name} is missing: run UPDATE_GOLDEN=1 uv run pytest tests/core/test_export.py and review it"
    )
    assert text == path.read_text(encoding="utf-8")


def test_retail_profile_matches_the_golden_files() -> None:
    df, report = load_sample("retail_orders")
    args = (report, profile_dataset(df), quality_report(df), ViewSpec(), len(df))
    golden("retail_orders_profile.json", profile_json(*args))
    golden("retail_orders_profile.md", profile_markdown(*args))
