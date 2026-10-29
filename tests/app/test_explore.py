"""Explore page: conditions through widgets and as text, errors, Remove, Clear, columns and sort."""

from __future__ import annotations

from collections.abc import Callable

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
