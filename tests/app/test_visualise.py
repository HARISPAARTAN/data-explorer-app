"""Visualise page: every chart type renders, controls are remembered, errors and gaps are explained."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from streamlit.testing.v1 import AppTest

from data_explorer.core.filters import parse_filter

CHARTS = ["Histogram", "Bar", "Line", "Scatter", "Correlation heatmap"]


@pytest.mark.parametrize("chart", CHARTS)
def test_each_chart_type_renders(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest], chart: str
) -> None:
    at = goto(loaded("retail_orders"), "5_Visualise")
    at.radio(key="w.c.type").set_value(chart).run()
    assert not at.exception and not at.warning
    assert len(at.get("vega_lite_chart")) == 1
    assert at.session_state["de.chart"]["type"] == chart
    assert at.main.caption[-1].value.endswith(".")


def test_captions_state_the_aggregation(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = goto(loaded("retail_orders"), "5_Visualise")
    at.radio(key="w.c.type").set_value("Line").run()
    assert at.main.caption[-1].value == "Weekly count of rows; weeks run Monday to Sunday."
    at.selectbox(key="w.c.measure").set_value("revenue_eur").run()
    at.selectbox(key="w.c.agg").set_value("sum").run()
    assert at.main.caption[-1].value == "Weekly sum of revenue_eur; weeks run Monday to Sunday."
    at.radio(key="w.c.type").set_value("Bar").run()
    assert at.selectbox(key="w.c.category").options[0] == "store"
    assert at.main.caption[-1].value == "Sum of revenue_eur per store."
    goto(at, "2_Overview")
    goto(at, "5_Visualise")
    assert at.radio(key="w.c.type").value == "Bar" and at.selectbox(key="w.c.category").value == "store"


def test_explore_filter_is_used(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = loaded("retail_orders")
    at.session_state["de.filter"] = parse_filter('`store` = "Milan"')
    goto(at, "5_Visualise")
    milan = int((at.session_state["de.df"]["store"] == "Milan").sum())
    assert at.main.caption[0].value == f"Explore filter: {milan:,} of 6,060 rows"
    at.toggle(key="w.c.filtered").set_value(False).run()
    assert at.main.caption[0].value == "All 6,060 rows; the Explore filter is not used"
    assert at.session_state["de.chart"]["filtered"] is False


def test_missing_kinds_and_chart_errors(
    app: Callable[[], AppTest], goto: Callable[[AppTest, str], AppTest], fixture_bytes: Callable[[str], bytes]
) -> None:
    at = app()
    at.run()
    at.file_uploader[0].upload(
        "one_numeric_column.csv", fixture_bytes("one_numeric_column.csv"), "text/csv"
    ).run()
    at.button(key="w.load").click().run()
    goto(at, "5_Visualise")
    at.radio(key="w.c.type").set_value("Correlation heatmap").run()
    assert [element.value for element in at.warning] == [
        "A correlation heatmap needs at least 2 numeric columns."
    ]
    at.radio(key="w.c.type").set_value("Line").run()
    assert [element.value for element in at.info] == ["This dataset has no datetime column."]
    assert len(at.get("vega_lite_chart")) == 0 and not at.exception
