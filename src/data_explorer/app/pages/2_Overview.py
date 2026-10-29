"""Overview: size, missing cells, duplicates, memory, column statistics and a preview."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from data_explorer.app import cache, ui
from data_explorer.core.profile import ColumnProfile

PREVIEW_ROWS = 100


def most_frequent(column: ColumnProfile) -> str:
    if column.top:
        value, count = column.top[0]
        return f"{value} ({count:,})"
    if column.kind == "boolean":
        return f"true {column.stats.get('true', 0):,} · false {column.stats.get('false', 0):,}"
    return ""


def column_table(columns: tuple[ColumnProfile, ...]) -> pd.DataFrame:
    rows = [
        {
            "Column": column.name,
            "Type": column.kind,
            "pandas dtype": column.dtype,
            "Missing %": round(column.missing_pct, 1),
            "Unique": column.unique,
            "Min": ui.stat_text(column.stats.get("min")),
            "Median": ui.stat_text(column.stats.get("median")),
            "Mean": ui.stat_text(column.stats.get("mean")),
            "Max": ui.stat_text(column.stats.get("max")),
            "Most frequent": most_frequent(column),
        }
        for column in columns
    ]
    return pd.DataFrame(rows)


ui.page_setup("Overview")
df, report, dataset_id = ui.require_dataset()
st.title("Overview")

try:
    profile = cache.profile(dataset_id, df)
except Exception:
    ui.unexpected("profiling the dataset")
    st.stop()

cells = st.columns(5)
cells[0].metric("Rows", f"{profile.n_rows:,}")
cells[1].metric("Columns", f"{profile.n_cols:,}")
cells[2].metric(
    "Missing cells",
    ui.pct(profile.missing_cells_pct),
    help=f"{profile.missing_cells:,} of {profile.n_cells:,} cells are missing.",
)
cells[3].metric(
    "Duplicate rows", f"{profile.duplicate_rows:,}", help="Rows identical in every column to an earlier row."
)
cells[4].metric(
    "Memory", f"{profile.memory_bytes / ui.MiB:,.1f} MB", help="Memory used by the table in this session."
)
st.caption(" · ".join(f"{count} {kind}" for kind, count in profile.kinds.items() if count))

st.subheader("Columns")
st.dataframe(column_table(profile.columns), hide_index=True)

st.subheader("Preview")
st.dataframe(df.head(PREVIEW_ROWS))
st.caption(f"First {min(PREVIEW_ROWS, len(df)):,} of {len(df):,} rows")

with st.expander("How the file was read"):
    st.json(report.to_dict())
