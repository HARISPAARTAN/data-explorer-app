"""core/quality.py: fences, skipping, duplicates, constants, the missing matrix."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

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


def test_fences_on_one_to_ten_and_a_hundred() -> None:
    df = pd.DataFrame({"v": [*range(1, 11), 100]})
    (summary,) = iqr_outliers(df)
    assert (summary.q1, summary.q3, summary.iqr, summary.lower, summary.upper) == (3.5, 8.5, 5.0, -4.0, 16.0)
    assert (summary.n_low, summary.n_high) == (0, 1) and summary.pct == pytest.approx(100 / 11)
    assert outlier_rows(df, "v")["v"].tolist() == [100]
    (wide,) = iqr_outliers(df, k=5.0)
    assert wide.upper == 33.5 and wide.n_high == 1


def test_skips_zero_iqr_short_and_boolean_columns() -> None:
    df = pd.DataFrame(
        {"flat": [5] * 10 + [6], "short": [1.0, 2.0, 3.0] + [np.nan] * 8, "flag": [True, False] * 5 + [True]}
    )
    assert iqr_outliers(df) == ()
    assert zero_iqr_columns(df) == ("flat",)
    assert outlier_rows(df, "flat").empty


def test_outlier_argument_checks() -> None:
    df = pd.DataFrame({"v": [1, 2, 3, 4, 5], "t": list("abcde")})
    for k in (0.4, 5.1):
        with pytest.raises(ValueError, match="between 0.5 and 5.0"):
            iqr_outliers(df, k=k)
    with pytest.raises(ValueError, match="Unknown column"):
        outlier_rows(df, "nope")
    with pytest.raises(ValueError, match="not numeric"):
        outlier_rows(df, "t")


def test_missing_summary_order() -> None:
    df = pd.DataFrame({"a": [None, 1, 2], "b": [None, None, 1], "c": [1, 2, 3], "d": [None, 1, 1]})
    summary = missing_summary(df)
    assert summary["column"].tolist() == ["b", "a", "d"]
    assert summary["missing"].tolist() == [2, 1, 1]
    assert summary["missing_pct"].tolist() == pytest.approx([200 / 3, 100 / 3, 100 / 3])
    assert missing_summary(pd.DataFrame({"x": [1]})).empty


def test_missing_matrix_blocks_and_columns() -> None:
    df = pd.DataFrame({"a": [None] * 3 + [1] * 7, "b": [1] * 8 + [None, None], "c": [1] * 10})
    matrix = missing_matrix(df, bins=4)
    blocks = matrix.drop_duplicates("bin")[["bin", "row_from", "row_to"]].values.tolist()
    assert blocks == [[1, 1, 3], [2, 4, 6], [3, 7, 8], [4, 9, 10]]
    a = matrix[matrix["column"] == "a"]["missing_share"].tolist()
    b = matrix[matrix["column"] == "b"]["missing_share"].tolist()
    assert a == [1.0, 0.0, 0.0, 0.0] and b == [0.0, 0.0, 0.0, 1.0]
    narrow = missing_matrix(df, bins=4, max_columns=1)
    assert narrow["column"].unique().tolist() == ["a"]
    assert len(missing_matrix(df.iloc[:3], bins=100)) == 9
    assert missing_matrix(df.iloc[0:0]).empty
    with pytest.raises(ValueError):
        missing_matrix(df, bins=0)


def test_duplicates_all_columns_and_subset(small_df: pd.DataFrame) -> None:
    report = duplicates(small_df)
    assert (report.subset, report.duplicate_rows, report.groups) == ((), 1, 1)
    assert report.sample_rows.index.tolist() == [1, 11]
    df = pd.DataFrame({"k": ["x", "y", "x", "x", "y", "z"], "v": [1, 2, 3, 1, 2, 9]})
    subset = duplicates(df, subset=("k",))
    assert (subset.duplicate_rows, subset.groups) == (3, 2)
    assert subset.sample_rows["k"].tolist() == ["x", "x", "x", "y", "y"]
    assert duplicates(df, subset=("k",), sample=2).sample_rows.shape[0] == 2
    assert subset.to_dict() == {"subset": ["k"], "duplicate_rows": 3, "groups": 2}
    with pytest.raises(ValueError, match="Unknown column"):
        duplicates(df, subset=("nope",))


def test_constant_columns() -> None:
    df = pd.DataFrame({"c": ["IT"] * 3, "n": [None, None, None], "v": [1, 2, 3], "w": [2025, 2025, None]})
    result = {item.name: (item.value, item.all_missing) for item in constant_columns(df)}
    assert result == {"c": ("IT", False), "n": (None, True), "w": (2025.0, False)}


def test_quality_report_bundle_is_json_and_pure(small_df: pd.DataFrame) -> None:
    before = small_df.copy()
    report = quality_report(small_df, k=2.0, subset=("colour",))
    pd.testing.assert_frame_equal(small_df, before)
    payload = report.to_dict()
    json.dumps(payload, allow_nan=False)
    assert payload["outliers"]["k"] == 2.0 and payload["duplicates"]["subset"] == ["colour"]
    assert [row["column"] for row in payload["missing"]] == ["amount", "day", "flag", "colour"]
