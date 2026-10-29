"""Download: the current view as CSV in two dialects, the profile as JSON or Markdown."""

from __future__ import annotations

import json

import streamlit as st

from data_explorer.app import cache, state, ui
from data_explorer.core.export import export_file_name, profile_json, profile_markdown, to_csv_bytes
from data_explorer.core.filters import FilterError, format_filter

DIALECTS = {
    "comma": "Comma, UTF-8",
    "semicolon": "Semicolon, decimal comma, UTF-8 with BOM (Excel with Italian or German settings)",
}
SCOPES = {"dataset": "Full dataset", "view": "Current view"}


def save_dialect() -> None:
    st.session_state[state.CSV_DIALECT] = st.session_state["w.d.dialect"]


def save_scope() -> None:
    st.session_state[state.PROFILE_SCOPE] = st.session_state["w.d.scope"]


ui.page_setup("Download")
df, report, dataset_id = ui.require_dataset()
st.title("Download")
spec = state.view_spec()
view_json = state.view_json()
try:
    view = cache.view(dataset_id, view_json, df)
except FilterError as exc:
    st.error(exc.message)
    st.stop()
except Exception:
    ui.unexpected("applying the filter")
    st.stop()

st.subheader("Data")
filter_text = format_filter(spec.filter)
shown_filter = ui.inline_code(filter_text) if filter_text else "none"
st.caption(f"Current view: {len(view):,} rows × {len(view.columns):,} columns · filter: {shown_filter}")
state.seed("w.d.dialect", st.session_state[state.CSV_DIALECT], list(DIALECTS))
dialect = st.radio(
    "CSV format", list(DIALECTS), format_func=DIALECTS.__getitem__, key="w.d.dialect", on_change=save_dialect
)
try:
    csv_bytes = to_csv_bytes(view, dialect)
except Exception:
    ui.unexpected("writing the CSV file")
    st.stop()
st.download_button(
    "Download CSV",
    csv_bytes,
    export_file_name(report.file_name, "csv"),
    mime="text/csv",
    key="w.d.csv",
    on_click="ignore",
)

st.subheader("Profile")
state.seed("w.d.scope", st.session_state[state.PROFILE_SCOPE], list(SCOPES))
scope = st.radio(
    "Profile of",
    list(SCOPES),
    format_func=SCOPES.__getitem__,
    horizontal=True,
    key="w.d.scope",
    on_change=save_scope,
)
frame, frame_key = (view, view_json) if scope == "view" else (df, "")
subset = [column for column in st.session_state[state.Q_SUBSET] if column in frame.columns]
k = float(st.session_state[state.Q_K])
try:
    profile = cache.profile(dataset_id, frame, frame_key)
    quality = cache.quality(dataset_id, k, json.dumps(subset), frame, frame_key)
    as_json = profile_json(report, profile, quality, spec, len(view), scope=scope)
    as_markdown = profile_markdown(report, profile, quality, spec, len(view), scope=scope)
except Exception:
    ui.unexpected("writing the profile")
    st.stop()
st.download_button(
    "Download profile (JSON)",
    as_json,
    export_file_name(report.file_name, "json"),
    mime="application/json",
    key="w.d.json",
    on_click="ignore",
)
st.download_button(
    "Download profile (Markdown)",
    as_markdown,
    export_file_name(report.file_name, "md"),
    mime="text/markdown",
    key="w.d.md",
    on_click="ignore",
)
with st.expander("Preview the Markdown profile"):
    st.markdown(as_markdown)
