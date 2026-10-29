"""Pinned versions shared by the server environment and the browser demo.

The browser runs ``@stlite/browser`` with its default Pyodide; the server environment pins the
same Streamlit, pandas, Altair and openpyxl versions, so the tests describe the demo. Change these
together with ``pyproject.toml`` and ``web/index.html`` (see ``docs/handover.md``).
"""

STLITE = "1.12.0"
PYODIDE = "314.0.3"
PYODIDE_PYTHON = "3.14"
STREAMLIT = "1.65.0"
PANDAS = "3.0.2"
ALTAIR = "6.0.0"
OPENPYXL = "3.1.5"
