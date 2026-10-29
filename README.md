# Data Explorer App

[![CI](https://github.com/HARISPAARTAN/data-explorer-app/actions/workflows/ci.yml/badge.svg)](https://github.com/HARISPAARTAN/data-explorer-app/actions/workflows/ci.yml)
[![Pages](https://github.com/HARISPAARTAN/data-explorer-app/actions/workflows/pages.yml/badge.svg)](https://github.com/HARISPAARTAN/data-explorer-app/actions/workflows/pages.yml)
[![Release](https://img.shields.io/github/v/release/HARISPAARTAN/data-explorer-app?sort=semver)](https://github.com/HARISPAARTAN/data-explorer-app/releases)

Upload a CSV or Excel file and get statistics, data quality, filters, charts and downloads; runs in the browser with stlite or on a server with Docker.

Deutsch: [README.de.md](README.de.md)

## Status

Not released and not published yet. CI has not run yet. This section lists only checked facts: the result of the last CI run, the date and browser of the last smoke test of the live demo, the measured download size of a first visit and the latest release. It is filled in once CI and the smoke test of the live page have run.

### Known limitations

- The browser version logs two console messages per download button: stlite 1.12.0 lets Streamlit check each button's file address on a placeholder host that never resolves. Clicking the button still downloads the file. The smoke test allows exactly these two messages and fails on every other console error, so a pass means no unexpected console errors, not an empty console ([details](docs/handover.md#known-console-messages-in-the-browser)).
- Integer columns that hold years, such as 2024, show a thousands separator in the Overview table.
- The Min and Max of a datetime column in the Overview table show a `T00:00:00` suffix.
- A number input in Explore that is cleared shows 0.0.
- The Pages deployment is not gated on CI: a push to `main` goes live even when the CI jobs of that commit fail ([details](docs/handover.md#pages-deployment)).
- In the dark theme the primary button is white text on amber and measures about 2.0:1 at rest; the repository makes no claim of WCAG compliance for it. In the light theme, white on the light primary measures 5.02:1 (`tools/checks/contrast.mjs`).

## Client brief

> We are a small analytics team in Milan. Colleagues from other departments keep sending us CSV and Excel files with the same question: what is in here, and is it usable? We want a web app where anyone on the team can upload a CSV or Excel file and immediately see summary statistics, missing values and duplicates, filter the rows, draw a few standard charts and download the filtered data together with a short profile of the file. Users should not have to install anything. Exports from Italian and English Excel settings must both work (semicolons, decimal commas). Python on our side, so we can extend it later. Contact: data-team@meridian.example.

Rebuilt from memory as a demo. The original client's name and data are not used. Meridian Analytics Collective is a fictional company; roles, scope and acceptance criteria are in [docs/brief.md](docs/brief.md).

## Live demo

[harispaartan.github.io/data-explorer-app](https://harispaartan.github.io/data-explorer-app/)

![The Visualise page of the live demo with a weekly line chart of the retail sample](docs/screenshots/visualise-1440.png)

The demo runs the app's Python code in your browser with stlite and Pyodide. It needs WebAssembly and module workers, which current versions of Chrome, Edge, Firefox and Safari have; other browsers see screenshots and the commands to run the app locally. The demo page loads stlite and Pyodide from cdn.jsdelivr.net and openpyxl from PyPI; your files stay in the browser.

| Overview | Quality | Explore |
|---|---|---|
| ![Overview page with the metrics and the column statistics of the retail sample](docs/screenshots/overview-1440.png) | ![Quality page with the missing-value heatmap and the duplicate rows](docs/screenshots/quality-1440.png) | ![Explore page with the filtered rows](docs/screenshots/explore-1440.png) |

| Upload | Download |
|---|---|
| ![Upload page with the retail sample loaded](docs/screenshots/upload-1440.png) | ![Download page with the CSV formats and the profile downloads](docs/screenshots/download-1440.png) |

## What it does

- **Upload**: open a CSV, TSV, TXT or XLSX file, or one of three samples. Encoding, delimiter, decimal separator, sheet and header row are detected and can be set by hand for an upload.
- **Overview**: rows, columns, missing cells, duplicate rows and memory; one line of statistics per column; the first 100 rows.
- **Quality**: missing values per column and as a heatmap, duplicate rows (also over chosen columns), constant columns, and outliers by the IQR rule with an adjustable factor.
- **Explore**: filters built with widgets or written as text, which stay in step, plus a column choice and sorting.
- **Visualise**: histogram, bar, line and scatter charts and a correlation heatmap, over all rows or the Explore view.
- **Download**: the current view as CSV for Excel with English settings or with Italian or German settings, and a profile of the file as JSON or Markdown.

## How it works

![Two runtimes, one code base: the server and the browser run the same app/ pages, which call the pure core/ package](docs/architecture.svg)

All computation sits in `core/`, pure functions over pandas frames that never import Streamlit; the six Streamlit pages in `app/` arrange widgets and call it. The same files run in two places: on a server (the Docker image or `uv run data-explorer run`, CPython 3.12) and in the browser (stlite 1.12.0 with Streamlit 1.65.0 on Pyodide 314.0.3, Python 3.14). The server pins the versions the browser runs, so the tests describe the demo. Details in [docs/architecture.md](docs/architecture.md).

## Data model

One pandas DataFrame per session plus frozen result objects; nothing is stored. Three invented samples ship with the package, each with defects planted in exact numbers:

| Sample | File | Rows × columns | Planted defects |
|---|---|---|---|
| Retail orders | `retail_orders.csv`: UTF-8 with BOM, semicolons, decimal commas | 6,060 × 11 | 60 duplicate rows, 180 missing discounts, 15 outliers, a constant column |
| Sensor readings | `sensor_readings.csv`: cp1252, commas, ISO timestamps | 8,640 × 9 | a 48-hour sensor outage, 30 further missing humidity values, 12 sentinel values, a constant column |
| Client survey | `client_survey.xlsx`: two sheets, header on row 4 | 1,224 × 11 | 24 duplicate rows, 37 missing ratings, 840 empty comments, 10 long response times, a constant column |

Columns, kinds, the filter grammar and the download formats are in [docs/data-model.md](docs/data-model.md).

## Getting started

```bash
git clone https://github.com/HARISPAARTAN/data-explorer-app.git
cd data-explorer-app
uv sync --locked
uv run data-explorer run        # serves the app on http://127.0.0.1:8501
uv run pytest
```

With Docker:

```bash
docker build -t data-explorer .
docker run --rm -p 8501:8501 data-explorer
```

`uv run data-explorer run` binds to 127.0.0.1 by default; `--host` changes that. You need [uv](https://docs.astral.sh/uv/) and Git, and Docker only for the image. [docs/handover.md](docs/handover.md) covers the environment variables, the logs, adding a sample or a chart type, and the update checklist for the pinned versions.

## Project layout

```text
src/data_explorer/   core/ (pure computation), app/ (Streamlit pages), cli.py, samples/
tests/               core/, app/, tools/, golden/
fixtures/            small files for the reading tests
tools/               make_data.py, sync_kit.py, sync_web.py, checks/
web/                 index.html (the stlite page), kit/, py/ (synced copy of the package), assets/
docs/                brief, data model, architecture, adr/, handover, screenshots/
.github/             ci.yml, pages.yml, dependabot.yml
```

## Decisions

- [ADR 0001: stlite for the live demo](docs/adr/0001-stlite-for-the-live-demo.md)
- [ADR 0002: Pure core, thin Streamlit shell](docs/adr/0002-pure-core-thin-streamlit-shell.md)
- [ADR 0003: Flat filter grammar](docs/adr/0003-flat-filter-grammar.md)
- [ADR 0004: Browser and server version parity](docs/adr/0004-browser-server-version-parity.md)
- [ADR 0005: Text-only downloads](docs/adr/0005-text-only-downloads.md)

## Compared with the original delivery

This rebuild adds:

- a written brief with acceptance criteria, and a documented data model;
- a pure core with unit and property tests, and AppTest tests for every page;
- a browser demo that runs the same code, with a smoke test in CI and after every deployment;
- a Docker image pinned by digest, with a health check and a non-root user;
- handover notes with an update checklist for the pinned versions;
- CI on Ubuntu and Windows with Python 3.11, 3.12 and 3.13, and the core on Python 3.14; it installs with `uv sync --locked`, pins setup-uv by commit and runs the smoke test with Playwright 1.64.1.

## Licence and data note

MIT, see [LICENSE](LICENSE). Every dataset in this repository is invented. The app uses Streamlit and stlite (Apache-2.0), Pyodide (MPL-2.0), pandas and Altair (BSD-3-Clause) and openpyxl (MIT); the fonts in `web/kit/fonts/` are under the SIL Open Font License.

Rebuilt from memory as a demo. The original client's name and data are not used.
