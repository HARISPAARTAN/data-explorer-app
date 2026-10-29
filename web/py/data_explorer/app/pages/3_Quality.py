"""Quality: missing values, duplicates, constant columns and IQR outliers."""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from data_explorer.app import cache, state, ui
from data_explorer.core.charts import ChartError, chart_caption, missing_heatmap
from data_explorer.core.quality import OUTLIER_ROWS_SHOWN, outlier_rows

K_OPTIONS = [1.5, 2.0, 2.5, 3.0]


def save_subset() -> None:
    st.session_state[state.Q_SUBSET] = tuple(st.session_state["w.q.subset"])


def save_k() -> None:
    st.session_state[state.Q_K] = float(st.session_state["w.q.k"])


ui.page_setup("Quality")
df, report, dataset_id = ui.require_dataset()
st.title("Quality")
columns = [str(name) for name in df.columns]
state.seed_many("w.q.subset", list(st.session_state[state.Q_SUBSET]), columns)
state.seed("w.q.k", float(st.session_state[state.Q_K]), K_OPTIONS)
subset = tuple(st.session_state["w.q.subset"])
k = float(st.session_state["w.q.k"])

try:
    quality = cache.quality(dataset_id, k, json.dumps(list(subset)), df)
    profile = cache.profile(dataset_id, df)
except Exception:
    ui.unexpected("checking the data quality")
    st.stop()

flagged = [item.column for item in quality.outliers if item.n_low + item.n_high]
cells = st.columns(5)
cells[0].metric("Columns with missing values", f"{len(quality.missing):,}")
cells[1].metric("Missing cells", ui.pct(profile.missing_cells_pct))
cells[2].metric("Duplicate rows", f"{quality.duplicates.duplicate_rows:,}")
cells[3].metric("Constant columns", f"{len(quality.constant_columns):,}")
cells[4].metric("Columns with outliers", f"{len(flagged):,}", help=f"IQR rule with k = {k:g}.")

st.subheader("Missing values")
if quality.missing.empty:
    st.success("No missing values.")
else:
    try:
        chart = missing_heatmap(cache.matrix(dataset_id, df), theme=ui.chart_theme())
        st.altair_chart(chart, width="stretch", theme="streamlit")
        st.caption(chart_caption(chart))
    except ChartError as exc:
        st.warning(str(exc))
    table = quality.missing.rename(
        columns={"column": "Column", "missing": "Missing", "missing_pct": "Missing %"}
    )
    st.dataframe(
        table.round({"Missing %": 1}),
        hide_index=True,
        column_config={"Missing %": st.column_config.NumberColumn(format="%.1f %%")},
    )

st.subheader("Duplicates")
st.multiselect("Compare on columns (empty = all columns)", columns, key="w.q.subset", on_change=save_subset)
duplicates = quality.duplicates
st.markdown(f"{duplicates.duplicate_rows:,} duplicate rows in {duplicates.groups:,} groups")
if duplicates.duplicate_rows:
    st.dataframe(duplicates.sample_rows)
    st.caption(
        "Up to 20 rows that take part in a duplication, each group together; the index is the row number."
    )

st.subheader("Constant columns")
if quality.constant_columns:
    constants = pd.DataFrame(
        [
            {
                "Column": item.name,
                "Value": "" if item.value is None else str(item.value),
                "All missing": item.all_missing,
            }
            for item in quality.constant_columns
        ]
    )
    st.dataframe(constants, hide_index=True)
else:
    st.success("No constant columns.")

st.subheader("Outliers (IQR rule)")
st.select_slider("Fence factor k", options=K_OPTIONS, key="w.q.k", on_change=save_k)
if quality.outliers:
    summary = pd.DataFrame(
        [
            {
                "Column": item.column,
                "Q1": item.q1,
                "Q3": item.q3,
                "Lower fence": item.lower,
                "Upper fence": item.upper,
                "Below": item.n_low,
                "Above": item.n_high,
                "Share %": round(item.pct, 1),
            }
            for item in quality.outliers
        ]
    )
    st.dataframe(
        summary,
        hide_index=True,
        column_config={"Share %": st.column_config.NumberColumn(format="%.1f %%")},
    )
else:
    st.info("No numeric column has at least 4 values and an IQR above 0.")
if quality.zero_iqr:
    st.caption("Skipped because the IQR is 0: " + ", ".join(quality.zero_iqr) + ".")
if flagged:
    state.seed("w.q.outlier_column", flagged[0], flagged)
    column = st.selectbox("Show rows for", flagged, key="w.q.outlier_column")
    rows = outlier_rows(df, column, k)
    st.dataframe(rows.head(OUTLIER_ROWS_SHOWN))
    more = f"; the first {OUTLIER_ROWS_SHOWN} are shown." if len(rows) > OUTLIER_ROWS_SHOWN else "."
    st.caption(f"{len(rows):,} rows have a {column} value outside the fences{more}")
