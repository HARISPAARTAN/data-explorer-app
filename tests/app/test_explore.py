"""Explore page: conditions through widgets and as text, errors, Remove, Clear, columns and sort."""

from __future__ import annotations

from collections.abc import Callable

import numpy as np
from streamlit.testing.v1 import AppTest

from data_explorer.core.filters import Condition, FilterSpec, Op, SortKey, apply_filter, parse_filter
from data_explorer.core.io import load_sample


def match_caption(at: AppTest) -> str:
    return next(caption.value for caption in at.main.caption if "rows match" in caption.value)


def test_in_condition_through_the_widgets(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = goto(loaded("retail_orders"), "4_Explore")
    assert "No conditions: all rows are shown." in [caption.value for caption in at.main.caption]
    assert match_caption(at) == "6,060 of 6,060 rows match (100.0 %)"
    at.selectbox(key="w.f.column").set_value("store").run()
    at.selectbox(key="w.f.op").set_value(Op.IN).run()
    at.multiselect(key="w.f.values").set_value(["Milan", "Como"]).run()
    at.button(key="w.f.add").click().run()
    spec = at.session_state["de.filter"]
    assert spec == FilterSpec("all", (Condition("store", Op.IN, ("Milan", "Como")),))
    expected = len(apply_filter(load_sample("retail_orders")[0], spec))
    assert match_caption(at) == f"{expected:,} of 6,060 rows match ({expected / 6060 * 100:.1f} %)"
    assert at.code[0].value == '`store` IN ("Milan", "Como")'
    assert at.text_area(key="w.f.text_form").value == '`store` IN ("Milan", "Como")'


def test_numeric_between_reads_integers(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = goto(loaded("retail_orders"), "4_Explore")
    at.selectbox(key="w.f.column").set_value("units").run()
    at.selectbox(key="w.f.op").set_value(Op.BETWEEN).run()
    at.number_input(key="w.f.value").set_value(2).run()
    at.number_input(key="w.f.value2").set_value(10).run()
    at.button(key="w.f.add").click().run()
    assert at.session_state["de.filter"].conditions == (Condition("units", Op.BETWEEN, (2, 10)),)
    assert at.code[0].value == "`units` BETWEEN 2 AND 10"


def test_text_form_mode_remove_and_clear(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = goto(loaded("retail_orders"), "4_Explore")
    text = '`units` BETWEEN 2 AND 10 AND `payment` = "Card"'
    at.text_area(key="w.f.text_form").set_value(text).run()
    at.button(key="w.f.apply_text").click().run()
    assert at.session_state["de.filter"] == parse_filter(text)
    assert [element.value for element in at.code] == ["`units` BETWEEN 2 AND 10", '`payment` = "Card"']
    at.radio(key="w.f.mode").set_value("any condition").run()
    assert at.session_state["de.filter"].mode == "any"
    assert at.text_area(key="w.f.text_form").value == '`units` BETWEEN 2 AND 10 OR `payment` = "Card"'
    at.button(key="w.f.remove.0").click().run()
    assert at.session_state["de.filter"].conditions == (Condition("payment", Op.EQ, "Card"),)
    at.button(key="w.f.clear").click().run()
    assert at.session_state["de.filter"].conditions == ()
    assert "No conditions: all rows are shown." in [caption.value for caption in at.main.caption]


def test_syntax_error_is_shown_with_its_position(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = goto(loaded("retail_orders"), "4_Explore")
    at.text_area(key="w.f.text_form").set_value("`order_date` x").run()
    at.button(key="w.f.apply_text").click().run()
    assert [element.value for element in at.error] == [
        "Position 14: expected an operator such as =, IN or CONTAINS."
    ]
    assert at.session_state["de.filter"] == FilterSpec()
    at.text_area(key="w.f.text_form").set_value("`nope` = 1").run()
    at.button(key="w.f.apply_text").click().run()
    assert at.error[0].value == "Condition 1: column `nope` does not exist."


def test_columns_and_sort(loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]) -> None:
    at = goto(loaded("retail_orders"), "4_Explore")
    at.multiselect(key="w.v.columns").set_value(["store", "units"]).run()
    assert at.session_state["de.columns"] == ("store", "units")
    at.selectbox(key="w.v.sort.1.column").set_value("units").run()
    at.toggle(key="w.v.sort.1.desc").set_value(True).run()
    assert at.session_state["de.sort"] == (SortKey("units", True),)
    table = at.dataframe[0].value
    assert list(table.columns) == ["store", "units"]
    assert table["units"].iloc[0] == load_sample("retail_orders")[0]["units"].max()
    assert "Showing the first 1,000 rows; Download contains all of them." in [
        c.value for c in at.main.caption
    ]
    goto(at, "2_Overview")
    goto(at, "4_Explore")
    assert at.multiselect(key="w.v.columns").value == ["store", "units"]
    assert (
        at.selectbox(key="w.v.sort.1.column").value == "units"
        and at.toggle(key="w.v.sort.1.desc").value is True
    )


def test_switching_the_column_reseeds_the_number_inputs(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    df = load_sample("retail_orders")[0]
    at = goto(loaded("retail_orders"), "4_Explore")
    at.selectbox(key="w.f.column").set_value("units").run()
    at.selectbox(key="w.f.op").set_value(Op.BETWEEN).run()
    assert at.number_input(key="w.f.value").value == df["units"].min()
    assert at.number_input(key="w.f.value2").value == df["units"].max()
    at.number_input(key="w.f.value").set_value(7).run()
    at.selectbox(key="w.f.column").set_value("revenue_eur").run()
    assert at.number_input(key="w.f.value").value == df["revenue_eur"].min()
    assert at.number_input(key="w.f.value2").value == df["revenue_eur"].max()
    at.button(key="w.f.add").click().run()
    low, high = df["revenue_eur"].min(), df["revenue_eur"].max()
    assert at.session_state["de.filter"].conditions == (Condition("revenue_eur", Op.BETWEEN, (low, high)),)


def test_switching_the_operator_reseeds_the_number_inputs(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    df = load_sample("retail_orders")[0]
    at = goto(loaded("retail_orders"), "4_Explore")
    at.selectbox(key="w.f.column").set_value("units").run()
    at.selectbox(key="w.f.op").set_value(Op.BETWEEN).run()
    at.number_input(key="w.f.value").set_value(3).run()
    at.selectbox(key="w.f.op").set_value(Op.GT).run()
    assert at.number_input(key="w.f.value").value == df["units"].median()


def test_infinite_values_do_not_reach_the_number_inputs(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = loaded("retail_orders")
    df = at.session_state["de.df"].copy()
    df.loc[df.index[0], "revenue_eur"] = np.inf
    df.loc[df.index[1], "revenue_eur"] = -np.inf
    at.session_state["de.df"] = df
    finite = df["revenue_eur"][np.isfinite(df["revenue_eur"])]
    at = goto(at, "4_Explore")
    at.selectbox(key="w.f.column").set_value("revenue_eur").run()
    at.selectbox(key="w.f.op").set_value(Op.BETWEEN).run()
    assert not at.exception, at.exception
    assert at.number_input(key="w.f.value").value == finite.min()
    assert at.number_input(key="w.f.value2").value == finite.max()


def test_a_column_without_finite_values_starts_at_zero(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = loaded("retail_orders")
    df = at.session_state["de.df"].copy()
    df["revenue_eur"] = np.inf
    at.session_state["de.df"] = df
    at = goto(at, "4_Explore")
    at.selectbox(key="w.f.column").set_value("revenue_eur").run()
    at.selectbox(key="w.f.op").set_value(Op.BETWEEN).run()
    assert not at.exception, at.exception
    assert (at.number_input(key="w.f.value").value, at.number_input(key="w.f.value2").value) == (0.0, 0.0)
    assert "This column has no finite values; the inputs start at 0." in [c.value for c in at.main.caption]


def test_ten_conditions_disable_the_add_button(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = goto(loaded("retail_orders"), "4_Explore")
    assert at.button(key="w.f.add").disabled is False
    text = " AND ".join(f"`units` > {n}" for n in range(10))
    at.text_area(key="w.f.text_form").set_value(text).run()
    at.button(key="w.f.apply_text").click().run()
    assert len(at.session_state["de.filter"].conditions) == 10
    assert at.button(key="w.f.add").disabled is True
    assert "A filter has at most 10 conditions." in [caption.value for caption in at.main.caption]


def test_categorical_equals_through_the_choice_widget(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    df = load_sample("retail_orders")[0]
    at = goto(loaded("retail_orders"), "4_Explore")
    at.selectbox(key="w.f.column").set_value("payment").run()
    at.selectbox(key="w.f.op").set_value(Op.EQ).run()
    choice = at.selectbox(key="w.f.choice").options[-1]
    at.selectbox(key="w.f.choice").set_value(choice).run()
    at.button(key="w.f.add").click().run()
    spec = at.session_state["de.filter"]
    assert spec == FilterSpec("all", (Condition("payment", Op.EQ, choice),))
    expected = len(apply_filter(df, spec))
    assert 0 < expected < len(df)
    assert match_caption(at) == f"{expected:,} of 6,060 rows match ({expected / 6060 * 100:.1f} %)"


def test_reversed_between_shows_the_error(
    loaded: Callable[..., AppTest], goto: Callable[[AppTest, str], AppTest]
) -> None:
    at = goto(loaded("retail_orders"), "4_Explore")
    at.selectbox(key="w.f.column").set_value("units").run()
    at.selectbox(key="w.f.op").set_value(Op.BETWEEN).run()
    at.number_input(key="w.f.value").set_value(10).run()
    at.number_input(key="w.f.value2").set_value(2).run()
    at.button(key="w.f.add").click().run()
    assert not at.exception, at.exception
    assert [element.value for element in at.error] == ["Condition 1: BETWEEN needs the smaller value first."]
    assert at.session_state["de.filter"] == FilterSpec()
