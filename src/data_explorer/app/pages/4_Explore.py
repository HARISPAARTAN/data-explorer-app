"""Explore: filter conditions built with widgets or written as text, column choice and sorting."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pandas as pd
import streamlit as st

from data_explorer.app import cache, state, ui
from data_explorer.core.filters import (
    MAX_CONDITIONS,
    MAX_SORT_KEYS,
    OP_LABELS,
    Condition,
    FilterError,
    FilterSpec,
    FilterSyntaxError,
    Op,
    SortKey,
    format_condition,
    format_filter,
    ops_for,
    parse_filter,
    validate,
)
from data_explorer.core.profile import Kind, classify

MODES = ["all conditions", "any condition"]
NONE = "(none)"
IN_VALUES = 200
TABLE_ROWS = 1_000
FLASH = "w.f.flash"
EXAMPLES = (
    '`store` IN ("Milan", "Como") AND `units` BETWEEN 2 AND 10',
    '`order_date` >= "2025-01-01" OR `payment` = "Voucher"',
)


def current() -> FilterSpec:
    spec: FilterSpec = st.session_state[state.FILTER]
    return spec


def set_filter(spec: FilterSpec) -> None:
    st.session_state[state.FILTER] = spec
    st.session_state["w.f.text_form"] = format_filter(spec)


def flash(place: str, message: str) -> None:
    st.session_state[FLASH] = (place, message)


def on_mode() -> None:
    mode = "all" if st.session_state["w.f.mode"] == MODES[0] else "any"
    set_filter(FilterSpec(mode, current().conditions))


def on_remove(index: int) -> None:
    spec = current()
    set_filter(FilterSpec(spec.mode, spec.conditions[:index] + spec.conditions[index + 1 :]))


def on_clear() -> None:
    set_filter(FilterSpec(current().mode, ()))


def number(value: Any) -> int | float:
    value = float(value)
    return int(value) if value.is_integer() and abs(value) < 2**53 else value


def built_condition(df: pd.DataFrame) -> Condition:
    """The condition the widgets describe; ValueError with a message for missing input."""
    session = st.session_state
    column = str(session["w.f.column"])
    op = Op(session["w.f.op"])
    kind = classify(df[column])
    if op in (Op.IS_NULL, Op.NOT_NULL):
        return Condition(column, op)
    if op in (Op.IN, Op.NOT_IN):
        values = list(session.get("w.f.values", []))
        if not values:
            raise ValueError("Choose at least one value.")
        return Condition(
            column, op, tuple(number(v) for v in values) if kind == "numeric" else tuple(map(str, values))
        )
    if kind == "numeric":
        if op == Op.BETWEEN:
            return Condition(column, op, (number(session["w.f.value"]), number(session["w.f.value2"])))
        return Condition(column, op, number(session["w.f.value"]))
    if kind == "datetime":
        if op == Op.BETWEEN:
            chosen = session.get("w.f.date_range")
            if not isinstance(chosen, tuple | list) or len(chosen) != 2:
                raise ValueError("Choose both dates of the range.")
            return Condition(column, op, (chosen[0].isoformat(), chosen[1].isoformat()))
        day = session.get("w.f.date")
        if not isinstance(day, dt.date):
            raise ValueError("Choose a date.")
        return Condition(column, op, day.isoformat())
    if kind == "boolean":
        return Condition(column, op, session["w.f.bool"] == "TRUE")
    if kind == "categorical" and op in (Op.EQ, Op.NE):
        choice = session.get("w.f.choice")
        if choice is None:
            raise ValueError("This column has no values to compare with.")
        return Condition(column, op, str(choice))
    return Condition(column, op, str(session.get("w.f.text", "")))


def on_add() -> None:
    df = st.session_state[state.DF]
    try:
        condition = built_condition(df)
    except ValueError as exc:
        flash("add", str(exc))
        return
    spec = current()
    candidate = FilterSpec(spec.mode, (*spec.conditions, condition))
    issues = validate(candidate, df)
    if issues:
        flash("add", " ".join(issue.message for issue in issues))
        return
    set_filter(candidate)


def on_apply_text() -> None:
    df = st.session_state[state.DF]
    try:
        spec = parse_filter(st.session_state["w.f.text_form"])
    except FilterSyntaxError as exc:
        flash("text", exc.message)
        return
    issues = validate(spec, df)
    if issues:
        flash("text", " ".join(issue.message for issue in issues))
        return
    set_filter(spec)
    st.session_state["w.f.mode"] = MODES[0] if spec.mode == "all" else MODES[1]


def on_columns() -> None:
    chosen = [str(name) for name in st.session_state["w.v.columns"]]
    every = [str(name) for name in st.session_state[state.DF].columns]
    st.session_state[state.COLUMNS] = None if not chosen or chosen == every else tuple(chosen)


def on_sort() -> None:
    keys: list[SortKey] = []
    for n in range(1, MAX_SORT_KEYS + 1):
        column = st.session_state.get(f"w.v.sort.{n}.column", NONE)
        if column != NONE and column not in [key.column for key in keys]:
            keys.append(SortKey(str(column), bool(st.session_state.get(f"w.v.sort.{n}.desc", False))))
    st.session_state[state.SORT] = tuple(keys)


def frequent(series: pd.Series) -> list[Any]:
    return series.dropna().value_counts().head(IN_VALUES).index.tolist()


def value_widgets(series: pd.Series, kind: Kind, op: Op) -> None:
    if op in (Op.IS_NULL, Op.NOT_NULL):
        st.caption("This operator needs no value.")
        return
    values = series.dropna()
    if op in (Op.IN, Op.NOT_IN):
        options = frequent(series)
        state.seed_many("w.f.values", [], options)
        st.multiselect("Values", options, key="w.f.values")
        st.caption(f"The {min(IN_VALUES, len(options))} most frequent values are offered.")
    elif kind == "numeric":
        low = float(values.min()) if len(values) else 0.0
        high = float(values.max()) if len(values) else 0.0
        if op == Op.BETWEEN:
            st.number_input("From", value=low, key="w.f.value")
            st.number_input("To", value=high, key="w.f.value2")
        else:
            st.number_input("Value", value=float(values.median()) if len(values) else 0.0, key="w.f.value")
    elif kind == "datetime":
        first = pd.Timestamp(values.min()).date() if len(values) else dt.date(2025, 1, 1)
        last = pd.Timestamp(values.max()).date() if len(values) else first
        if op == Op.BETWEEN:
            st.date_input(
                "Date range", value=(first, last), min_value=first, max_value=last, key="w.f.date_range"
            )
        else:
            st.date_input("Date", value=first, min_value=first, max_value=last, key="w.f.date")
    elif kind == "boolean":
        st.selectbox("Value", ["TRUE", "FALSE"], key="w.f.bool")
    elif kind == "categorical" and op in (Op.EQ, Op.NE):
        options = [str(value) for value in frequent(series)]
        state.seed("w.f.choice", options[0] if options else None, options)
        st.selectbox("Value", options, key="w.f.choice")
    else:
        st.text_input("Text", key="w.f.text")


ui.page_setup("Explore")
df, report, dataset_id = ui.require_dataset()
st.title("Explore")
columns = [str(name) for name in df.columns]
spec = current()
message = st.session_state.pop(FLASH, None)

state.seed("w.f.mode", MODES[0] if spec.mode == "all" else MODES[1], MODES)
st.radio("Rows must match", MODES, horizontal=True, key="w.f.mode", on_change=on_mode)

if spec.conditions:
    for index, condition in enumerate(spec.conditions):
        left, right = st.columns([6, 1], vertical_alignment="center")
        left.code(format_condition(condition), language=None)
        right.button("Remove", key=f"w.f.remove.{index}", on_click=on_remove, args=(index,))
else:
    st.caption("No conditions: all rows are shown.")

with st.container(border=True):
    st.markdown("**Add a condition**")
    state.seed("w.f.column", columns[0], columns)
    column = st.selectbox("Column", columns, key="w.f.column")
    kind = classify(df[column])
    operators = list(ops_for(kind))
    state.seed("w.f.op", operators[0], operators)
    op = st.selectbox("Operator", operators, format_func=lambda item: OP_LABELS[item], key="w.f.op")
    value_widgets(df[column], kind, Op(op))
    full = len(spec.conditions) >= MAX_CONDITIONS
    st.button("Add condition", key="w.f.add", on_click=on_add, disabled=full)
    if full:
        st.caption(f"A filter has at most {MAX_CONDITIONS} conditions.")
    if message is not None and message[0] == "add":
        st.error(message[1])

with st.expander("Edit as text", expanded=message is not None and message[0] == "text"):
    state.seed("w.f.text_form", format_filter(spec))
    st.text_area("Filter", height=120, key="w.f.text_form")
    st.button("Apply text", key="w.f.apply_text", on_click=on_apply_text)
    st.caption("Examples:  \n" + "  \n".join(ui.inline_code(example) for example in EXAMPLES))
    if message is not None and message[0] == "text":
        st.error(message[1])

st.button("Clear all conditions", key="w.f.clear", on_click=on_clear, disabled=not spec.conditions)

st.subheader("Columns and sort")
chosen = list(st.session_state[state.COLUMNS] or columns)
state.seed_many("w.v.columns", chosen, columns)
st.multiselect("Columns to show and download", columns, key="w.v.columns", on_change=on_columns)
sort = st.session_state[state.SORT]
for n in range(1, MAX_SORT_KEYS + 1):
    key = sort[n - 1] if len(sort) >= n else None
    left, right = st.columns([3, 1], vertical_alignment="bottom")
    with left:
        state.seed(f"w.v.sort.{n}.column", key.column if key else NONE, [NONE, *columns])
        st.selectbox(f"Sort {n}", [NONE, *columns], key=f"w.v.sort.{n}.column", on_change=on_sort)
    with right:
        state.seed(f"w.v.sort.{n}.desc", bool(key.descending) if key else False)
        st.toggle("Descending", key=f"w.v.sort.{n}.desc", on_change=on_sort)

st.subheader("Result")
try:
    view = cache.view(dataset_id, state.view_json(), df)
except FilterError as exc:
    st.error(exc.message)
    st.stop()
except Exception:
    ui.unexpected("applying the filter")
    st.stop()
share = len(view) / len(df) * 100 if len(df) else 0.0
st.caption(f"{len(view):,} of {len(df):,} rows match ({ui.pct(share)})")
st.dataframe(view.head(TABLE_ROWS), hide_index=True)
if len(view) > TABLE_ROWS:
    st.caption("Showing the first 1,000 rows; Download contains all of them.")
else:
    st.caption(f"Showing all {len(view):,} rows.")
