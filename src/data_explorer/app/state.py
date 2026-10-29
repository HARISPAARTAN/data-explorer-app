"""Session-state keys (docs/architecture.md, "Session state").

``de.*`` keys hold the app state and survive page switches. ``w.*`` keys belong to widgets and are
page-local: Streamlit drops the state of a widget that a run does not render, so pages copy widget
values into ``de.*`` keys in callbacks and seed the widgets from them before creating them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import pandas as pd
import streamlit as st

from data_explorer.core.filters import FilterSpec, ViewSpec, view_to_json
from data_explorer.core.io import LoadReport

DATASET_ID = "de.dataset_id"
DF = "de.df"
REPORT = "de.report"
SOURCE = "de.source"
FILTER = "de.filter"
COLUMNS = "de.columns"
SORT = "de.sort"
Q_SUBSET = "de.q_subset"
Q_K = "de.q_k"
CHART = "de.chart"
CSV_DIALECT = "de.csv_dialect"
PROFILE_SCOPE = "de.profile_scope"

DATASET_KEYS = (DATASET_ID, DF, REPORT, SOURCE)
DEFAULT_CHART: dict[str, Any] = {"type": "Histogram"}
DOWNLOAD_DEFAULTS: dict[str, Any] = {CSV_DIALECT: "comma", PROFILE_SCOPE: "dataset"}


def reset_values() -> dict[str, Any]:
    """The values a new dataset starts with."""
    return {FILTER: FilterSpec(), COLUMNS: None, SORT: (), Q_SUBSET: (), Q_K: 1.5, CHART: dict(DEFAULT_CHART)}


def init() -> None:
    for key, value in {**reset_values(), **DOWNLOAD_DEFAULTS}.items():
        if key not in st.session_state:
            st.session_state[key] = value


def has_dataset() -> bool:
    return st.session_state.get(DF) is not None


def set_dataset(dataset_id: str, df: pd.DataFrame, report: LoadReport, source: str) -> None:
    """Replace the dataset and reset everything that depends on its columns."""
    st.session_state[DATASET_ID] = dataset_id
    st.session_state[DF] = df
    st.session_state[REPORT] = report
    st.session_state[SOURCE] = source
    for key, value in reset_values().items():
        st.session_state[key] = value


def dataset() -> tuple[pd.DataFrame, LoadReport, str]:
    return st.session_state[DF], st.session_state[REPORT], st.session_state[DATASET_ID]


def view_spec() -> ViewSpec:
    return ViewSpec(st.session_state[FILTER], st.session_state[COLUMNS], st.session_state[SORT])


def view_json() -> str:
    return view_to_json(view_spec())


_MISSING = object()


def seed(key: str, value: Any, options: Sequence[Any] | None = None) -> None:
    """Give a widget key a value before the widget is created, unless it already holds a valid one."""
    current = st.session_state.get(key, _MISSING)
    if options is None:
        if current is _MISSING:
            st.session_state[key] = value
        return
    if current is _MISSING or current not in options:
        st.session_state[key] = value if value in options else (options[0] if len(options) else None)


def seed_many(key: str, values: Sequence[Any], options: Sequence[Any]) -> None:
    """The multiselect version of ``seed``: keep only values that are still options."""
    current = st.session_state.get(key, _MISSING)
    source = values if current is _MISSING else current
    st.session_state[key] = [value for value in source if value in options]
