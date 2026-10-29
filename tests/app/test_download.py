"""Download page: three buttons, the view caption, both radios and the Markdown preview."""

from __future__ import annotations

from collections.abc import Callable

from streamlit.testing.v1 import AppTest

from data_explorer.core.filters import apply_filter, parse_filter
from data_explorer.core.io import load_sample

LABELS = ["Download CSV", "Download profile (JSON)", "Download profile (Markdown)"]


def preview(at: AppTest) -> str:
    return next(element.value for element in at.markdown if element.value.startswith("# Data profile:"))


def test_buttons_and_radios(loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]) -> None:
    at = goto(loaded("retail_orders"), "6_Download")
    assert [button.proto.label for button in at.get("download_button")] == LABELS
    assert at.main.caption[0].value == "Current view: 6,060 rows × 11 columns · filter: none"
    assert "Profile of the full dataset." in preview(at)
    at.radio(key="w.d.dialect").set_value("semicolon").run()
    at.radio(key="w.d.scope").set_value("view").run()
    assert at.session_state["de.csv_dialect"] == "semicolon"
    assert at.session_state["de.profile_scope"] == "view"
    assert "Profile of the current view." in preview(at)
    goto(at, "2_Overview")
    goto(at, "6_Download")
    assert at.radio(key="w.d.dialect").value == "semicolon" and at.radio(key="w.d.scope").value == "view"
    assert [button.proto.label for button in at.get("download_button")] == LABELS


def test_view_caption_names_the_filter(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = loaded("retail_orders")
    spec = parse_filter('`store` IN ("Milan", "Como")')
    at.session_state["de.filter"] = spec
    at.session_state["de.columns"] = ("store", "units")
    goto(at, "6_Download")
    rows = len(apply_filter(load_sample("retail_orders")[0], spec))
    expected = f'Current view: {rows:,} rows × 2 columns · filter: `` `store` IN ("Milan", "Como") ``'
    assert at.main.caption[0].value == expected
    at.radio(key="w.d.scope").set_value("view").run()
    assert f"- Rows in view: {rows:,}" in preview(at)
    assert "| Rows | Columns |" in preview(at) and f"| {rows:,} | 2 |" in preview(at)
