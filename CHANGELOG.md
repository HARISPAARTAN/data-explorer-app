# Changelog

All notable changes to this project are listed here.

## Unreleased

- Streamlit app with six pages: Upload, Overview, Quality, Explore, Visualise and Download.
- Pure `core/` package: reading CSV and Excel files with detection of encoding, delimiter, decimal separator, sheet and header row; column profiles; missing values, duplicates, constant columns and IQR outliers; a flat filter grammar whose text form reads back to the same filter; Altair charts; CSV, JSON and Markdown downloads.
- Three invented sample datasets with planted defects, generated with a fixed seed, and the test fixtures.
- Browser demo on GitHub Pages with stlite 1.12.0 and Pyodide 314.0.3, loaded from cdn.jsdelivr.net at those versions, with a fallback card for browsers without WebAssembly or module workers.
- Docker image on Python 3.12, pinned by digest, running as a non-root user with a health check.
- `data-explorer` command with `run` (binds to 127.0.0.1 by default), `samples` and `--version`.
- Tests: pytest and hypothesis for the core, AppTest for every page, repository tests, and a Playwright 1.64.1 smoke test of the browser demo (no unexpected console errors; two known download-button messages are allowed); CI on Ubuntu and Windows with Python 3.11 to 3.13 and the core on Python 3.14, installing with `uv sync --locked` and using setup-uv pinned by commit.
- Docs: client brief, data model, architecture, five ADRs and handover notes.

### Known issues

- The browser version logs two console messages per download button (stlite 1.12.0 checks the file address on a placeholder host that never resolves); clicking the button still downloads the file.
- Integer columns that hold years show a thousands separator in the Overview table.
- The Min and Max of a datetime column in the Overview table show a `T00:00:00` suffix.
- A number input in Explore that is cleared shows 0.0.
- The Pages deployment is not gated on CI.
- In the dark theme the primary button (white on amber) measures about 2.0:1 at rest, with no claim of WCAG compliance; in the light theme it measures 5.02:1.
