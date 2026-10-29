"""Overview page on the retail sample."""

from __future__ import annotations

from collections.abc import Callable

from streamlit.testing.v1 import AppTest


def test_metrics(loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]) -> None:
    at = goto(loaded("retail_orders"), "2_Overview")
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics["Rows"] == "6,060" and metrics["Columns"] == "11" and metrics["Duplicate rows"] == "60"
    assert metrics["Missing cells"] == "0.3 %" and metrics["Memory"].endswith(" MB")
    assert at.title[0].value == "Overview"


def test_kinds_columns_and_preview(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = goto(loaded("retail_orders"), "2_Overview")
    captions = [caption.value for caption in at.main.caption]
    assert captions[0] == "4 numeric · 1 datetime · 5 categorical · 1 text"
    assert "First 100 of 6,060 rows" in captions
    table = at.dataframe[0].value
    assert list(table.columns) == [
        "Column",
        "Type",
        "pandas dtype",
        "Missing %",
        "Unique",
        "Min",
        "Median",
        "Mean",
        "Max",
        "Most frequent",
    ]
    discount = table[table["Column"] == "discount_pct"].iloc[0]
    assert discount["Missing %"] == 3.0 and discount["Type"] == "numeric" and discount["Max"] == "20"
    assert table[table["Column"] == "country"].iloc[0]["Most frequent"] == "IT (6,060)"
    assert at.dataframe[1].value.shape == (100, 11)
    assert at.json[0].value is not None
