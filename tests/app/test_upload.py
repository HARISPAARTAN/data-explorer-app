"""Upload page: first render, sample and file loads, reading options, errors in place."""

from __future__ import annotations

import io
import zipfile
from collections.abc import Callable
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest


def captions(block: object) -> list[str]:
    return [element.value for element in block.caption]  # type: ignore[attr-defined]


def test_first_render(app: Callable[[], AppTest]) -> None:
    at = app()
    at.run()
    assert not at.exception
    assert at.title[0].value == "Upload"
    assert at.radio(key="w.source").value == "Upload a file"
    assert at.button(key="w.load").disabled
    assert "No dataset loaded" in captions(at.sidebar)
    assert "Up to 50 MB, 1,000,000 rows and 500 columns on this server" in captions(at.main)
    assert any(caption.startswith("Runtime: server · Python 3.") for caption in captions(at.sidebar))
    assert "Rebuilt from memory as a demo. The original client's name and data are not used." in captions(
        at.sidebar
    )


def test_sample_load_sets_the_dataset(loaded: Callable[..., AppTest]) -> None:
    at = loaded("retail_orders")
    assert at.success[0].value == "Loaded retail_orders.csv: 6,060 rows × 11 columns."
    assert at.main.caption[-1].value.startswith("Encoding utf-8-sig · delimiter semicolon · decimal comma")
    assert len(at.session_state["de.dataset_id"]) == 16
    assert at.session_state["de.source"] == "sample" and at.session_state["de.df"].shape == (6_060, 11)
    assert "retail_orders.csv · 6,060 rows × 11 columns" in captions(at.sidebar)
    at.run()
    assert not at.success
    assert at.info[0].value == "Current dataset: retail_orders.csv · 6,060 rows × 11 columns."


def test_survey_sample_reads_the_workbook(loaded: Callable[..., AppTest]) -> None:
    at = loaded("client_survey")
    assert at.success[0].value == "Loaded client_survey.xlsx: 1,224 rows × 11 columns."
    assert "sheet Responses of 2" in at.main.caption[-1].value and "header row 4" in at.main.caption[-1].value


def test_uploaded_file_loads(app: Callable[[], AppTest], fixture_bytes: Callable[[str], bytes]) -> None:
    at = app()
    at.run()
    at.file_uploader[0].upload("utf8_comma.csv", fixture_bytes("utf8_comma.csv"), "text/csv").run()
    assert not at.button(key="w.load").disabled
    at.button(key="w.load").click().run()
    assert at.success[0].value == "Loaded utf8_comma.csv: 20 rows × 4 columns."
    assert at.session_state["de.source"] == "upload"


def test_header_row_option(app: Callable[[], AppTest], fixture_bytes: Callable[[str], bytes]) -> None:
    at = app()
    at.run()
    at.file_uploader[0].upload("utf8_comma.csv", fixture_bytes("utf8_comma.csv"), "text/csv").run()
    at.number_input(key="w.header_row").set_value(2).run()
    at.button(key="w.load").click().run()
    assert at.success[0].value == "Loaded utf8_comma.csv: 19 rows × 4 columns."
    assert "header row 2" in at.main.caption[-1].value


def test_workbook_offers_its_sheets(
    app: Callable[[], AppTest], fixture_bytes: Callable[[str], bytes]
) -> None:
    at = app()
    at.run()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    at.file_uploader[0].upload(
        "header_offset_two_sheets.xlsx", fixture_bytes("header_offset_two_sheets.xlsx"), mime
    ).run()
    assert at.selectbox(key="w.sheet").options == ["Detect", "Summary", "Data"]
    at.button(key="w.load").click().run()
    assert at.success[0].value == "Loaded header_offset_two_sheets.xlsx: 30 rows × 4 columns."


def test_workbook_is_opened_once_per_upload_not_once_per_rerun(
    app: Callable[[], AppTest], fixture_bytes: Callable[[str], bytes], monkeypatch: pytest.MonkeyPatch
) -> None:
    from data_explorer.app import cache

    calls: list[str] = []
    real = cache.list_sheets

    def counting(*args: Any, **kwargs: Any) -> tuple[str, ...]:
        calls.append("opened")
        return real(*args, **kwargs)

    monkeypatch.setattr(cache, "list_sheets", counting)
    at = app()
    at.run()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    at.file_uploader[0].upload(
        "header_offset_two_sheets.xlsx", fixture_bytes("header_offset_two_sheets.xlsx"), mime
    ).run()
    at.number_input(key="w.header_row").set_value(2).run()
    at.selectbox(key="w.delimiter").set_value("Tab").run()
    at.run()
    assert not at.exception
    assert at.selectbox(key="w.sheet").options == ["Detect", "Summary", "Data"]
    assert calls == ["opened"]


def test_workbook_that_unpacks_too_large_is_refused_in_place(
    app: Callable[[], AppTest], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DATA_EXPLORER_MAX_MB", "1")  # 10 MB once unpacked
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("xl/sharedStrings.xml", b"<sst>" + b"<si><t>x</t></si>" * 700_000 + b"</sst>")
    at = app()
    at.run()
    mime = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    at.file_uploader[0].upload("bomb.xlsx", buffer.getvalue(), mime).run()
    assert at.selectbox(key="w.sheet").options == ["Detect"]
    at.button(key="w.load").click().run()
    assert not at.exception
    assert (
        at.error[0].value
        == "bomb.xlsx unpacks to 11.3 MB; the limit is 10 MB unpacked (10 times the upload limit)."
    )


def test_legacy_xls_is_rejected_in_place(
    app: Callable[[], AppTest], fixture_bytes: Callable[[str], bytes]
) -> None:
    at = app()
    at.run()
    at.file_uploader[0].upload("legacy.xls", fixture_bytes("legacy.xls"), "application/vnd.ms-excel").run()
    at.button(key="w.load").click().run()
    assert not at.exception
    assert at.error[0].value == (
        "legacy.xls: this file type is not supported. Use .csv, .tsv, .txt or .xlsx; "
        "save legacy .xls workbooks as .xlsx first."
    )
    assert "de.df" not in at.session_state


def test_row_limit_from_the_environment(app: Callable[[], AppTest], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATA_EXPLORER_MAX_ROWS", "100")
    at = app()
    at.run()
    at.radio(key="w.source").set_value("Use a sample dataset").run()
    at.button(key="w.load").click().run()
    assert at.error[0].value == "retail_orders.csv has more than 100 rows; the limit is 100 rows."
