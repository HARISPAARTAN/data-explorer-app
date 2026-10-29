"""Every page after Upload shows a hint and stops when no dataset is loaded."""

from __future__ import annotations

from collections.abc import Callable

import pytest
from streamlit.testing.v1 import AppTest

from data_explorer.app.ui import NO_DATASET

PAGES = ["2_Overview", "3_Quality", "4_Explore", "5_Visualise", "6_Download"]


@pytest.mark.parametrize("page", PAGES)
def test_page_without_a_dataset(
    app: Callable[[], AppTest], goto: Callable[[AppTest, str], AppTest], page: str
) -> None:
    at = app()
    at.run()
    goto(at, page)
    assert [info.value for info in at.info] == [NO_DATASET]
    assert len(at.title) == 0 and not at.exception
