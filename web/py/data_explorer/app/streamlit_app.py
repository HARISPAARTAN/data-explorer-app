"""Upload: the entrypoint of the app, on the server and in the browser."""

from __future__ import annotations

import streamlit as st

from data_explorer.app import cache, state, ui
from data_explorer.core.io import (
    DEFAULT_OPTIONS,
    SAMPLES,
    LoadError,
    LoadOptions,
    LoadReport,
    current_limits,
    dataset_id,
    list_sheets,
    sample_bytes,
)

SOURCES = ["Upload a file", "Use a sample dataset"]
ENCODINGS = ["Detect", "utf-8", "utf-8-sig", "cp1252", "latin-1"]
DELIMITERS = {"Detect": None, "Comma": ",", "Semicolon": ";", "Tab": "\t", "Pipe": "|"}
DECIMALS = {"Detect": None, "Point": ".", "Comma": ","}


def sheet_names(data: bytes, file_name: str) -> list[str]:
    try:
        return list(list_sheets(data, file_name))
    except LoadError:
        return []


def show_success(report: LoadReport) -> None:
    st.success(f"Loaded {report.file_name}: {report.n_rows:,} rows × {report.n_cols:,} columns.")
    for warning in report.warnings:
        st.warning(warning)
    st.page_link("pages/2_Overview.py", label="Continue to Overview")
    st.caption(ui.reading_caption(report))


caption_slot = ui.page_setup("Upload")

st.title("Upload")
st.write(
    "Open a CSV or Excel file, or one of three sample datasets, and look at its statistics, data quality, "
    "filters and charts, then download the result."
)
privacy = "The data stays in this session's memory and is not stored."
if ui.IN_BROWSER:
    privacy += " In this browser demo the file never leaves your device."
st.write(privacy)

state.seed("w.source", SOURCES[1] if st.session_state.get(state.SOURCE) == "sample" else SOURCES[0], SOURCES)
source = st.radio("Source", SOURCES, horizontal=True, key="w.source")
limits = current_limits()
uploaded = None
sample_key = None
options = DEFAULT_OPTIONS

if source == SOURCES[0]:
    uploaded = st.file_uploader("CSV or Excel file", type=["csv", "tsv", "txt", "xlsx", "xls"], key="w.file")
    st.caption(ui.limits_caption(limits))
    with st.expander("Reading options"):
        encoding = st.selectbox("Encoding", ENCODINGS, key="w.encoding")
        delimiter = st.selectbox("Delimiter", list(DELIMITERS), key="w.delimiter")
        decimal = st.selectbox("Decimal separator", list(DECIMALS), key="w.decimal")
        sheet = "Detect"
        if uploaded is not None and uploaded.name.lower().endswith(".xlsx"):
            sheets = ["Detect", *sheet_names(uploaded.getvalue(), uploaded.name)]
            state.seed("w.sheet", "Detect", sheets)
            sheet = st.selectbox("Sheet", sheets, key="w.sheet")
        header_row = st.number_input(
            "Header row (0 = detect, 1 = first row)", min_value=0, max_value=20, step=1, key="w.header_row"
        )
    options = LoadOptions(
        encoding=None if encoding == "Detect" else encoding,
        delimiter=DELIMITERS[delimiter],
        decimal=DECIMALS[decimal],
        sheet=None if sheet == "Detect" else sheet,
        header_row=None if int(header_row) == 0 else int(header_row) - 1,
    )
else:
    keys = list(SAMPLES)
    state.seed("w.sample", keys[0], keys)
    sample_key = st.selectbox(
        "Sample dataset", keys, format_func=lambda key: SAMPLES[key].title, key="w.sample"
    )
    info = SAMPLES[sample_key]
    st.caption(f"{info.description} Planted defects: {'; '.join(info.defects)}.")

loaded_now = False
if st.button("Load", type="primary", key="w.load", disabled=source == SOURCES[0] and uploaded is None):
    try:
        with st.spinner("Reading the file"):
            if uploaded is not None:
                data = uploaded.getvalue()
                df, report = cache.load(data, uploaded.name, options.to_json(), cache.limits_key(limits))
                new_id, kind = dataset_id(data, options), "upload"
            else:
                assert sample_key is not None
                df, report = cache.sample(sample_key, cache.limits_key(limits))
                new_id, kind = dataset_id(sample_bytes(sample_key), DEFAULT_OPTIONS), "sample"
    except LoadError as exc:
        st.error(exc.message)
    except Exception:
        ui.unexpected("reading the file")
    else:
        state.set_dataset(new_id, df, report, kind)
        caption_slot.caption(ui.dataset_caption())
        loaded_now = True

if state.has_dataset():
    current: LoadReport = st.session_state[state.REPORT]
    if loaded_now:
        show_success(current)
    else:
        st.info(
            f"Current dataset: {current.file_name} · {current.n_rows:,} rows × {current.n_cols:,} columns."
        )
