# ADR 0004: Browser and server version parity

Status: accepted (2026-10-29)

## Context

The browser runs whatever `@stlite/browser@1.12.0` ships: its Streamlit 1.65.0 and Pyodide 314.0.3 (Python 3.14) with Pyodide's pandas 3.0.2 and Altair 6.0.0, plus openpyxl 3.1.5 from PyPI. The tests run on CPython with packages from PyPI. If the versions differed, a green test run would say little about the demo.

## Decision

The server environment pins what the browser runs: `streamlit==1.65.0`, `pandas==3.0.2`, `altair==6.0.0`, `openpyxl==3.1.5`. `src/data_explorer/_versions.py` records these and the browser runtime (stlite 1.12.0, Pyodide 314.0.3, Python 3.14); a test compares the installed versions, `pyproject.toml` and the two stlite URLs and the openpyxl pin in `web/index.html` with it. CI runs the core tests on Python 3.14 as well as on 3.11 to 3.13. Dependabot ignores the four pinned packages; they move only together with stlite, following the update checklist in [the handover notes](../handover.md#updating-the-pinned-versions). The Docker image uses Python 3.12, which is inside the tested range.

## Consequences

- Streamlit 1.66 and later wait until a stlite release ships them.
- A security fix in one of the four packages also waits for stlite, or is taken on the server alone as a recorded, temporary difference.
- `pyodideUrl` is not set, so the page always gets the Pyodide that stlite 1.12.0 was released with.

## Alternatives considered

- The latest versions on the server: the tests would no longer describe the demo.
- A different Pyodide through `pyodideUrl`: a combination stlite was not released with.
