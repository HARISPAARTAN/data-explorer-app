"""``st.cache_data`` wrappers (docs/architecture.md, "Caching").

Entries are keyed by the dataset id and canonical JSON; parameters that start with an underscore are
not hashed, so a large frame is never hashed on a rerun. No ttl, no persistence, nothing on disk.
"""

from __future__ import annotations

import json

import pandas as pd
import streamlit as st

from data_explorer.core.filters import apply_view, view_from_json
from data_explorer.core.io import Limits, LoadOptions, LoadReport, load_sample, load_table
from data_explorer.core.profile import DatasetProfile, profile_dataset
from data_explorer.core.quality import QualityReport, missing_matrix, quality_report

LimitsKey = tuple[int, int, int]


def limits_key(limits: Limits) -> LimitsKey:
    return (limits.max_bytes, limits.max_rows, limits.max_cols)


@st.cache_data(max_entries=3, show_spinner=False)
def load(
    data: bytes, file_name: str, options_json: str, limits: LimitsKey
) -> tuple[pd.DataFrame, LoadReport]:
    return load_table(data, file_name, LoadOptions.from_json(options_json), Limits(*limits))


@st.cache_data(max_entries=3, show_spinner=False)
def sample(key: str, limits: LimitsKey) -> tuple[pd.DataFrame, LoadReport]:
    return load_sample(key, Limits(*limits))


@st.cache_data(max_entries=16, show_spinner=False)
def profile(dataset_id: str, _df: pd.DataFrame, view_json: str = "") -> DatasetProfile:
    return profile_dataset(_df)


@st.cache_data(max_entries=16, show_spinner=False)
def quality(
    dataset_id: str, k: float, subset_json: str, _df: pd.DataFrame, view_json: str = ""
) -> QualityReport:
    subset = tuple(json.loads(subset_json))
    return quality_report(_df, k, subset or None)


@st.cache_data(max_entries=16, show_spinner=False)
def matrix(dataset_id: str, _df: pd.DataFrame) -> pd.DataFrame:
    return missing_matrix(_df)


@st.cache_data(max_entries=16, show_spinner=False)
def view(dataset_id: str, view_json: str, _df: pd.DataFrame) -> pd.DataFrame:
    return apply_view(_df, view_from_json(view_json))
