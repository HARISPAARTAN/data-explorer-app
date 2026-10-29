"""Filter conditions, the flat text grammar (docs/data-model.md, ADR 0003), views and their canonical JSON."""

from __future__ import annotations

import datetime as dt
import enum
import json
import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, NoReturn, TypeAlias

import numpy as np
import pandas as pd

from data_explorer.core.profile import Kind, classify

MAX_CONDITIONS = 10
MAX_SORT_KEYS = 3


class Op(enum.StrEnum):
    EQ = "eq"
    NE = "ne"
    LT = "lt"
    LE = "le"
    GT = "gt"
    GE = "ge"
    BETWEEN = "between"
    IN = "in"
    NOT_IN = "not_in"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    STARTS_WITH = "starts_with"
    ENDS_WITH = "ends_with"
    IS_NULL = "is_null"
    NOT_NULL = "not_null"


OP_LABELS: dict[Op, str] = {
    Op.EQ: "=",
    Op.NE: "!=",
    Op.LT: "<",
    Op.LE: "<=",
    Op.GT: ">",
    Op.GE: ">=",
    Op.BETWEEN: "BETWEEN",
    Op.IN: "IN",
    Op.NOT_IN: "NOT IN",
    Op.CONTAINS: "CONTAINS",
    Op.NOT_CONTAINS: "NOT CONTAINS",
    Op.STARTS_WITH: "STARTS WITH",
    Op.ENDS_WITH: "ENDS WITH",
    Op.IS_NULL: "IS NULL",
    Op.NOT_NULL: "IS NOT NULL",
}
COMPARE = (Op.EQ, Op.NE, Op.LT, Op.LE, Op.GT, Op.GE)
TEXT_OPS = (Op.CONTAINS, Op.NOT_CONTAINS, Op.STARTS_WITH, Op.ENDS_WITH)
NULL_OPS = (Op.IS_NULL, Op.NOT_NULL)
OPS_BY_KIND: dict[Kind, tuple[Op, ...]] = {
    "numeric": (*COMPARE, Op.BETWEEN, Op.IN, Op.NOT_IN, *NULL_OPS),
    "datetime": (Op.EQ, Op.LT, Op.LE, Op.GT, Op.GE, Op.BETWEEN, *NULL_OPS),
    "boolean": (Op.EQ, *NULL_OPS),
    "categorical": (Op.EQ, Op.NE, Op.IN, Op.NOT_IN, *TEXT_OPS, *NULL_OPS),
    "text": (Op.EQ, Op.NE, *TEXT_OPS, *NULL_OPS),
}

Scalar: TypeAlias = bool | int | float | str
Value: TypeAlias = "Scalar | tuple[Scalar, ...] | None"
Mode = Literal["all", "any"]


@dataclass(frozen=True)
class Condition:
    column: str
    op: Op
    value: Value = None


@dataclass(frozen=True)
class FilterSpec:
    mode: Mode = "all"
    conditions: tuple[Condition, ...] = ()


@dataclass(frozen=True)
class SortKey:
    column: str
    descending: bool = False


@dataclass(frozen=True)
class ViewSpec:
    filter: FilterSpec = FilterSpec()
    columns: tuple[str, ...] | None = None
    sort: tuple[SortKey, ...] = ()


@dataclass(frozen=True)
class FilterIssue:
    index: int | None
    message: str


class FilterError(ValueError):
    """A filter or view that cannot be applied; ``message`` joins the issues."""

    def __init__(self, issues: Sequence[FilterIssue]) -> None:
        self.issues = tuple(issues)
        self.message = " ".join(issue.message for issue in self.issues)
        super().__init__(self.message)


class FilterSyntaxError(FilterError):
    """Text that does not follow the grammar; ``position`` is a 0-based character offset."""

    def __init__(self, position: int, expected: str) -> None:
        self.position = position
        self.expected = expected
        super().__init__([FilterIssue(None, f"Position {position + 1}: expected {expected}.")])


def ops_for(kind: Kind) -> tuple[Op, ...]:
    return OPS_BY_KIND[kind]


DATE_LITERAL = re.compile(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?)?")


def parse_date_literal(text: str) -> tuple[pd.Timestamp, bool] | None:
    """'2025-03-01' (a whole day) or '2025-03-01 08:00' (an instant); None when invalid."""
    match = DATE_LITERAL.fullmatch(text.strip())
    if match is None:
        return None
    year, month, day, hour, minute, second = match.groups()
    try:
        moment = dt.datetime(
            int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0)
        )
    except ValueError:
        return None
    return pd.Timestamp(moment), hour is not None


# --- validation -------------------------------------------------------------------------------


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _items(condition: Condition) -> list[Scalar] | str:
    """The literal values of a condition, or an error text for a wrongly shaped value."""
    label, value = OP_LABELS[condition.op], condition.value
    if condition.op in NULL_OPS:
        return [] if value is None else f"{label} takes no value."
    if condition.op == Op.BETWEEN:
        if isinstance(value, tuple) and len(value) == 2:
            return list(value)
        return "BETWEEN needs two values."
    if condition.op in (Op.IN, Op.NOT_IN):
        if isinstance(value, tuple) and len(value) >= 1:
            return list(value)
        return f"{label} needs at least one value."
    if value is None or isinstance(value, tuple):
        return f"{label} needs one value."
    return [value]


def _condition_issue(index: int, condition: Condition, df: pd.DataFrame) -> str | None:
    prefix = f"Condition {index + 1}"
    column = condition.column
    if column not in df.columns:
        return f"{prefix}: column `{column}` does not exist."
    kind = classify(df[column])
    if condition.op not in OPS_BY_KIND[kind]:
        return f"{prefix}: {OP_LABELS[condition.op]} cannot be used with the {kind} column `{column}`."
    items = _items(condition)
    if isinstance(items, str):
        return f"{prefix}: {items}"
    if not items:
        return None
    if kind == "numeric":
        if not all(_is_number(item) for item in items):
            return f"{prefix}: `{column}` is numeric, so the value must be a number."
        if condition.op == Op.BETWEEN and float(items[0]) > float(items[1]):
            return f"{prefix}: BETWEEN needs the smaller value first."
    elif kind == "datetime":
        dates = [parse_date_literal(item) if isinstance(item, str) else None for item in items]
        if any(date is None for date in dates):
            return (
                f'{prefix}: `{column}` holds dates, so the value must be a date in double quotes such as "2025-03-01" '
                'or "2025-03-01 08:00".'
            )
        if (
            condition.op == Op.BETWEEN
            and dates[0] is not None
            and dates[1] is not None
            and dates[0][0] > dates[1][0]
        ):
            return f"{prefix}: BETWEEN needs the earlier date first."
    elif kind == "boolean":
        if not isinstance(items[0], bool):
            return f"{prefix}: `{column}` is boolean, so the value must be TRUE or FALSE."
    elif not all(isinstance(item, str) for item in items):
        return f"{prefix}: `{column}` holds text, so the value must be a string in double quotes."
    return None


def validate(spec: FilterSpec, df: pd.DataFrame) -> list[FilterIssue]:
    issues: list[FilterIssue] = []
    if spec.mode not in ("all", "any"):
        issues.append(FilterIssue(None, 'The mode must be "all" or "any".'))
    if len(spec.conditions) > MAX_CONDITIONS:
        issues.append(FilterIssue(None, f"A filter can have at most {MAX_CONDITIONS} conditions."))
        return issues
    for index, condition in enumerate(spec.conditions):
        message = _condition_issue(index, condition, df)
        if message is not None:
            issues.append(FilterIssue(index, message))
    return issues


def validate_view(view: ViewSpec, df: pd.DataFrame) -> list[FilterIssue]:
    issues = validate(view.filter, df)
    for column in view.columns or ():
        if column not in df.columns:
            issues.append(FilterIssue(None, f"Column `{column}` does not exist."))
    if len(view.sort) > MAX_SORT_KEYS:
        issues.append(FilterIssue(None, f"A view can sort by at most {MAX_SORT_KEYS} columns."))
    for key in view.sort:
        if key.column not in df.columns:
            issues.append(FilterIssue(None, f"Sort column `{key.column}` does not exist."))
    return issues


# --- applying -------------------------------------------------------------------------------


def _bool(result: Any) -> np.ndarray[Any, np.dtype[np.bool_]]:
    if isinstance(result, pd.Series):
        return result.to_numpy(dtype=bool, na_value=False)
    return np.asarray(result, dtype=bool)


def _numeric_mask(series: pd.Series[Any], op: Op, items: list[Scalar]) -> np.ndarray[Any, np.dtype[np.bool_]]:
    numbers = series.astype("float64")
    values = [float(item) for item in items]
    if op == Op.EQ:
        return _bool(numbers == values[0])
    if op == Op.NE:
        return _bool(numbers != values[0])
    if op == Op.LT:
        return _bool(numbers < values[0])
    if op == Op.LE:
        return _bool(numbers <= values[0])
    if op == Op.GT:
        return _bool(numbers > values[0])
    if op == Op.GE:
        return _bool(numbers >= values[0])
    if op == Op.BETWEEN:
        return _bool((numbers >= values[0]) & (numbers <= values[1]))
    inside = _bool(numbers.isin(values))
    return inside if op == Op.IN else ~inside


def _date_bounds(item: Scalar) -> tuple[pd.Timestamp, pd.Timestamp, bool]:
    parsed = parse_date_literal(str(item))
    if parsed is None:
        raise ValueError(f"Not a date: {item!r}")
    start, has_time = parsed
    return start, (start if has_time else start + pd.Timedelta(days=1)), has_time


def _datetime_mask(
    series: pd.Series[Any], op: Op, items: list[Scalar]
) -> np.ndarray[Any, np.dtype[np.bool_]]:
    start, end, has_time = _date_bounds(items[0])
    if op == Op.EQ:
        return _bool(series == start) if has_time else _bool((series >= start) & (series < end))
    if op == Op.LT:
        return _bool(series < start)
    if op == Op.LE:
        return _bool(series <= start) if has_time else _bool(series < end)
    if op == Op.GT:
        return _bool(series > start) if has_time else _bool(series >= end)
    if op == Op.GE:
        return _bool(series >= start)
    high_start, high_end, high_time = _date_bounds(items[1])
    upper = _bool(series <= high_start) if high_time else _bool(series < high_end)
    return _bool(series >= start) & upper


def _text_mask(series: pd.Series[Any], op: Op, items: list[Scalar]) -> np.ndarray[Any, np.dtype[np.bool_]]:
    strings = series.astype("str")
    if op == Op.EQ:
        return _bool(strings == items[0])
    if op == Op.NE:
        return _bool(strings != items[0])
    if op in (Op.IN, Op.NOT_IN):
        inside = _bool(strings.isin([str(item) for item in items]))
        return inside if op == Op.IN else ~inside
    folded = strings.str.casefold()
    needle = str(items[0]).casefold()
    if op in (Op.CONTAINS, Op.NOT_CONTAINS):
        found = _bool(folded.str.contains(needle, regex=False))
        return found if op == Op.CONTAINS else ~found
    if op == Op.STARTS_WITH:
        return _bool(folded.str.startswith(needle))
    return _bool(folded.str.endswith(needle))


def _mask(df: pd.DataFrame, condition: Condition) -> np.ndarray[Any, np.dtype[np.bool_]]:
    series = df[condition.column]
    present = series.notna().to_numpy(dtype=bool)
    if condition.op == Op.IS_NULL:
        return ~present
    if condition.op == Op.NOT_NULL:
        return present
    items = _items(condition)
    assert not isinstance(items, str)
    kind = classify(series)
    if kind == "numeric":
        return _numeric_mask(series, condition.op, items) & present
    if kind == "datetime":
        return _datetime_mask(series, condition.op, items) & present
    if kind == "boolean":
        return _bool(series == items[0]) & present
    return _text_mask(series, condition.op, items) & present


def apply_filter(df: pd.DataFrame, spec: FilterSpec) -> pd.DataFrame:
    """Rows matching all (or any) conditions; missing values match only IS NULL."""
    issues = validate(spec, df)
    if issues:
        raise FilterError(issues)
    if not spec.conditions:
        return df.copy(deep=False)
    masks = [_mask(df, condition) for condition in spec.conditions]
    stacked = np.stack(masks)
    combined = stacked.all(axis=0) if spec.mode == "all" else stacked.any(axis=0)
    return df.loc[combined]


def apply_view(df: pd.DataFrame, view: ViewSpec) -> pd.DataFrame:
    issues = validate_view(view, df)
    if issues:
        raise FilterError(issues)
    result = apply_filter(df, view.filter)
    if view.sort:
        result = result.sort_values(
            by=[key.column for key in view.sort],
            ascending=[not key.descending for key in view.sort],
            kind="mergesort",
            na_position="last",
        )
    if view.columns is not None:
        result = result.loc[:, list(view.columns)]
    return result


# --- text form ------------------------------------------------------------------------------


def format_literal(value: Scalar) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Filter numbers must be finite.")
        text = repr(value)
        if "e" in text or "E" in text:
            text = np.format_float_positional(value, unique=True, trim="0")
        return text
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def format_condition(condition: Condition) -> str:
    column = "`" + condition.column.replace("`", "``") + "`"
    label, value = OP_LABELS[condition.op], condition.value
    if condition.op in NULL_OPS:
        return f"{column} {label}"
    if condition.op == Op.BETWEEN and isinstance(value, tuple):
        return f"{column} BETWEEN {format_literal(value[0])} AND {format_literal(value[1])}"
    if condition.op in (Op.IN, Op.NOT_IN) and isinstance(value, tuple):
        return f"{column} {label} ({', '.join(format_literal(item) for item in value)})"
    if value is None or isinstance(value, tuple):
        raise ValueError(f"{label} needs one value.")
    return f"{column} {label} {format_literal(value)}"


def format_filter(spec: FilterSpec) -> str:
    joiner = " AND " if spec.mode == "all" else " OR "
    return joiner.join(format_condition(condition) for condition in spec.conditions)


class _Parser:
    """Recursive descent over characters for the grammar in docs/data-model.md."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.pos = 0

    def fail(self, expected: str, position: int | None = None) -> NoReturn:
        raise FilterSyntaxError(self.pos if position is None else position, expected)

    def skip_space(self) -> None:
        while self.pos < len(self.text) and self.text[self.pos].isspace():
            self.pos += 1

    def at_end(self) -> bool:
        self.skip_space()
        return self.pos >= len(self.text)

    def peek(self) -> str:
        self.skip_space()
        return self.text[self.pos] if self.pos < len(self.text) else ""

    def keyword(self, word: str) -> bool:
        self.skip_space()
        end = self.pos + len(word)
        if self.text[self.pos : end].upper() != word:
            return False
        if end < len(self.text) and (self.text[end].isalnum() or self.text[end] == "_"):
            return False
        self.pos = end
        return True

    def symbol(self, token: str) -> bool:
        self.skip_space()
        if self.text.startswith(token, self.pos):
            self.pos += len(token)
            return True
        return False

    def parse(self) -> FilterSpec:
        if self.at_end():
            return FilterSpec()
        conditions = [self.condition()]
        joiner: str | None = None
        while not self.at_end():
            start = self.pos
            if self.keyword("AND"):
                word = "AND"
            elif self.keyword("OR"):
                word = "OR"
            else:
                self.fail('"AND", "OR" or the end of the filter')
            if joiner is not None and word != joiner:
                self.fail("the same joiner throughout (AND and OR cannot be mixed)", start)
            joiner = word
            conditions.append(self.condition())
        return FilterSpec("any" if joiner == "OR" else "all", tuple(conditions))

    def condition(self) -> Condition:
        column = self.column()
        if self.symbol("<="):
            return Condition(column, Op.LE, self.literal())
        if self.symbol(">="):
            return Condition(column, Op.GE, self.literal())
        if self.symbol("!="):
            return Condition(column, Op.NE, self.literal())
        if self.symbol("="):
            return Condition(column, Op.EQ, self.literal())
        if self.symbol("<"):
            return Condition(column, Op.LT, self.literal())
        if self.symbol(">"):
            return Condition(column, Op.GT, self.literal())
        if self.keyword("BETWEEN"):
            low = self.literal()
            if not self.keyword("AND"):
                self.fail('"AND" between the two values')
            return Condition(column, Op.BETWEEN, (low, self.literal()))
        if self.keyword("NOT"):
            if self.keyword("IN"):
                return Condition(column, Op.NOT_IN, self.members())
            if self.keyword("CONTAINS"):
                return Condition(column, Op.NOT_CONTAINS, self.string())
            self.fail('"IN" or "CONTAINS" after NOT')
        if self.keyword("IN"):
            return Condition(column, Op.IN, self.members())
        if self.keyword("CONTAINS"):
            return Condition(column, Op.CONTAINS, self.string())
        if self.keyword("STARTS"):
            if not self.keyword("WITH"):
                self.fail('"WITH" after STARTS')
            return Condition(column, Op.STARTS_WITH, self.string())
        if self.keyword("ENDS"):
            if not self.keyword("WITH"):
                self.fail('"WITH" after ENDS')
            return Condition(column, Op.ENDS_WITH, self.string())
        if self.keyword("IS"):
            if self.keyword("NULL"):
                return Condition(column, Op.IS_NULL)
            if self.keyword("NOT") and self.keyword("NULL"):
                return Condition(column, Op.NOT_NULL)
            self.fail('"NULL" or "NOT NULL" after IS')
        self.fail("an operator such as =, IN or CONTAINS")

    def column(self) -> str:
        if self.peek() != "`":
            self.fail("a column name in backticks, such as `store`")
        self.pos += 1
        chars: list[str] = []
        while True:
            if self.pos >= len(self.text):
                self.fail("a closing backtick")
            char = self.text[self.pos]
            if char == "`":
                if self.text.startswith("``", self.pos):
                    chars.append("`")
                    self.pos += 2
                    continue
                self.pos += 1
                return "".join(chars)
            chars.append(char)
            self.pos += 1

    def members(self) -> tuple[Scalar, ...]:
        if not self.symbol("("):
            self.fail('"(" after IN')
        values = [self.literal()]
        while True:
            if self.symbol(","):
                values.append(self.literal())
            elif self.symbol(")"):
                return tuple(values)
            else:
                self.fail('"," or ")"')

    def literal(self) -> Scalar:
        char = self.peek()
        if char == '"':
            return self.string()
        if char == "-" or (char != "" and char in "0123456789"):
            return self.number()
        if self.keyword("TRUE"):
            return True
        if self.keyword("FALSE"):
            return False
        self.fail("a value: a number, a string in double quotes, TRUE or FALSE")

    def number(self) -> int | float:
        start = self.pos
        if self.text[self.pos] == "-":
            self.pos += 1
        if not self._digits():
            self.fail("a digit")
        if self.pos < len(self.text) and self.text[self.pos] == ".":
            self.pos += 1
            if not self._digits():
                self.fail("a digit")
        token = self.text[start : self.pos]
        return float(token) if "." in token else int(token)

    def _digits(self) -> bool:
        start = self.pos
        while self.pos < len(self.text) and self.text[self.pos] in "0123456789":
            self.pos += 1
        return self.pos > start

    def string(self) -> str:
        if self.peek() != '"':
            self.fail("a string in double quotes")
        self.pos += 1
        chars: list[str] = []
        while True:
            if self.pos >= len(self.text):
                self.fail("a closing double quote")
            char = self.text[self.pos]
            if char == "\\":
                following = self.text[self.pos + 1 : self.pos + 2]
                if following not in ('"', "\\"):
                    self.fail('a quote (\\") or a backslash (\\\\) after the backslash', self.pos + 1)
                chars.append(following)
                self.pos += 2
                continue
            self.pos += 1
            if char == '"':
                return "".join(chars)
            chars.append(char)


def parse_filter(text: str) -> FilterSpec:
    """Parse the text form; raises FilterSyntaxError with the position of the first problem."""
    return _Parser(text).parse()


# --- JSON form ------------------------------------------------------------------------------


def _value_to_json(value: Value) -> Any:
    return list(value) if isinstance(value, tuple) else value


def _value_from_json(value: Any) -> Value:
    if isinstance(value, list):
        return tuple(value)
    return value  # type: ignore[no-any-return]


def view_to_json(view: ViewSpec) -> str:
    payload = {
        "filter": {
            "mode": view.filter.mode,
            "conditions": [
                {"column": c.column, "op": c.op.value, "value": _value_to_json(c.value)}
                for c in view.filter.conditions
            ],
        },
        "columns": None if view.columns is None else list(view.columns),
        "sort": [{"column": key.column, "descending": key.descending} for key in view.sort],
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def view_from_json(text: str) -> ViewSpec:
    try:
        payload = json.loads(text)
        spec = payload["filter"]
        conditions = tuple(
            Condition(str(item["column"]), Op(item["op"]), _value_from_json(item.get("value")))
            for item in spec["conditions"]
        )
        columns = payload.get("columns")
        sort = tuple(
            SortKey(str(item["column"]), bool(item["descending"])) for item in payload.get("sort", [])
        )
        mode = spec.get("mode", "all")
        if mode not in ("all", "any"):
            raise ValueError(f"bad mode {mode!r}")
        return ViewSpec(
            FilterSpec(mode, conditions), None if columns is None else tuple(str(c) for c in columns), sort
        )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError(f"Invalid view JSON: {exc}") from exc
