"""Quality page on the retail sample: missing values, duplicates, constants, outliers and k."""

from __future__ import annotations

from collections.abc import Callable

import pandas as pd
from streamlit.testing.v1 import AppTest


def table_with(at: AppTest, column: str) -> pd.DataFrame:
    for element in at.dataframe:
        if column in element.value.columns:
            return element.value
    raise AssertionError(f"no table with a {column} column")


def texts(at: AppTest) -> list[str]:
    return [element.value for element in at.markdown]


def test_sections(loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]) -> None:
    at = goto(loaded("retail_orders"), "3_Quality")
    metrics = {metric.label: metric.value for metric in at.metric}
    assert metrics == {
        "Columns with missing values": "1",
        "Missing cells": "0.3 %",
        "Duplicate rows": "60",
        "Constant columns": "1",
        "Columns with outliers": "3",
    }
    missing = table_with(at, "Missing %")
    assert missing.iloc[0].to_dict() == {"Column": "discount_pct", "Missing": 180, "Missing %": 3.0}
    assert len(at.get("vega_lite_chart")) == 1
    assert "60 duplicate rows in 60 groups" in texts(at)
    constants = table_with(at, "All missing")
    assert constants["Column"].tolist() == ["country"] and constants["Value"].tolist() == ["IT"]
    outliers = table_with(at, "Upper fence")
    assert outliers.set_index("Column").loc["units", "Above"] == 15
    assert at.selectbox(key="w.q.outlier_column").options == ["units", "unit_price_eur", "revenue_eur"]
    assert len(at.dataframe[-1].value) == 15


def test_fence_factor_changes_the_outliers(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = goto(loaded("retail_orders"), "3_Quality")
    before = table_with(at, "Upper fence").set_index("Column")
    at.select_slider(key="w.q.k").set_value(3.0).run()
    after = table_with(at, "Upper fence").set_index("Column")
    assert at.session_state["de.q_k"] == 3.0
    assert after.loc["units", "Upper fence"] > before.loc["units", "Upper fence"]
    assert after.loc["unit_price_eur", "Above"] == 0 < before.loc["unit_price_eur", "Above"]


def test_duplicate_subset(loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]) -> None:
    at = goto(loaded("retail_orders"), "3_Quality")
    at.multiselect(key="w.q.subset").set_value(["store"]).run()
    assert at.session_state["de.q_subset"] == ("store",)
    assert "6,052 duplicate rows in 8 groups" in texts(at)
    goto(at, "2_Overview")
    goto(at, "3_Quality")
    assert at.multiselect(key="w.q.subset").value == ["store"]


def test_dataset_without_missing_values(
    app: Callable[[], AppTest], goto: Callable[[AppTest, str], AppTest], fixture_bytes: Callable[[str], bytes]
) -> None:
    at = app()
    at.run()
    at.file_uploader[0].upload(
        "two_numeric_columns.csv", fixture_bytes("two_numeric_columns.csv"), "text/csv"
    ).run()
    at.button(key="w.load").click().run()
    goto(at, "3_Quality")
    assert "No missing values." in [element.value for element in at.success]
    assert len(at.get("vega_lite_chart")) == 0
