"""AppTest helpers: a fresh cache per test, a new app, a loaded sample, page switching."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "src" / "data_explorer" / "app" / "streamlit_app.py"
TIMEOUT = 30


@pytest.fixture(autouse=True)
def _fresh_cache() -> Iterator[None]:
    st.cache_data.clear()
    yield
    st.cache_data.clear()


@pytest.fixture
def app() -> Callable[[], AppTest]:
    def make() -> AppTest:
        return AppTest.from_file(str(APP), default_timeout=TIMEOUT)

    return make


@pytest.fixture
def loaded(app: Callable[[], AppTest]) -> Callable[..., AppTest]:
    def load(sample: str = "retail_orders") -> AppTest:
        at = app()
        at.run()
        at.radio(key="w.source").set_value("Use a sample dataset").run()
        at.selectbox(key="w.sample").set_value(sample).run()
        at.button(key="w.load").click().run()
        assert not at.exception, at.exception
        return at

    return load


@pytest.fixture
def goto() -> Callable[[AppTest, str], AppTest]:
    def switch(at: AppTest, page: str) -> AppTest:
        at.switch_page(f"pages/{page}.py").run()
        assert not at.exception, at.exception
        return at

    return switch
