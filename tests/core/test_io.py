"""core/io.py: detection, loading, header cleanup, missing values, dates, errors and limits."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from typing import Any

import pandas as pd
import pytest

from data_explorer.core import io as dio
from data_explorer.core.io import (
    BROWSER_LIMITS,
    SAMPLES,
    SERVER_LIMITS,
    LoadError,
    LoadOptions,
    MiB,
    current_limits,
    dataset_id,
    detect_decimal,
    detect_delimiter,
    detect_encoding,
    detect_header_row,
    detect_sheet,
    list_sheets,
    load_sample,
    load_table,
    sample_bytes,
)

Read = Callable[[str], bytes]


@pytest.mark.parametrize(
    ("name", "encoding", "delimiter", "decimal"),
    [
        ("utf8_comma.csv", "utf-8", ",", "."),
        ("utf8_bom_semicolon_decimal_comma.csv", "utf-8-sig", ";", ","),
        ("cp1252_semicolon.csv", "cp1252", ";", "."),
        ("latin1_tab.tsv", "latin-1", "\t", "."),
        ("pipe_delimited.txt", "utf-8", "|", "."),
    ],
)
def test_detects_encoding_delimiter_and_decimal(
    fixture_bytes: Read, name: str, encoding: str, delimiter: str, decimal: str
) -> None:
    df, report = load_table(fixture_bytes(name), name)
    assert (report.encoding, report.delimiter, report.decimal) == (encoding, delimiter, decimal)
    assert report.file_type == "csv" and report.header_row == 0
    assert (report.n_rows, report.n_cols) == df.shape
    assert report.sheet is None and report.sheets == ()


def test_values_are_parsed_per_dialect(fixture_bytes: Read) -> None:
    df, _ = load_table(fixture_bytes("utf8_bom_semicolon_decimal_comma.csv"), "a.csv")
    assert df["amount"].dtype == "float64" and df["amount"].iloc[0] == pytest.approx(1234.56)
    assert df["day"].dtype == "datetime64[us]" and df["day"].iloc[0] == pd.Timestamp("2025-03-01")
    assert df["units"].dtype == "int64"
    df, _ = load_table(fixture_bytes("utf8_comma.csv"), "b.csv")
    assert df["label"].iloc[0] == "Caffè" and df["amount"].iloc[1] == pytest.approx(11.5)
    df, _ = load_table(fixture_bytes("cp1252_semicolon.csv"), "c.csv")
    assert df["note"].iloc[0] == "Prezzo in €" and df["price_eur"].dtype == "float64"
    df, _ = load_table(fixture_bytes("latin1_tab.tsv"), "d.tsv")
    assert df["name"].iloc[0] == "Kühl" and df["note"].iloc[0] == "ctrl\x81"


def test_xlsx_picks_the_larger_sheet_and_header_row_four(fixture_bytes: Read) -> None:
    data = fixture_bytes("header_offset_two_sheets.xlsx")
    assert list_sheets(data) == ("Summary", "Data")
    assert detect_sheet(data) == "Data"
    df, report = load_table(data, "offset.xlsx")
    assert (report.file_type, report.sheet, report.sheets, report.header_row) == (
        "xlsx",
        "Data",
        ("Summary", "Data"),
        3,
    )
    assert list(df.columns) == ["month", "region", "amount", "units"]
    assert len(df) == 30 and df["units"].dtype == "int64" and df["amount"].dtype == "float64"
    assert report.encoding is None and report.delimiter is None and report.decimal is None


def test_xlsx_sheet_option_and_missing_sheet(fixture_bytes: Read) -> None:
    data = fixture_bytes("header_offset_two_sheets.xlsx")
    df, report = load_table(data, "offset.xlsx", LoadOptions(sheet="Summary"))
    assert report.sheet == "Summary" and list(df.columns) == ["Summary", "column_2"] and df.shape == (1, 2)
    with pytest.raises(LoadError) as caught:
        load_table(data, "offset.xlsx", LoadOptions(sheet="Nope"))
    assert caught.value.code == "sheet_not_found" and "Summary, Data" in caught.value.message


def test_renames_blank_and_repeated_headers(fixture_bytes: Read) -> None:
    df, report = load_table(fixture_bytes("duplicate_and_blank_headers.csv"), "h.csv")
    assert list(df.columns) == ["id", "name", "column_3", "name_2", "amount", "name_3"]
    assert report.renamed_columns == (
        ("", "column_3"),
        ("name", "name_2"),
        (" amount ", "amount"),
        ("name", "name_3"),
    )
    assert "Column 7 has no header and no values and was removed." in report.warnings
    assert df["amount"].tolist() == [10, 20, 30, 40, 50]


def test_whitespace_cells_become_missing_and_text_is_kept(fixture_bytes: Read) -> None:
    df, report = load_table(fixture_bytes("whitespace_cells.csv"), "w.csv")
    assert report.blank_to_missing == 4
    assert df["name"].isna().sum() == 1
    assert df["score"].dtype == "Int64" and df["score"].isna().sum() == 1
    assert df["note"].isna().sum() == 3 and df["note"].iloc[0] == "  padded  "


def test_date_formats_and_no_month_first(fixture_bytes: Read) -> None:
    df, report = load_table(fixture_bytes("dates_mixed.csv"), "dates.csv")
    parsed = ("iso", "day_first", "dotted", "iso_minutes", "iso_t", "offset")
    for column in parsed:
        assert df[column].dtype == "datetime64[us]", column
    assert set(report.date_columns) == set(parsed)
    assert pd.api.types.is_string_dtype(df["month_first"]) and pd.api.types.is_string_dtype(df["junk"])
    assert df["day_first"].isna().sum() == 1 and df["day_first"].iloc[0] == pd.Timestamp("2025-03-10")
    assert df["dotted"].iloc[0] == pd.Timestamp("2025-03-10")
    assert df["iso_minutes"].iloc[0] == pd.Timestamp("2025-03-01 08:15")
    assert df["iso_t"].iloc[0] == pd.Timestamp("2025-03-01 08:15:30")
    assert df["offset"].iloc[0] == pd.Timestamp("2025-03-01 07:00")
    assert df["junk"].isna().sum() == 3
    assert any("'day_first'" in w and "1 of 20 values" in w for w in report.warnings)
    assert any("'offset'" in w and "UTC" in w for w in report.warnings)


def test_ambiguous_dates_parse_day_first_and_month_first_stays_text() -> None:
    df, _ = load_table(b"d\n01/02/2025\n03/04/2025\n", "a.csv")
    assert df["d"].iloc[0] == pd.Timestamp("2025-02-01")
    df, report = load_table(b"d\n12/31/2024\n01/15/2025\n", "b.csv")
    assert pd.api.types.is_string_dtype(df["d"]) and report.date_columns == ()


def test_booleans_leading_zeros_and_long_integers() -> None:
    df, _ = load_table(b"flag,code,big,n\nTRUE,007,1234567890123456,1\nfalse,010,2,\n", "t.csv")
    assert df["flag"].dtype == "bool" and df["flag"].tolist() == [True, False]
    assert df["code"].tolist() == ["007", "010"]
    assert pd.api.types.is_string_dtype(df["big"])
    assert df["n"].dtype == "Int64"


def test_decimal_comma_with_thousands_and_negatives() -> None:
    df, report = load_table(b"a;b\n-1.234,5;7\n2,25;-3\n", "n.csv")
    assert report.decimal == ","
    assert df["a"].tolist() == [-1234.5, 2.25] and df["b"].tolist() == [7, -3]


@pytest.mark.parametrize(
    ("fixture", "file_name", "code"),
    [
        ("empty.csv", "empty.csv", "empty_file"),
        ("legacy.xls", "legacy.xls", "unsupported_type"),
        ("not_a_table.bin", "not_a_table.bin", "unsupported_type"),
        ("not_a_table.bin", "not_a_table.csv", "decode_failed"),
        ("not_a_table.bin", "not_a_table.xlsx", "parse_failed"),
    ],
)
def test_error_codes_for_bad_files(fixture_bytes: Read, fixture: str, file_name: str, code: str) -> None:
    with pytest.raises(LoadError) as caught:
        load_table(fixture_bytes(fixture), file_name)
    assert caught.value.code == code
    assert file_name in caught.value.message and str(caught.value) == caught.value.message


def test_blank_text_and_ragged_rows() -> None:
    with pytest.raises(LoadError) as caught:
        load_table(b" \n\n", "blank.csv")
    assert caught.value.code == "no_columns"
    with pytest.raises(LoadError) as caught:
        load_table(b"a,b\n1,2\n1,2,3\n", "ragged.csv")
    assert caught.value.code == "parse_failed"


def test_limits_raise_with_the_limit_in_the_message(tight_limits: Any) -> None:
    cases = [
        (b"a,b\n" + b"1,2\n" * 600, "too_large", "2,000 bytes"),
        (b"a\n" + b"1\n" * 60, "too_many_rows", "the limit is 50 rows"),
        (b"a,b,c,d,e,f\n1,2,3,4,5,6\n", "too_many_columns", "the limit is 5 columns"),
    ]
    for data, code, text in cases:
        with pytest.raises(LoadError) as caught:
            load_table(data, "big.csv", limits=tight_limits)
        assert caught.value.code == code and text in caught.value.message


def test_check_order_empty_then_size_then_type(tight_limits: Any) -> None:
    with pytest.raises(LoadError, match="is empty") as caught:
        load_table(b"", "x.xls")
    assert caught.value.code == "empty_file"
    with pytest.raises(LoadError) as caught:
        load_table(b"x" * 3_000, "x.xls", limits=tight_limits)
    assert caught.value.code == "too_large"


def test_header_only_gives_zero_rows(fixture_bytes: Read) -> None:
    df, report = load_table(fixture_bytes("header_only.csv"), "header_only.csv")
    assert df.shape == (0, 3) and report.n_rows == 0 and list(df.columns) == ["a", "b", "c"]


def test_options_override_detection(fixture_bytes: Read) -> None:
    options = LoadOptions(encoding="utf-8-sig", delimiter=";", decimal=",", header_row=0)
    df, report = load_table(fixture_bytes("utf8_bom_semicolon_decimal_comma.csv"), "a.csv", options)
    assert report.delimiter == ";" and df["amount"].iloc[0] == pytest.approx(1234.56)
    with pytest.raises(LoadError) as caught:
        load_table(fixture_bytes("cp1252_semicolon.csv"), "c.csv", LoadOptions(encoding="utf-8"))
    assert caught.value.code == "decode_failed" and "Reading options" in caught.value.message


def test_load_options_validate_and_round_trip() -> None:
    assert (
        LoadOptions().to_json()
        == '{"decimal":null,"delimiter":null,"encoding":null,"header_row":null,"sheet":null}'
    )
    options = LoadOptions(encoding="cp1252", delimiter="\t", decimal=",", sheet="Data", header_row=3)
    assert LoadOptions.from_json(options.to_json()) == options
    for bad in (
        {"delimiter": ":"},
        {"encoding": "utf-16"},
        {"decimal": ";"},
        {"header_row": 20},
        {"header_row": -1},
    ):
        with pytest.raises(ValueError):
            LoadOptions(**bad)


def test_detect_encoding() -> None:
    assert detect_encoding(b"\xef\xbb\xbfa,b") == "utf-8-sig"
    assert detect_encoding("é,ü".encode()) == "utf-8"
    assert detect_encoding(b"a" * (MiB - 1) + "é".encode()) == "utf-8"
    assert detect_encoding("€".encode("cp1252")) == "cp1252"
    assert detect_encoding(b"\x81abc") == "latin-1"


def test_detect_delimiter_and_decimal() -> None:
    assert detect_delimiter("a;b;c\n1;2;3\n") == ";"
    assert detect_delimiter("a|b\n1|2\n") == "|"
    assert detect_delimiter("a\tb\n1\t2\n") == "\t"
    assert detect_delimiter('a,b\n"x;y",1\n"z;w",2\n') == ","
    assert detect_delimiter("") == ","
    assert detect_decimal("a;b\n1,5;2,25\n3,5;4\n", ";") == ","
    assert detect_decimal("a;b\n1.5;2.25\n", ";") == "."
    assert detect_decimal("a,b\n1,5\n", ",") == "."
    assert detect_decimal("d;v\n01.02.2025;1,5\n", ";") == ","


def test_detect_header_row() -> None:
    assert detect_header_row([["Title"], [], ["a", "b", "c"], ["1", "2", "3"]]) == 2
    assert detect_header_row([["1", "2"], ["3", "4"]]) == 0
    assert detect_header_row([["a", "b"], ["1", "2"]]) == 0
    assert detect_header_row([["T", None, None], [None, None, None], ["x", "y", "z"], [1, 2.5, "q"]]) == 2
    assert detect_header_row([]) == 0


def test_current_limits(monkeypatch: pytest.MonkeyPatch) -> None:
    assert current_limits() == SERVER_LIMITS
    monkeypatch.setenv("DATA_EXPLORER_MAX_MB", "10")
    monkeypatch.setenv("DATA_EXPLORER_MAX_ROWS", "100")
    assert current_limits() == dio.Limits(10 * MiB, 100, 500)
    monkeypatch.setenv("DATA_EXPLORER_MAX_MB", "500")
    monkeypatch.setenv("DATA_EXPLORER_MAX_COLS", "900")
    assert current_limits() == dio.Limits(50 * MiB, 100, 500)
    for bad in ("abc", "0", "-5", "1.5"):
        monkeypatch.setenv("DATA_EXPLORER_MAX_COLS", bad)
        with pytest.raises(ValueError, match="DATA_EXPLORER_MAX_COLS"):
            current_limits()
    monkeypatch.setenv("DATA_EXPLORER_MAX_COLS", "")
    assert current_limits().max_cols == 500
    monkeypatch.setattr(sys, "platform", "emscripten")
    assert current_limits() == BROWSER_LIMITS


def test_samples_registry_and_ids() -> None:
    assert list(SAMPLES) == ["retail_orders", "sensor_readings", "client_survey"]
    assert [info.title for info in SAMPLES.values()] == ["Retail orders", "Sensor readings", "Client survey"]
    with pytest.raises(KeyError):
        load_sample("nope")
    data = sample_bytes("retail_orders")
    first = dataset_id(data, LoadOptions())
    assert len(first) == 16 and all(c in "0123456789abcdef" for c in first)
    assert dataset_id(data, LoadOptions(delimiter=";")) != first


def test_report_is_json_safe(fixture_bytes: Read) -> None:
    _, report = load_table(fixture_bytes("duplicate_and_blank_headers.csv"), "h.csv")
    payload = report.to_dict()
    assert json.loads(json.dumps(payload)) == payload
    assert payload["renamed_columns"][0] == ["", "column_3"]
    assert payload["sha256"] == report.sha256 and len(report.sha256) == 64
