"""core/profile.py against hand computation on small_df."""

from __future__ import annotations

import json
import random
import statistics

import pandas as pd
import pytest

from data_explorer.core.profile import CATEGORICAL_MAX_UNIQUE, classify, profile_column, profile_dataset

AMOUNTS = [10.0, 20.0, 0.0, -5.0, 15.0, 30.0, 25.0, 45.0, 50.0, 35.0, 20.0]


def test_kinds(small_df: pd.DataFrame) -> None:
    assert [classify(small_df[c]) for c in small_df.columns] == [
        "numeric",
        "datetime",
        "boolean",
        "categorical",
    ]
    assert classify(pd.Series([True, False])) == "boolean"
    assert classify(pd.Series([1, None], dtype="Int64")) == "numeric"
    many = pd.Series([f"v{i}" for i in range(CATEGORICAL_MAX_UNIQUE + 1)], dtype="str")
    assert classify(many) == "text" and classify(many.iloc[:CATEGORICAL_MAX_UNIQUE]) == "categorical"


def test_numeric_statistics(small_df: pd.DataFrame) -> None:
    column = profile_column(small_df["amount"], "amount")
    assert (column.count, column.missing, column.unique) == (11, 1, 10)
    assert column.missing_pct == pytest.approx(100 / 12)
    stats = column.stats
    assert stats["mean"] == pytest.approx(statistics.mean(AMOUNTS))
    assert stats["std"] == pytest.approx(statistics.stdev(AMOUNTS))
    assert (stats["min"], stats["p25"], stats["median"], stats["p75"], stats["max"]) == (
        -5.0,
        12.5,
        20.0,
        32.5,
        50.0,
    )
    assert (stats["zeros"], stats["negatives"]) == (1, 1)
    assert column.top == ()


def test_integer_min_and_max_stay_integers() -> None:
    stats = profile_column(pd.Series([3, 1, 2]), "n").stats
    assert stats["min"] == 1 and isinstance(stats["min"], int) and isinstance(stats["max"], int)


def test_datetime_boolean_and_categorical(small_df: pd.DataFrame) -> None:
    day = profile_column(small_df["day"], "day")
    assert day.stats == {"min": "2025-03-01T00:00:00", "max": "2025-03-11T00:00:00", "span_days": 10.0}
    flag = profile_column(small_df["flag"], "flag")
    assert flag.stats == {"true": 6, "false": 5} and flag.missing == 1
    colour = profile_column(small_df["colour"], "colour")
    assert colour.top == (("red", 5), ("blue", 4), ("green", 2)) and colour.unique == 3 and colour.stats == {}


def test_text_lengths_and_top_ties() -> None:
    text = pd.Series([f"value {i:03d}" for i in range(60)] + ["value 000"], dtype="str")
    column = profile_column(text, "t")
    assert column.kind == "text" and column.stats == {"mean_length": 9.0, "max_length": 9}
    assert column.top[0] == ("value 000", 2) and column.top[1] == ("value 001", 1)
    ties = profile_column(pd.Series(["b", "a", "b", "a", "c"], dtype="str"), "x")
    assert ties.top == (("a", 2), ("b", 2), ("c", 1))


def test_top_five_of_ten_thousand_labels_with_ties() -> None:
    labels = [f"code-{i:05d}" for i in range(10_000)]
    labels += ["code-07777"] * 4 + ["code-00003"] * 2 + ["code-09999"] * 2 + ["code-00500"]
    random.Random(7).shuffle(labels)
    column = profile_column(pd.Series(labels, dtype="str"), "codes")
    assert column.kind == "text" and column.unique == 10_000
    # 07777 has 5; 00003 and 09999 tie on 3 (label order); 00500 has 2; the count-1 tie goes to code-00000
    assert column.top == (
        ("code-07777", 5),
        ("code-00003", 3),
        ("code-09999", 3),
        ("code-00500", 2),
        ("code-00000", 1),
    )


def test_single_value_has_no_standard_deviation() -> None:
    assert profile_column(pd.Series([5.0]), "one").stats["std"] is None
    assert profile_column(pd.Series([5.0, None]), "one").stats["std"] is None


def test_dataset_profile(small_df: pd.DataFrame) -> None:
    before = small_df.copy()
    profile = profile_dataset(small_df)
    pd.testing.assert_frame_equal(small_df, before)
    assert (profile.n_rows, profile.n_cols, profile.n_cells, profile.missing_cells) == (12, 4, 48, 4)
    assert profile.missing_cells_pct == pytest.approx(4 / 48 * 100)
    assert profile.duplicate_rows == 1
    assert dict(profile.kinds) == {"numeric": 1, "datetime": 1, "boolean": 1, "categorical": 1, "text": 0}
    assert profile.memory_bytes > 0
    assert [c.name for c in profile.columns] == ["amount", "day", "flag", "colour"]


def test_zero_rows_and_no_columns(small_df: pd.DataFrame) -> None:
    profile = profile_dataset(small_df.iloc[0:0])
    assert (profile.n_rows, profile.missing_cells, profile.duplicate_rows, profile.missing_cells_pct) == (
        0,
        0,
        0,
        0.0,
    )
    amount = profile.columns[0]
    assert amount.missing_pct == 0.0 and amount.stats["mean"] is None and amount.stats["zeros"] == 0
    assert profile.columns[1].stats["min"] is None
    with pytest.raises(ValueError, match="no columns"):
        profile_dataset(pd.DataFrame())


def test_to_dict_is_strict_json(small_df: pd.DataFrame) -> None:
    payload = profile_dataset(small_df).to_dict()
    text = json.dumps(payload, allow_nan=False)
    assert json.loads(text)["columns"][0]["stats"]["mean"] == round(statistics.mean(AMOUNTS), 6)
