"""core/filters.py: every operator per kind, null semantics, whole days, validation, grammar, round trips."""

from __future__ import annotations

import pandas as pd
import pytest
from hypothesis import given
from hypothesis import strategies as st

from data_explorer.core.filters import (
    MAX_CONDITIONS,
    Condition,
    FilterError,
    FilterIssue,
    FilterSpec,
    FilterSyntaxError,
    Op,
    SortKey,
    ViewSpec,
    apply_filter,
    apply_view,
    format_filter,
    ops_for,
    parse_date_literal,
    parse_filter,
    validate,
    validate_view,
    view_from_json,
    view_to_json,
)


@pytest.fixture
def frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "n": pd.Series([1, 5, 10, None, 7], dtype="Int64"),
            "x": [0.5, 2.5, -1.0, 3.0, None],
            "d": pd.to_datetime(
                pd.Series(
                    ["2025-03-01 08:00", "2025-03-31 23:30", "2025-04-01 00:00", None, "2025-02-28 12:00"]
                ),
                format="%Y-%m-%d %H:%M",
            ).astype("datetime64[us]"),
            "b": pd.array([True, False, None, True, False], dtype="boolean"),
            "c": pd.Series(["Milan", "Como", None, "milan", "Monza"], dtype="str"),
        }
    )


def rows(df: pd.DataFrame, text: str) -> list[int]:
    return apply_filter(df, parse_filter(text)).index.tolist()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("`n` = 5", [1]),
        ("`n` != 5", [0, 2, 4]),
        ("`n` < 5", [0]),
        ("`n` <= 5", [0, 1]),
        ("`n` > 5", [2, 4]),
        ("`n` >= 7", [2, 4]),
        ("`n` BETWEEN 5 AND 10", [1, 2, 4]),
        ("`n` IN (1, 10)", [0, 2]),
        ("`n` NOT IN (1)", [1, 2, 4]),
        ("`x` > 0", [0, 1, 3]),
        ("`x` BETWEEN -1 AND 0.5", [0, 2]),
        ("`n` IS NULL", [3]),
        ("`x` IS NOT NULL", [0, 1, 2, 3]),
    ],
)
def test_numeric_operators_and_nulls(frame: pd.DataFrame, text: str, expected: list[int]) -> None:
    assert rows(frame, text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ('`d` = "2025-03-31"', [1]),
        ('`d` <= "2025-03-31"', [0, 1, 4]),
        ('`d` > "2025-03-31"', [2]),
        ('`d` < "2025-03-01"', [4]),
        ('`d` >= "2025-03-01"', [0, 1, 2]),
        ('`d` BETWEEN "2025-03-01" AND "2025-03-31"', [0, 1]),
        ('`d` = "2025-03-01 08:00"', [0]),
        ('`d` <= "2025-03-01 08:00"', [0, 4]),
        ('`d` BETWEEN "2025-02-28" AND "2025-03-01 08:00"', [0, 4]),
        ("`d` IS NULL", [3]),
    ],
)
def test_datetime_whole_day_rule(frame: pd.DataFrame, text: str, expected: list[int]) -> None:
    assert rows(frame, text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("`b` = TRUE", [0, 3]),
        ("`b` = FALSE", [1, 4]),
        ("`b` IS NULL", [2]),
        ('`c` = "Milan"', [0]),
        ('`c` != "Milan"', [1, 3, 4]),
        ('`c` IN ("Milan", "Como")', [0, 1]),
        ('`c` NOT IN ("Como")', [0, 3, 4]),
        ('`c` CONTAINS "MIL"', [0, 3]),
        ('`c` NOT CONTAINS "mil"', [1, 4]),
        ('`c` STARTS WITH "mo"', [4]),
        ('`c` ENDS WITH "O"', [1]),
        ("`c` IS NULL", [2]),
        ('`n` = 1 OR `c` = "Monza"', [0, 4]),
        ('`n` >= 5 AND `c` CONTAINS "o"', [1, 4]),
    ],
)
def test_boolean_categorical_and_modes(frame: pd.DataFrame, text: str, expected: list[int]) -> None:
    assert rows(frame, text) == expected


def test_text_kind_and_empty_filter(frame: pd.DataFrame) -> None:
    text = pd.DataFrame({"t": pd.Series([f"Note {i}" for i in range(60)] + [None], dtype="str")})
    assert rows(text, '`t` ENDS WITH "9"') == [9, 19, 29, 39, 49, 59]
    assert rows(text, '`t` != "Note 1"') == [i for i in range(60) if i != 1]
    with pytest.raises(FilterError):
        apply_filter(text, parse_filter('`t` IN ("Note 1")'))
    assert apply_filter(frame, FilterSpec()).index.tolist() == [0, 1, 2, 3, 4]


def test_ops_for_each_kind() -> None:
    assert ops_for("boolean") == (Op.EQ, Op.IS_NULL, Op.NOT_NULL)
    assert Op.BETWEEN in ops_for("datetime") and Op.NE not in ops_for("datetime")
    assert Op.CONTAINS in ops_for("categorical") and Op.IN not in ops_for("text")
    assert Op.IN in ops_for("numeric") and Op.CONTAINS not in ops_for("numeric")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("`zz` = 1", "Condition 1: column `zz` does not exist."),
        ("`b` > TRUE", "Condition 1: > cannot be used with the boolean column `b`."),
        ('`n` = "5"', "Condition 1: `n` is numeric, so the value must be a number."),
        ('`d` = "31/03/2025"', "Condition 1: `d` holds dates"),
        ("`c` = 5", "Condition 1: `c` holds text, so the value must be a string in double quotes."),
        ("`n` BETWEEN 10 AND 5", "Condition 1: BETWEEN needs the smaller value first."),
        ('`n` = 1 AND `d` > "2025-02-30"', "Condition 2: `d` holds dates"),
    ],
)
def test_validation_messages(frame: pd.DataFrame, text: str, message: str) -> None:
    issues = validate(parse_filter(text), frame)
    assert issues and issues[0].message.startswith(message)
    with pytest.raises(FilterError) as caught:
        apply_filter(frame, parse_filter(text))
    assert caught.value.issues == tuple(issues)


def test_limits_of_conditions_and_sort_keys(frame: pd.DataFrame) -> None:
    eleven = FilterSpec(conditions=tuple(Condition("n", Op.NOT_NULL) for _ in range(MAX_CONDITIONS + 1)))
    assert validate(eleven, frame) == [FilterIssue(None, "A filter can have at most 10 conditions.")]
    assert validate(FilterSpec(conditions=eleven.conditions[:10]), frame) == []
    four = tuple(SortKey(column) for column in ("n", "x", "d", "c"))
    assert FilterIssue(None, "A view can sort by at most 3 columns.") in validate_view(
        ViewSpec(sort=four), frame
    )
    issues = validate_view(ViewSpec(columns=("n", "zz"), sort=(SortKey("yy"),)), frame)
    assert [issue.message for issue in issues] == [
        "Column `zz` does not exist.",
        "Sort column `yy` does not exist.",
    ]


def test_sorting_is_stable_with_missing_last(frame: pd.DataFrame) -> None:
    view = ViewSpec(sort=(SortKey("n", descending=True),))
    assert apply_view(frame, view)["n"].tolist()[:4] == [10, 7, 5, 1]
    assert apply_view(frame, view).index.tolist()[-1] == 3
    assert apply_view(frame, ViewSpec(sort=(SortKey("n"),))).index.tolist() == [0, 1, 4, 2, 3]
    ties = pd.DataFrame({"k": [2, 1, 2, 1], "v": ["a", "b", "c", "d"]})
    assert apply_view(ties, ViewSpec(sort=(SortKey("k"),)))["v"].tolist() == ["b", "d", "a", "c"]
    both = ViewSpec(sort=(SortKey("k", True), SortKey("v", True)))
    assert apply_view(ties, both)["v"].tolist() == ["c", "a", "d", "b"]
    picked = apply_view(frame, ViewSpec(filter=parse_filter("`n` > 1"), columns=("c", "n")))
    assert list(picked.columns) == ["c", "n"] and picked.index.tolist() == [1, 2, 4]


def test_format_examples() -> None:
    spec = FilterSpec(
        conditions=(
            Condition("store", Op.IN, ("Milan", "Como")),
            Condition("units", Op.BETWEEN, (2, 10)),
            Condition("order_date", Op.GE, "2025-01-01"),
        )
    )
    expected = '`store` IN ("Milan", "Como") AND `units` BETWEEN 2 AND 10 AND `order_date` >= "2025-01-01"'
    assert format_filter(spec) == expected and parse_filter(expected) == spec
    odd = FilterSpec(conditions=(Condition("we`ird", Op.EQ, 'say "hi" \\ bye'),))
    assert format_filter(odd) == '`we``ird` = "say \\"hi\\" \\\\ bye"'
    numbers = FilterSpec(
        "any",
        (
            Condition("x", Op.GT, 1e16),
            Condition("x", Op.LT, 0.1),
            Condition("x", Op.NE, 5),
            Condition("b", Op.EQ, False),
        ),
    )
    assert format_filter(numbers) == "`x` > 10000000000000000.0 OR `x` < 0.1 OR `x` != 5 OR `b` = FALSE"
    assert format_filter(FilterSpec()) == "" and parse_filter("  ") == FilterSpec()


def test_keywords_are_case_insensitive_and_between_owns_its_and() -> None:
    spec = parse_filter(
        '`a` not in (1, 2) and `b` is not null And `c` between 1 and 5 AND `d` starts with "x"'
    )
    assert spec.mode == "all"
    assert [c.op for c in spec.conditions] == [Op.NOT_IN, Op.NOT_NULL, Op.BETWEEN, Op.STARTS_WITH]
    assert spec.conditions[2].value == (1, 5)
    assert parse_filter("`a`=1 or`b`IN(-2.5)").conditions[1] == Condition("b", Op.IN, (-2.5,))


@pytest.mark.parametrize(
    ("text", "position", "expected"),
    [
        ("`order_date` x", 13, "an operator such as =, IN or CONTAINS"),
        ("store = 1", 0, "a column name in backticks, such as `store`"),
        ("`a` = 1 AND `b` = 2 OR `c` = 3", 20, "the same joiner throughout (AND and OR cannot be mixed)"),
        ('`a` = "open', 11, "a closing double quote"),
        ("`a` IN ()", 8, "a value: a number, a string in double quotes, TRUE or FALSE"),
        ("`a` = 1 `b` = 2", 8, '"AND", "OR" or the end of the filter'),
        ('`a` = "x\\y"', 9, 'a quote (\\") or a backslash (\\\\) after the backslash'),
        ("`a` BETWEEN 1 2", 14, '"AND" between the two values'),
        ("`a` CONTAINS 5", 13, "a string in double quotes"),
        ("`a` IS NUL", 7, '"NULL" or "NOT NULL" after IS'),
        ("`a` = -x", 7, "a digit"),
        ("`open", 5, "a closing backtick"),
    ],
)
def test_syntax_errors_have_positions(text: str, position: int, expected: str) -> None:
    with pytest.raises(FilterSyntaxError) as caught:
        parse_filter(text)
    assert (caught.value.position, caught.value.expected) == (position, expected)
    assert caught.value.message == f"Position {position + 1}: expected {expected}."


def test_spec_example_error_message() -> None:
    with pytest.raises(
        FilterSyntaxError, match=r"^Position 14: expected an operator such as =, IN or CONTAINS\.$"
    ):
        parse_filter("`order_date` x")


def test_date_literals() -> None:
    assert parse_date_literal("2025-03-01") == (pd.Timestamp("2025-03-01"), False)
    assert parse_date_literal("2025-03-01 08:00") == (pd.Timestamp("2025-03-01 08:00"), True)
    assert parse_date_literal("2025-02-30") is None and parse_date_literal("01/03/2025") is None


def test_view_json_is_canonical() -> None:
    assert view_to_json(ViewSpec()) == '{"columns":null,"filter":{"conditions":[],"mode":"all"},"sort":[]}'
    view = ViewSpec(parse_filter('`a` BETWEEN 1 AND 2.5 OR `b` = "x"'), ("a", "b"), (SortKey("a", True),))
    assert view_from_json(view_to_json(view)) == view
    with pytest.raises(ValueError):
        view_from_json('{"filter": 3}')


scalars = st.one_of(
    st.booleans(),
    st.integers(min_value=-(10**15), max_value=10**15),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=12),
)
columns = st.text(max_size=12)
conditions = st.one_of(
    st.builds(Condition, columns, st.sampled_from([Op.EQ, Op.NE, Op.LT, Op.LE, Op.GT, Op.GE]), scalars),
    st.builds(Condition, columns, st.just(Op.BETWEEN), st.tuples(scalars, scalars)),
    st.builds(
        Condition,
        columns,
        st.sampled_from([Op.IN, Op.NOT_IN]),
        st.lists(scalars, min_size=1, max_size=4).map(tuple),
    ),
    st.builds(
        Condition,
        columns,
        st.sampled_from([Op.CONTAINS, Op.NOT_CONTAINS, Op.STARTS_WITH, Op.ENDS_WITH]),
        st.text(max_size=12),
    ),
    st.builds(Condition, columns, st.sampled_from([Op.IS_NULL, Op.NOT_NULL]), st.none()),
)
specs = st.lists(conditions, max_size=MAX_CONDITIONS).flatmap(
    lambda items: st.sampled_from(["all", "any"] if len(items) >= 2 else ["all"]).map(
        lambda mode: FilterSpec(mode, tuple(items))
    )
)


@given(specs)
def test_format_parse_round_trip(spec: FilterSpec) -> None:
    assert parse_filter(format_filter(spec)) == spec


@given(
    specs,
    st.one_of(st.none(), st.lists(columns, max_size=3).map(tuple)),
    st.lists(st.builds(SortKey, columns, st.booleans()), max_size=3),
)
def test_view_json_round_trip(spec: FilterSpec, chosen: tuple[str, ...] | None, sort: list[SortKey]) -> None:
    view = ViewSpec(spec, chosen, tuple(sort))
    assert view_from_json(view_to_json(view)) == view


# --- integers above 2**53 stay exact -------------------------------------------------------------

BIG = 2**53


def big_frame(dtype: str) -> pd.DataFrame:
    return pd.DataFrame({"v": pd.Series([BIG, BIG + 1, BIG + 2], dtype=dtype)})


@pytest.mark.parametrize("dtype", ["int64", "uint64", "Int64", "UInt64"])
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"`v` = {BIG + 1}", [1]),
        (f"`v` != {BIG + 1}", [0, 2]),
        (f"`v` < {BIG + 1}", [0]),
        (f"`v` <= {BIG + 1}", [0, 1]),
        (f"`v` > {BIG + 1}", [2]),
        (f"`v` >= {BIG + 1}", [1, 2]),
        (f"`v` BETWEEN {BIG + 1} AND {BIG + 1}", [1]),
        (f"`v` BETWEEN {BIG} AND {BIG + 1}", [0, 1]),
        (f"`v` IN ({BIG + 1}, {BIG + 2})", [1, 2]),
        (f"`v` IN ({BIG + 1})", [1]),
        (f"`v` NOT IN ({BIG + 1})", [0, 2]),
        (f"`v` = {BIG + 3}", []),
    ],
)
def test_large_integers_compare_exactly(dtype: str, text: str, expected: list[int]) -> None:
    assert rows(big_frame(dtype), text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (f"`v` = {BIG + 1}", [1]),
        (f"`v` != {BIG + 1}", [0, 3]),
        (f"`v` < {BIG + 2}", [0, 1]),
        (f"`v` >= {BIG + 1}", [1, 3]),
        (f"`v` BETWEEN {BIG + 1} AND {BIG + 2}", [1, 3]),
        (f"`v` IN ({BIG}, {BIG + 2})", [0, 3]),
        (f"`v` NOT IN ({BIG + 1})", [0, 3]),
        ("`v` IS NULL", [2]),
        ("`v` IS NOT NULL", [0, 1, 3]),
    ],
)
def test_large_nullable_integers_skip_missing_values(text: str, expected: list[int]) -> None:
    frame = pd.DataFrame({"v": pd.Series([BIG, BIG + 1, None, BIG + 2], dtype="Int64")})
    assert rows(frame, text) == expected


def test_integer_literals_beyond_the_column_range_and_backwards_between() -> None:
    for dtype in ("int64", "Int64"):
        frame = big_frame(dtype)
        assert rows(frame, f"`v` < {10**20}") == [0, 1, 2]
        assert rows(frame, f"`v` > -{10**20}") == [0, 1, 2]
        assert rows(frame, f"`v` = {10**20}") == [] and rows(frame, f"`v` > {10**20}") == []
        assert rows(frame, f"`v` IN ({10**20}, {BIG + 2})") == [2]
    issues = validate(parse_filter(f"`v` BETWEEN {BIG + 1} AND {BIG}"), big_frame("int64"))
    assert [issue.message for issue in issues] == ["Condition 1: BETWEEN needs the smaller value first."]


def test_decimal_literals_on_integer_columns_still_use_floats() -> None:
    frame = pd.DataFrame(
        {
            "i": pd.Series([1, 2, 3], dtype="int64"),
            "m": pd.Series([1, None, 3], dtype="Int64"),
        }
    )
    assert rows(frame, "`i` > 1.5") == [1, 2]
    assert rows(frame, "`i` = 2.0") == [1]
    assert rows(frame, "`i` BETWEEN 1 AND 2.5") == [0, 1]
    assert rows(frame, "`i` IN (1, 2.5)") == [0]
    assert rows(frame, "`m` < 2.5") == [0]
    assert rows(frame, "`m` NOT IN (1.0)") == [2]
    assert rows(frame, "`i` = 2") == [1] and rows(frame, "`m` >= 2") == [2]


# --- pathological numbers ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "number",
    [
        "9" * 4301,
        "9" * 400,
        "-" + "9" * 400,
        "9" * 309,
        "0" * 4301 + "1",
        "9" * 400 + ".5",
        "-" + "9" * 400 + ".5",
        "1" + "0" * 309 + ".0",
    ],
)
def test_oversized_number_literals_are_syntax_errors(number: str) -> None:
    for text, position in [
        (f"`n` = {number}", 6),
        (f"`n` BETWEEN 1 AND {number}", 18),
        (f"`n` IN (1, {number})", 11),
    ]:
        with pytest.raises(FilterSyntaxError) as caught:
            parse_filter(text)
        assert caught.value.position == position
        assert caught.value.expected == "a smaller number (this one is too large)"


def test_largest_float_sized_literals_still_parse_and_round_trip() -> None:
    biggest = int("1" + "0" * 308)
    assert parse_filter(f"`x` > {biggest}").conditions[0].value == biggest
    assert rows(pd.DataFrame({"x": [1.0, 1e308, 5e307]}), f"`x` >= {biggest}") == [1]
    assert parse_filter("`x` = 0." + "1" * 400).conditions[0].value == float("0." + "1" * 400)
    for value in (1.7976931348623157e308, -1.7976931348623157e308, 5e-324, 2.2250738585072014e-308):
        spec = FilterSpec(conditions=(Condition("x", Op.LE, value),))
        assert parse_filter(format_filter(spec)) == spec


def test_oversized_numbers_in_built_conditions_are_filter_errors(frame: pd.DataFrame) -> None:
    for condition in (
        Condition("n", Op.EQ, 10**400),
        Condition("n", Op.BETWEEN, (1, 10**400)),
        Condition("n", Op.IN, (1, -(10**400))),
        Condition("x", Op.GT, 10**309),
        Condition("x", Op.GT, float("inf")),
    ):
        spec = FilterSpec(conditions=(condition,))
        assert validate(spec, frame)[0].message.endswith("so the value must be a number.")
        with pytest.raises(FilterError):
            apply_filter(frame, spec)
    from_json = view_from_json(
        '{"filter":{"mode":"all","conditions":[{"column":"n","op":"eq","value":' + "9" * 400 + "}]}}"
    )
    with pytest.raises(FilterError):
        apply_view(frame, from_json)
