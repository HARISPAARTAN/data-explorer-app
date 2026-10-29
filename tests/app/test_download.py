"""Download page: three buttons, the view caption, both radios and the Markdown preview."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, NamedTuple

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from data_explorer.core import export
from data_explorer.core.filters import apply_filter, parse_filter
from data_explorer.core.io import load_sample

LABELS = ["Download CSV", "Download profile (JSON)", "Download profile (Markdown)"]
BOM = b"\xef\xbb\xbf"


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


class Sent(NamedTuple):
    data: Any
    file_name: str | None
    mime: str | None


def spy_on_downloads(monkeypatch: pytest.MonkeyPatch) -> dict[str, Sent]:
    """Wrap st.download_button; the dict holds what the last run offered, by widget key."""
    sent: dict[str, Sent] = {}
    original = st.download_button

    def spy(
        label: str, data: Any, file_name: str | None = None, mime: str | None = None, **kwargs: Any
    ) -> Any:
        sent[kwargs["key"]] = Sent(data, file_name, mime)
        return original(label, data, file_name, mime, **kwargs)

    monkeypatch.setattr(st, "download_button", spy)
    return sent


def test_download_bytes_follow_the_dialect(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest], monkeypatch: pytest.MonkeyPatch
) -> None:
    sent = spy_on_downloads(monkeypatch)
    at = loaded("retail_orders")
    spec = parse_filter('`store` = "Milan"')
    at.session_state["de.filter"] = spec
    goto(at, "6_Download")
    view = apply_filter(load_sample("retail_orders")[0], spec)
    assert 0 < len(view) < 6060

    comma = sent["w.d.csv"]
    assert isinstance(comma.data, bytes) and not comma.data.startswith(BOM)
    assert len(comma.data.splitlines()) == len(view) + 1
    assert comma.data.splitlines()[0].startswith(b"order_id,order_date,store,")
    assert comma.file_name is not None and comma.file_name.endswith("_filtered.csv")
    assert comma.mime == export.MIME["csv"]

    at.radio(key="w.d.dialect").set_value("semicolon").run()
    semicolon = sent["w.d.csv"]
    assert isinstance(semicolon.data, bytes) and semicolon.data.startswith(BOM)
    assert semicolon.data.splitlines()[0].removeprefix(BOM).startswith(b"order_id;order_date;store;")
    assert len(semicolon.data.splitlines()) == len(view) + 1
    assert semicolon.file_name is not None and semicolon.file_name.endswith("_filtered.csv")
    assert semicolon.mime == export.MIME["csv"]

    assert sent["w.d.json"].mime == export.MIME["json"]
    assert sent["w.d.json"].file_name is not None and sent["w.d.json"].file_name.endswith("_profile.json")
    assert sent["w.d.md"].mime == export.MIME["md"]
    assert sent["w.d.md"].file_name is not None and sent["w.d.md"].file_name.endswith("_profile.md")
