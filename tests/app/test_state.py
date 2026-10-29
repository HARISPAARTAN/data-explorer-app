"""A new dataset resets the view state and keeps the download choices (docs/architecture.md)."""

from __future__ import annotations

from collections.abc import Callable

from streamlit.testing.v1 import AppTest

from data_explorer.core.filters import FilterSpec, SortKey, parse_filter


def test_second_dataset_resets_the_view_state(loaded: Callable[..., AppTest]) -> None:
    at = loaded("retail_orders")
    first = at.session_state["de.dataset_id"]
    at.session_state["de.filter"] = parse_filter("`units` > 3")
    at.session_state["de.columns"] = ("store",)
    at.session_state["de.sort"] = (SortKey("units", True),)
    at.session_state["de.q_subset"] = ("store",)
    at.session_state["de.q_k"] = 3.0
    at.session_state["de.chart"] = {"type": "Bar", "category": "store"}
    at.session_state["de.csv_dialect"] = "semicolon"
    at.session_state["de.profile_scope"] = "view"
    at.selectbox(key="w.sample").set_value("sensor_readings").run()
    at.button(key="w.load").click().run()
    assert not at.exception
    assert at.session_state["de.dataset_id"] != first
    assert at.session_state["de.source"] == "sample"
    assert at.session_state["de.df"].shape == (8640, 9)
    assert at.session_state["de.filter"] == FilterSpec()
    assert at.session_state["de.columns"] is None
    assert at.session_state["de.sort"] == ()
    assert at.session_state["de.q_subset"] == ()
    assert at.session_state["de.q_k"] == 1.5
    assert at.session_state["de.chart"] == {"type": "Histogram"}
    assert at.session_state["de.csv_dialect"] == "semicolon"
    assert at.session_state["de.profile_scope"] == "view"


def test_loading_the_same_sample_again_keeps_the_id(loaded: Callable[..., AppTest]) -> None:
    at = loaded("retail_orders")
    first = at.session_state["de.dataset_id"]
    at.button(key="w.load").click().run()
    assert at.session_state["de.dataset_id"] == first and len(first) == 16
