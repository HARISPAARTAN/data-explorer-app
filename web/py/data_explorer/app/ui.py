"""The frame every page shares: page config, sidebar, dataset guard, captions, errors and logging."""

from __future__ import annotations

import logging
import os
import re
import sys

import pandas as pd
import streamlit as st
from streamlit.delta_generator import DeltaGenerator

from data_explorer.app import state
from data_explorer.core.charts import Theme
from data_explorer.core.io import Limits, LoadReport

APP_NAME = "Meridian Data Explorer"
REPO_URL = "https://github.com/HARISPAARTAN/data-explorer-app"
DEMO_NOTE = "Demo with invented data for a fictional company."
FOOTER = "Rebuilt from memory as a demo. The original client's name and data are not used."
NO_DATASET = "No dataset loaded yet. Load a file or a sample on the Upload page."
PAGES = (
    ("streamlit_app.py", "Upload"),
    ("pages/2_Overview.py", "Overview"),
    ("pages/3_Quality.py", "Quality"),
    ("pages/4_Explore.py", "Explore"),
    ("pages/5_Visualise.py", "Visualise"),
    ("pages/6_Download.py", "Download"),
)
IN_BROWSER = sys.platform == "emscripten"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
HANDLER_NAME = "data_explorer.stdout"
MiB = 1024 * 1024
DELIMITER_WORDS = {",": "comma", ";": "semicolon", "\t": "tab", "|": "pipe"}
DECIMAL_WORDS = {".": "point", ",": "comma"}

logger = logging.getLogger("data_explorer")


def configure_logging() -> None:
    """One stdout handler for the ``data_explorer`` logger, level from DATA_EXPLORER_LOG_LEVEL."""
    if any(handler.get_name() == HANDLER_NAME for handler in logger.handlers):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.set_name(HANDLER_NAME)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    logger.addHandler(handler)
    logger.propagate = False
    raw = os.environ.get("DATA_EXPLORER_LOG_LEVEL", "").strip().upper() or "INFO"
    logger.setLevel(raw if raw in LOG_LEVELS else "INFO")
    if raw not in LOG_LEVELS:
        logger.warning("DATA_EXPLORER_LOG_LEVEL=%s is not a log level; using INFO", raw)


def pct(value: float) -> str:
    return f"{value:.1f} %"


def stat_text(value: object) -> str:
    """A statistic for a table cell: thousands separators, two decimals, empty for missing."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return f"{value:,}"
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return f"{value:,.0f}"
        return f"{value:,.2f}" if abs(value) >= 1 else f"{value:.4g}"
    return str(value)


def inline_code(text: str) -> str:
    """Markdown inline code that may itself contain backticks (column names in filters do)."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    if not longest:
        return f"`{text}`"
    fence = "`" * (longest + 1)
    return f"{fence} {text} {fence}"


def dataset_caption() -> str:
    if not state.has_dataset():
        return "No dataset loaded"
    report: LoadReport = st.session_state[state.REPORT]
    return f"{report.file_name} · {report.n_rows:,} rows × {report.n_cols:,} columns"


def runtime_caption() -> str:
    python = f"{sys.version_info.major}.{sys.version_info.minor}"
    where = "browser (Pyodide)" if IN_BROWSER else "server"
    return f"Runtime: {where} · Python {python} · Streamlit {st.__version__} · pandas {pd.__version__}"


def limits_caption(limits: Limits) -> str:
    size = f"{limits.max_bytes / MiB:g} MB"
    where = "in the browser demo" if IN_BROWSER else "on this server"
    return f"Up to {size}, {limits.max_rows:,} rows and {limits.max_cols:,} columns {where}"


def reading_caption(report: LoadReport) -> str:
    parts = []
    if report.file_type == "csv":
        parts.append(f"Encoding {report.encoding}")
        parts.append(f"delimiter {DELIMITER_WORDS.get(report.delimiter or '', 'unknown')}")
        parts.append(f"decimal {DECIMAL_WORDS.get(report.decimal or '', 'unknown')}")
    else:
        parts.append(f"Workbook, sheet {report.sheet} of {len(report.sheets)}")
    parts.append(f"header row {report.header_row + 1}")
    return " · ".join(parts)


def page_setup(title: str) -> DeltaGenerator:
    """Page config, logging, state defaults and the sidebar; returns the slot of the dataset caption."""
    st.set_page_config(page_title=f"{title} · {APP_NAME}", layout="wide")
    configure_logging()
    state.init()
    with st.sidebar:
        st.markdown(f"**{APP_NAME}**")
        for path, label in PAGES:
            st.page_link(path, label=label)
        slot = st.empty()
        slot.caption(dataset_caption())
        st.caption(f"{DEMO_NOTE} [Source on GitHub]({REPO_URL})")
        st.caption(runtime_caption())
        st.caption(FOOTER)
    return slot


def require_dataset() -> tuple[pd.DataFrame, LoadReport, str]:
    """The current dataset; without one, the page shows a hint and stops."""
    if not state.has_dataset():
        st.info(NO_DATASET)
        st.page_link("streamlit_app.py", label="Go to Upload")
        st.stop()
    return state.dataset()


def unexpected(action: str) -> None:
    """Call inside ``except Exception``: log the traceback, show a short message."""
    logger.exception("unexpected error while %s", action)
    st.error(f"Something went wrong while {action}. The details are in the log.")


def chart_theme() -> Theme:
    """The theme the browser reports; dark (the configured base) until it is known."""
    try:
        kind = st.context.theme.type
    except Exception:  # the theme is unknown in tests and before the first round trip
        kind = None
    return "light" if kind == "light" else "dark"
