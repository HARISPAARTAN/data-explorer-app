"""Visualise page: every chart type renders, controls are remembered, errors and gaps are explained."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from data_explorer.app import ui
from data_explorer.core import charts
from data_explorer.core.filters import parse_filter

CHARTS = ["Histogram", "Bar", "Line", "Scatter", "Correlation heatmap"]


def chart_spec(at: AppTest) -> dict[str, Any]:
    spec: dict[str, Any] = json.loads(at.get("vega_lite_chart")[0].proto.spec)
    return spec


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
    at.selectbox(key="w.c.category").set_value("payment").run()
    assert at.main.caption[-1].value == "Sum of revenue_eur per payment."
    goto(at, "2_Overview")
    goto(at, "5_Visualise")
    assert at.radio(key="w.c.type").value == "Bar" and at.selectbox(key="w.c.category").value == "payment"
    assert at.session_state["de.chart"]["category"] == "payment"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_histogram_uses_the_theme_palette(
    loaded: Callable[..., AppTest],
    goto: Callable[[AppTest, str], AppTest],
    monkeypatch: pytest.MonkeyPatch,
    theme: str,
) -> None:
    monkeypatch.setattr(ui, "chart_theme", lambda: theme)
    at = goto(loaded("retail_orders"), "5_Visualise")
    assert chart_spec(at)["mark"]["color"] == charts.PALETTE[theme][0]


def test_split_line_uses_the_light_palette(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ui, "chart_theme", lambda: "light")
    at = goto(loaded("retail_orders"), "5_Visualise")
    at.radio(key="w.c.type").set_value("Line").run()
    at.selectbox(key="w.c.split").set_value("payment").run()
    assert chart_spec(at)["encoding"]["color"]["scale"]["range"][0] == charts.PALETTE["light"][0]


def test_histogram_counts_only_the_filtered_rows(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = loaded("retail_orders")
    at.session_state["de.filter"] = parse_filter('`store` = "Milan"')
    goto(at, "5_Visualise")
    milan = int((at.session_state["de.df"]["store"] == "Milan").sum())
    assert milan >= 1_000
    assert f"{milan:,}" in at.main.caption[-1].value
    assert at.main.caption[-1].value.startswith("30 equal-width bins over ")
    at.toggle(key="w.c.filtered").set_value(False).run()
    assert "6,060 non-missing values" in at.main.caption[-1].value


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
