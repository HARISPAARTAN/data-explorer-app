"""core/charts.py: pre-aggregation, encodings, limits, themes and the kit palette."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pandas as pd
import pytest

from data_explorer.core import charts
from data_explorer.core.charts import (
    DIVERGING,
    PALETTE,
    SEQUENTIAL,
    ChartError,
    bar,
    bar_data,
    chart_caption,
    correlation_data,
    correlation_heatmap,
    histogram,
    histogram_data,
    line,
    line_data,
    missing_heatmap,
    scatter,
    scatter_data,
)
from data_explorer.core.quality import missing_matrix


def rows(chart: Any) -> list[dict[str, Any]]:
    spec = chart.to_dict()
    data = spec["data"]
    return data["values"] if "values" in data else spec["datasets"][data["name"]]


def mark_type(spec: dict[str, Any]) -> str:
    mark = spec["mark"]
    return mark["type"] if isinstance(mark, dict) else mark


@pytest.fixture
def categories() -> pd.DataFrame:
    labels = ["a"] * 6 + ["b"] * 5 + ["c"] * 4 + ["d"] * 3 + ["e"] * 2 + ["f", "g"] + [None] * 3
    return pd.DataFrame({"cat": pd.Series(labels, dtype="str"), "amount": range(len(labels))})


@pytest.fixture
def dated() -> pd.DataFrame:
    days = pd.Series(["2025-03-03", "2025-03-09", "2025-03-10", "2025-03-24", None])
    return pd.DataFrame(
        {
            "day": pd.to_datetime(days, format="%Y-%m-%d").astype("datetime64[us]"),
            "amount": [1.0, 2.0, None, 4.0, 5.0],
            "shop": pd.Series(["x", "y", "x", "x", "y"], dtype="str"),
        }
    )


def test_palette_matches_the_vendored_kit(tool: Callable[[str], ModuleType], repo_root: Path) -> None:
    sync_kit = tool("tools/sync_kit.py")
    expected = sync_kit.parse_palette(
        (repo_root / "web" / "kit" / "echarts-theme.js").read_text(encoding="utf-8")
    )
    assert {"PALETTE": PALETTE, "SEQUENTIAL": SEQUENTIAL, "DIVERGING": DIVERGING} == expected
    assert sync_kit.read_block(Path(charts.__file__).read_text(encoding="utf-8")) == expected
    assert len(charts.DIVERGING_DOMAIN) == 7 and len(charts.SEQUENTIAL_DOMAIN) == 6


def test_histogram_data() -> None:
    df = pd.DataFrame({"v": [0.0, 1, 2, 3, 4, 5, 6, 7, 8, 9, None]})
    data = histogram_data(df, "v", bins=5)
    assert data["rows"].tolist() == [2, 2, 2, 2, 2]
    assert data["bin_start"].tolist() == pytest.approx([0.0, 1.8, 3.6, 5.4, 7.2])
    assert data["bin_end"].iloc[-1] == 9.0


def test_histogram_chart() -> None:
    df = pd.DataFrame({"v": [0.0, 1, 2, 3, 4, 5, 6, 7, 8, 9, None]})
    chart = histogram(df, "v", bins=5)
    spec = chart.to_dict()
    assert spec["mark"] == {"type": "bar", "color": PALETTE["dark"][0]}
    assert spec["encoding"]["x"] == {
        "field": "bin_start",
        "type": "quantitative",
        "bin": "binned",
        "title": "v",
    }
    assert spec["encoding"]["x2"] == {"field": "bin_end"}
    assert spec["encoding"]["y"]["title"] == "Rows" and spec["height"] == 360
    assert chart_caption(chart) == "5 equal-width bins over 10 non-missing values of v."
    assert spec["description"] == chart_caption(chart) and len(rows(chart)) == 5
    assert histogram(df, "v", 5, theme="light").to_dict()["mark"]["color"] == PALETTE["light"][0]


def test_histogram_errors() -> None:
    df = pd.DataFrame({"v": [1.0, None], "t": ["a", "b"], "b": [True, False]})
    with pytest.raises(ChartError, match="fewer than 2 values"):
        histogram(df, "v")
    with pytest.raises(ChartError, match="`t` is not numeric"):
        histogram(df, "t")
    with pytest.raises(ChartError, match="`b` is not numeric"):
        histogram(df, "b")
    with pytest.raises(ChartError, match="does not exist"):
        histogram(df, "zz")
    with pytest.raises(ChartError, match="between 5 and 100"):
        histogram(pd.DataFrame({"v": range(10)}), "v", bins=4)


def test_bar_data_counts_measures_and_other(categories: pd.DataFrame) -> None:
    counts = bar_data(categories, "cat", top_n=5)
    assert counts["category"].tolist() == ["a", "b", "c", "(missing)", "d", "Other (3 categories)"]
    assert counts["value"].tolist() == [6, 5, 4, 3, 3, 4]
    sums = bar_data(categories, "cat", "amount", "sum", top_n=5)
    assert sums["category"].tolist() == ["(missing)", "c", "d", "b", "e", "Other (3 categories)"]
    assert sums["value"].tolist() == [69, 50, 48, 40, 37, 56]
    means = bar_data(categories, "cat", "amount", "mean", top_n=5)
    assert means["value"].tolist() == [23, 21, 20, 18.5, 16, 7.0]
    assert bar_data(categories, "cat", top_n=50)["category"].tolist()[-1] == "g"
    flags = pd.DataFrame({"f": pd.array([True, False, None, True], dtype="boolean")})
    assert bar_data(flags, "f")["category"].tolist() == ["True", "(missing)", "False"]


def test_bar_chart_and_errors(categories: pd.DataFrame) -> None:
    chart = bar(categories, "cat", "amount", "median", top_n=5)
    spec = chart.to_dict()
    assert spec["encoding"]["y"]["sort"] == "-x" and spec["encoding"]["x"]["title"] == "median of amount"
    assert chart_caption(chart) == "Median of amount per cat; the top 5 categories, the other 3 as one bar."
    assert chart_caption(bar(categories, "cat", top_n=50)) == "Rows per cat."
    with pytest.raises(ChartError, match="`amount` is numeric; bars need"):
        bar(categories, "amount")
    with pytest.raises(ChartError, match="Choose a measure column"):
        bar(categories, "cat", agg="sum")
    with pytest.raises(ChartError, match="needs the aggregation sum, mean or median"):
        bar(categories, "cat", "amount", "count")
    with pytest.raises(ChartError, match="between 5 and 50"):
        bar(categories, "cat", top_n=4)
    many = pd.DataFrame({"t": pd.Series([f"id {i}" for i in range(1_001)], dtype="str")})
    with pytest.raises(ChartError, match="more than 1,000 distinct values"):
        bar(many, "t")


def test_line_data(dated: pd.DataFrame) -> None:
    weekly = line_data(dated, "day")
    assert weekly["period"].dt.strftime("%Y-%m-%d").tolist() == [
        "2025-03-03",
        "2025-03-10",
        "2025-03-17",
        "2025-03-24",
    ]
    assert weekly["value"].tolist() == [2, 1, 0, 1] and set(weekly["series"]) == {"All rows"}
    sums = line_data(dated, "day", "amount", "sum")
    assert [None if pd.isna(v) else v for v in sums["value"]] == [3.0, None, None, 4.0]
    split = line_data(dated, "day", split="shop")
    assert split["series"].tolist() == ["x"] * 4 + ["y"] * 4
    assert split["value"].tolist() == [1, 1, 0, 1, 1, 0, 0, 0]
    assert line_data(dated, "day", freq="M")["value"].tolist() == [4]
    assert len(line_data(dated, "day", freq="D")) == 22


def test_line_chart(dated: pd.DataFrame) -> None:
    chart = line(dated, "day", "amount", "sum", split="shop")
    spec = chart.to_dict()
    assert spec["mark"] == {"type": "line", "point": True, "invalid": None}
    assert spec["encoding"]["color"]["scale"]["range"] == list(PALETTE["dark"])
    assert chart_caption(chart) == (
        "Weekly sum of amount by shop; weeks run Monday to Sunday; periods without values are gaps."
    )
    assert rows(chart)[0]["period"] == "2025-03-03T00:00:00"
    single = line(dated, "day")
    assert chart_caption(single) == "Weekly count of rows; weeks run Monday to Sunday."
    assert (
        "color" not in single.to_dict()["encoding"]
        and single.to_dict()["mark"]["color"] == PALETTE["dark"][0]
    )
    long = pd.DataFrame(
        {"day": pd.Series(pd.date_range("2025-01-01", periods=61, freq="D")).astype("datetime64[us]")}
    )
    assert line(long, "day", freq="D").to_dict()["mark"]["point"] is False


def test_line_errors(dated: pd.DataFrame) -> None:
    with pytest.raises(ChartError, match="`amount` is not a date column"):
        line(dated, "amount")
    with pytest.raises(ChartError, match="The period must be"):
        line(dated, "day", freq="Q")  # type: ignore[arg-type]
    nine = dated.assign(shop=pd.Series(list("abcde"), dtype="str"))
    nine = pd.concat([nine, nine.assign(shop=pd.Series(list("fghij"), dtype="str"))], ignore_index=True)
    with pytest.raises(ChartError, match="at most 8 series"):
        line(nine, "day", split="shop")
    days = pd.DataFrame(
        {"day": pd.Series(pd.date_range("2000-01-01", periods=5_001, freq="D")).astype("datetime64[us]")}
    )
    with pytest.raises(ChartError, match="longer period"):
        line(days, "day", freq="D")


def test_scatter_sampling_and_missing() -> None:
    rng = np.random.default_rng(1)
    df = pd.DataFrame(
        {"x": rng.normal(size=6_000), "y": rng.normal(size=6_000), "g": rng.choice(["a", "b"], size=6_000)}
    )
    df.loc[:9, "y"] = np.nan
    data, total = scatter_data(df, "x", "y", "g")
    assert total == 5_990 and len(data) == 5_000 and list(data.columns) == ["x", "y", "group"]
    again, _ = scatter_data(df, "x", "y", "g")
    pd.testing.assert_frame_equal(data, again)
    other, _ = scatter_data(df, "x", "y", seed=7)
    assert not other["x"].equals(data["x"])
    chart = scatter(df, "x", "y", "g")
    assert (
        chart_caption(chart) == "Sample of 5,000 of 5,990 points; 10 rows with a missing x or y are left out."
    )
    spec = chart.to_dict()
    assert spec["mark"] == {"type": "circle", "size": 30, "opacity": 0.6}
    assert spec["encoding"]["x"]["scale"] == {"zero": False} and spec["encoding"]["y"]["scale"] == {
        "zero": False
    }
    assert spec["encoding"]["color"]["scale"]["range"] == list(PALETTE["dark"])
    small = scatter(df.head(100), "x", "y", theme="light")
    assert chart_caption(small) == "90 points; 10 rows with a missing x or y are left out."
    assert small.to_dict()["mark"]["color"] == PALETTE["light"][0]


def test_scatter_errors() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0, 3.0], "y": [1.0, None, None], "g": list("abc"), "n": range(3)})
    with pytest.raises(ChartError, match="Fewer than 2 rows"):
        scatter(df, "x", "y")
    with pytest.raises(ChartError, match="`g` is not numeric"):
        scatter(df, "x", "g")
    nine = pd.DataFrame({"x": range(9), "y": range(9), "g": list("abcdefghi")})
    with pytest.raises(ChartError, match="at most 8 groups"):
        scatter(nine, "x", "y", "g")
    with pytest.raises(ChartError, match="between 1 and 5,000"):
        scatter(nine, "x", "y", max_points=5_001)


def correlated() -> pd.DataFrame:
    x = np.arange(20, dtype="float64")
    sparse = np.where(x < 5, x, np.nan)
    return pd.DataFrame(
        {"a": x, "b": 2 * x + 1, "c": -(x**3), "flag": x > 5, "t": ["s"] * 20, "sparse": sparse}
    )


def test_correlation_data() -> None:
    df = correlated()
    data = correlation_data(df)
    assert list(dict.fromkeys(data["a"])) == ["a", "b", "c", "sparse"] and len(data) == 16
    r = {(row.a, row.b): row.r for row in data.itertuples()}
    assert r[("a", "b")] == pytest.approx(1.0)
    assert r[("a", "c")] == pytest.approx(np.corrcoef(df["a"], df["c"])[0, 1])
    assert np.isnan(r[("a", "sparse")])
    ranks = {(row.a, row.b): row.r for row in correlation_data(df, "spearman").itertuples()}
    assert ranks[("a", "c")] == pytest.approx(-1.0)


def test_correlation_chart() -> None:
    chart = correlation_heatmap(correlated())
    spec = chart.to_dict()
    assert [mark_type(layer) for layer in spec["layer"]] == ["rect", "text"]
    scale = spec["layer"][0]["encoding"]["color"]["scale"]
    assert scale["range"] == list(DIVERGING["dark"]) and len(scale["domain"]) == 7
    assert (scale["domain"][0], scale["domain"][3], scale["domain"][-1]) == (-1, 0, 1)
    text = spec["layer"][1]
    assert text["encoding"]["text"] == {"field": "r", "type": "quantitative", "format": ".2f"}
    assert text["transform"] == [{"filter": "isValid(datum.r)"}]
    strong, weak = charts.TEXT_COLOURS["dark"]
    assert text["encoding"]["color"]["value"] == weak and strong in json.dumps(
        text["encoding"]["color"]["condition"]
    )
    assert "0.35" in json.dumps(text["encoding"]["color"]["condition"])
    assert chart_caption(chart) == (
        "Pearson correlation of 4 numeric columns; pairs with fewer than 10 rows with both values are blank."
    )
    wide = pd.DataFrame({f"c{i}": np.random.default_rng(i).normal(size=30) for i in range(13)})
    assert mark_type(correlation_heatmap(wide).to_dict()) == "rect"
    wider = pd.DataFrame({f"c{i}": np.random.default_rng(i).normal(size=30) for i in range(25)})
    assert correlation_data(wider)["a"].nunique() == 20
    assert "the first 20 of 25 numeric columns" in chart_caption(correlation_heatmap(wider, "spearman"))
    with pytest.raises(ChartError, match="at least 2 numeric columns"):
        correlation_heatmap(correlated()[["a", "t"]])
    with pytest.raises(ChartError, match="pearson or spearman"):
        correlation_heatmap(correlated(), "kendall")  # type: ignore[arg-type]


def test_missing_heatmap() -> None:
    df = pd.DataFrame({"a": [None] * 3 + [1] * 7, "b": [1] * 8 + [None, None]})
    chart = missing_heatmap(missing_matrix(df, bins=4))
    spec = chart.to_dict()
    assert len(rows(chart)) == 8
    assert spec["encoding"]["x"]["sort"] == ["a", "b"] and spec["encoding"]["x"]["axis"] == {
        "labelAngle": -45
    }
    assert spec["encoding"]["y"] == {"field": "bin", "type": "ordinal", "title": "Row block"}
    scale = spec["encoding"]["color"]["scale"]
    assert scale["range"] == list(SEQUENTIAL["dark"]) and scale["domain"] == [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    assert chart_caption(chart) == (
        "Rows are grouped into up to 100 consecutive blocks; colour shows the share missing per block."
    )
    with pytest.raises(ChartError, match="no rows"):
        missing_heatmap(missing_matrix(df.iloc[0:0]))


def test_inline_limit() -> None:
    with pytest.raises(ChartError, match="the limit is 5,000"):
        charts._records(pd.DataFrame({"v": range(5_001)}))


def test_every_chart_on_a_sample_validates(samples: dict[str, tuple[pd.DataFrame, Any]]) -> None:
    retail = samples["retail_orders"][0]
    built = [
        histogram(retail, "units"),
        bar(retail, "store"),
        line(retail, "order_date", "revenue_eur", "sum"),
        scatter(retail, "units", "revenue_eur", "store"),
        correlation_heatmap(retail),
        missing_heatmap(missing_matrix(retail)),
    ]
    for chart in built:
        spec = chart.to_dict()
        assert spec["height"] == 360 and len(rows(chart)) <= 5_000
        json.dumps(spec, allow_nan=False)
