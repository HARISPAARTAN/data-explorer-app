"""Visualise: histogram, bar, line, scatter and correlation heatmap from pre-aggregated data."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import streamlit as st

from data_explorer.app import cache, state, ui
from data_explorer.core.charts import (
    ChartError,
    bar,
    chart_caption,
    correlation_heatmap,
    histogram,
    line,
    scatter,
)
from data_explorer.core.filters import FilterSpec, ViewSpec, view_to_json

TYPES = ["Histogram", "Bar", "Line", "Scatter", "Correlation heatmap"]
COUNT = "Count rows"
NONE = "(none)"
AGGS = ["sum", "mean", "median"]
PERIODS = {"Day": "D", "Week": "W", "Month": "M"}
METHODS = {"Pearson": "pearson", "Spearman": "spearman"}
MAX_GROUPS = 8
MAX_BAR_TEXT = 1_000


def remember(control: str) -> None:
    st.session_state[state.CHART] = {
        **st.session_state[state.CHART],
        control: st.session_state[f"w.c.{control}"],
    }


def choose(label: str, options: Sequence[Any], control: str, default: Any = None) -> Any:
    key = f"w.c.{control}"
    saved = st.session_state[state.CHART].get(control, options[0] if default is None else default)
    state.seed(key, saved, options)
    return st.selectbox(label, options, key=key, on_change=remember, args=(control,))


def slide(label: str, low: int, high: int, control: str, default: int) -> int:
    key = f"w.c.{control}"
    state.seed(key, int(st.session_state[state.CHART].get(control, default)))
    return int(st.slider(label, low, high, key=key, on_change=remember, args=(control,)))


def measure_controls(numeric: list[str]) -> tuple[str | None, str]:
    measure = choose("Measure", [COUNT, *numeric], "measure")
    if measure == COUNT:
        return None, "count"
    return str(measure), str(choose("Aggregation", AGGS, "agg"))


ui.page_setup("Visualise")
df, report, dataset_id = ui.require_dataset()
st.title("Visualise")
saved = st.session_state[state.CHART]

state.seed("w.c.filtered", bool(saved.get("filtered", True)))
use_filter = st.toggle("Use the Explore filter", key="w.c.filtered", on_change=remember, args=("filtered",))
spec: FilterSpec = st.session_state[state.FILTER]
frame = df
if use_filter and spec.conditions:
    try:
        frame = cache.view(dataset_id, view_to_json(ViewSpec(filter=spec)), df)
    except Exception:
        ui.unexpected("applying the filter")
        st.stop()
    st.caption(f"Explore filter: {len(frame):,} of {len(df):,} rows")
elif use_filter:
    st.caption(f"The Explore filter has no conditions: all {len(df):,} rows")
else:
    st.caption(f"All {len(df):,} rows; the Explore filter is not used")

state.seed("w.c.type", saved.get("type", TYPES[0]), TYPES)
chart_type = st.radio("Chart", TYPES, horizontal=True, key="w.c.type", on_change=remember, args=("type",))

profile = cache.profile(dataset_id, df)
numeric = [column.name for column in profile.columns if column.kind == "numeric"]
dates = [column.name for column in profile.columns if column.kind == "datetime"]
groups = [
    column.name
    for column in profile.columns
    if column.kind in ("categorical", "boolean")
    and column.unique + (1 if column.missing else 0) <= MAX_GROUPS
]
categories = [
    column.name
    for column in profile.columns
    if column.kind in ("categorical", "boolean") or (column.kind == "text" and column.unique <= MAX_BAR_TEXT)
]
theme = ui.chart_theme()
chart = None
notice = None
try:
    if chart_type == "Histogram":
        if not numeric:
            notice = "This dataset has no numeric column."
        else:
            column = choose("Column", numeric, "column")
            bins = slide("Bins", 5, 100, "bins", 30)
            chart = histogram(frame, column, bins, theme=theme)
    elif chart_type == "Bar":
        if not categories:
            notice = "This dataset has no categorical, boolean or text column with at most 1,000 values."
        else:
            category = choose("Category", categories, "category")
            value, agg = measure_controls(numeric)
            top_n = slide("Top N", 5, 50, "top_n", 15)
            chart = bar(frame, category, value, agg, top_n, theme=theme)
    elif chart_type == "Line":
        if not dates:
            notice = "This dataset has no datetime column."
        else:
            date_column = choose("Date column", dates, "date")
            value, agg = measure_controls(numeric)
            period = choose("Period", list(PERIODS), "period", "Week")
            split = choose("Split by", [NONE, *groups], "split")
            split_by = None if split == NONE else split
            chart = line(frame, date_column, value, agg, PERIODS[period], split_by, theme=theme)
    elif chart_type == "Scatter":
        if not numeric:
            notice = "This dataset has no numeric column."
        else:
            x = choose("X", numeric, "x")
            y = choose("Y", numeric, "y", numeric[1] if len(numeric) > 1 else numeric[0])
            colour = choose("Colour", [NONE, *groups], "colour")
            chart = scatter(frame, x, y, None if colour == NONE else colour, theme=theme)
    else:
        state.seed("w.c.method", saved.get("method", "Pearson"), list(METHODS))
        method = st.radio(
            "Method", list(METHODS), horizontal=True, key="w.c.method", on_change=remember, args=("method",)
        )
        chart = correlation_heatmap(frame, METHODS[method], theme=theme)
except ChartError as exc:
    st.warning(str(exc))
except Exception:
    ui.unexpected("drawing the chart")

if notice is not None:
    st.info(notice)
if chart is not None:
    st.altair_chart(chart, width="stretch", theme="streamlit")
    st.caption(chart_caption(chart))
