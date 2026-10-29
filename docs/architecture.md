# Architecture

![Two runtimes, one code base: the server and the browser run the same app/ pages, which call the pure core/ package](architecture.svg)

## Layout

| Path | What it is |
|---|---|
| `src/data_explorer/core/` | Pure computation: `io` (reading files), `profile`, `quality`, `filters`, `charts`, `export`. Imports only the standard library, numpy, pandas, Altair and openpyxl, never Streamlit ([ADR 0002](adr/0002-pure-core-thin-streamlit-shell.md)). |
| `src/data_explorer/app/` | The Streamlit shell: `streamlit_app.py` (the Upload page), `pages/` (Overview, Quality, Explore, Visualise, Download), `state.py`, `cache.py`, `ui.py`. |
| `src/data_explorer/cli.py` | The `data-explorer` command: `run`, `samples`, `--version`. |
| `src/data_explorer/samples/` | The three sample datasets ([data model](data-model.md#samples)). |
| `src/data_explorer/_versions.py` | The versions the browser runs and the server pins ([ADR 0004](adr/0004-browser-server-version-parity.md)). |
| `web/` | The GitHub Pages site: `index.html` (the stlite page), `kit/` (the vendored portfolio-kit), `py/data_explorer/` (a synced copy of the package), `assets/` (the fallback screenshots). |
| `tools/` | `make_data.py` (samples and fixtures), `sync_kit.py`, `sync_web.py`, `checks/`. |
| `tests/` | `core/`, `app/` and `tools/` tests, `golden/` profiles. |

## Two runtimes

Server: the Docker image (CPython 3.12) or `uv run data-explorer run` starts Streamlit 1.65.0 with `.streamlit/config.toml`. Browser: `web/index.html` loads `@stlite/browser@1.12.0` from cdn.jsdelivr.net, which runs Streamlit 1.65.0 on Pyodide 314.0.3 (Python 3.14) in a web worker; micropip installs openpyxl 3.1.5 from PyPI. The page first checks for WebAssembly and module workers and imports stlite only when both exist; otherwise, or when the download fails, it shows a fallback card with screenshots and the commands to run the app locally ([ADR 0001](adr/0001-stlite-for-the-live-demo.md)).

The page mounts these 22 files into the browser's in-memory file system; the page scripts sit at the root next to the entrypoint, as Streamlit's multipage layout needs, and the package sits next to them so `import data_explorer.core` works:

| Browser path | Source under `web/` |
|---|---|
| `streamlit_app.py` | `py/data_explorer/app/streamlit_app.py` |
| `pages/2_Overview.py` | `py/data_explorer/app/pages/2_Overview.py` |
| `pages/3_Quality.py` | `py/data_explorer/app/pages/3_Quality.py` |
| `pages/4_Explore.py` | `py/data_explorer/app/pages/4_Explore.py` |
| `pages/5_Visualise.py` | `py/data_explorer/app/pages/5_Visualise.py` |
| `pages/6_Download.py` | `py/data_explorer/app/pages/6_Download.py` |
| `data_explorer/__init__.py` | `py/data_explorer/__init__.py` |
| `data_explorer/_versions.py` | `py/data_explorer/_versions.py` |
| `data_explorer/core/__init__.py` | `py/data_explorer/core/__init__.py` |
| `data_explorer/core/io.py` | `py/data_explorer/core/io.py` |
| `data_explorer/core/profile.py` | `py/data_explorer/core/profile.py` |
| `data_explorer/core/quality.py` | `py/data_explorer/core/quality.py` |
| `data_explorer/core/filters.py` | `py/data_explorer/core/filters.py` |
| `data_explorer/core/charts.py` | `py/data_explorer/core/charts.py` |
| `data_explorer/core/export.py` | `py/data_explorer/core/export.py` |
| `data_explorer/app/__init__.py` | `py/data_explorer/app/__init__.py` |
| `data_explorer/app/state.py` | `py/data_explorer/app/state.py` |
| `data_explorer/app/ui.py` | `py/data_explorer/app/ui.py` |
| `data_explorer/app/cache.py` | `py/data_explorer/app/cache.py` |
| `data_explorer/samples/retail_orders.csv` | `py/data_explorer/samples/retail_orders.csv` |
| `data_explorer/samples/sensor_readings.csv` | `py/data_explorer/samples/sensor_readings.csv` |
| `data_explorer/samples/client_survey.xlsx` | `py/data_explorer/samples/client_survey.xlsx` |

`tools/sync_web.py` copies `src/data_explorer/` without `cli.py`, `__main__.py` and caches into `web/py/data_explorer/`; `--check` fails CI on any difference, so the Pages workflow can upload `web/` alone. The browser has lower limits than the server, loses its data on reload and shares nothing between tabs; otherwise both runtimes run the same code.

One difference shows in the browser console. Streamlit 1.65 checks the media URL of every download button when the button renders, and stlite 1.12.0 answers with a placeholder host, `stlite.invalid`, which never resolves. The Download page therefore logs two known console errors per button render and the browser makes a harmless DNS lookup; the click download works ([handover notes](handover.md#known-console-messages-in-the-browser)). Besides the page's own origin, the page's outbound hosts are cdn.jsdelivr.net, pypi.org and files.pythonhosted.org, plus that `.invalid` probe.

The page also loads the portfolio kit from `web/kit/`: the fonts, the colour tokens, the theme boot (the hub's `hh-theme` choice, otherwise the system preference, dark by default) and the fixed banner "Demo with invented data for a fictional company" with the link to this repository. The theme colours passed to stlite are the kit tokens; `.streamlit/config.toml` carries the dark ones for the server. A CSS rule in `web/index.html` sets the height of Streamlit's main column to the frame below the banner, because Streamlit sizes it to `100dvh`, which would clip 40 px (the banner's height) of the page.

## Session state

| Key | Set by | Holds |
|---|---|---|
| `de.dataset_id` | Upload | 16 hex characters: SHA-256 of the file bytes and the reading options |
| `de.df`, `de.report`, `de.source` | Upload | the frame, its `LoadReport`, `upload` or `sample` |
| `de.filter`, `de.columns`, `de.sort` | Explore | the current view |
| `de.q_subset`, `de.q_k` | Quality | the duplicate subset and the IQR factor |
| `de.chart` | Visualise | the chart type and its controls |
| `de.csv_dialect`, `de.profile_scope` | Download | the download choices |

Loading a new dataset replaces the first four keys and resets the view, the Quality choices (empty subset, k = 1.5) and the chart (histogram); the download choices stay. Widget keys (`w.*`) belong to one page, because Streamlit drops the state of widgets a run does not draw: every value that must survive a page switch is copied into its `de.*` key by a callback, and the widgets start from those keys. On the Explore page the number, date and text inputs of a new condition are reseeded when its column or operator changes, and a cleared number input shows 0.0.

## Caching

`app/cache.py` wraps the expensive calls in `st.cache_data`, with no expiry and nothing on disk: `load` and `sample` keep 3 entries; `profile`, `quality`, `matrix` and `view` keep 16. Parameters whose names start with an underscore are not hashed, so a large frame is passed as `_df` together with its `dataset_id`; the view's canonical JSON ([data model](data-model.md#filter-json)) completes the key. On a server the cache is shared between sessions, but an entry is reachable only with identical file bytes. Charts are not cached: they are built from the cached view after aggregation in pandas.

## Errors and logging

Expected problems (`LoadError`, `FilterError`, `ChartError`) appear in place with their message. Anything else shows "Something went wrong while … The details are in the log." and is logged with its traceback. The logger `data_explorer` writes to stdout in both runtimes, at the level of `DATA_EXPLORER_LOG_LEVEL` (default `INFO`); a load logs the file type, size, rows, columns and duration, never file names or values.

## Charts

| Chart | Prepared in pandas | Drawn as |
|---|---|---|
| Histogram | `numpy.histogram` of the non-missing values, 5 to 100 bins | bars from `bin_start` to `bin_end` |
| Bar | count, sum, mean or median per category, the top N and one bar "Other (n categories)" | horizontal bars, largest first |
| Line | daily, weekly (Monday to Sunday) or monthly periods over the full range, optionally split by a column with up to 8 groups; empty periods are 0 for counts and gaps otherwise | lines, with points up to 60 periods |
| Scatter | rows with both values, a reproducible sample of 5,000 when larger, optionally coloured by a column with up to 8 groups | circles |
| Correlation heatmap | the first 20 numeric columns, Pearson or Spearman, at least 10 pairs per cell | cells on a diverging scale from −1 to 1, with values up to 12 columns |
| Missing values (Quality page) | the share of missing cells per column in up to 100 row blocks | cells on a sequential scale from 0 to 1 |

Every chart carries at most 5,000 rows of inline data, uses the kit's colour palette for the active theme and has a caption that says what it shows. The palette in `core/charts.py` is generated from `web/kit/echarts-theme.js` by `tools/sync_kit.py`, and a test keeps them equal.

## Tests

| Layer | What runs | Where |
|---|---|---|
| `tests/core/` | pytest and hypothesis on every core module: reading rules per fixture, the planted sample defects, statistics, quality rules, every filter operator, the grammar round trip, chart specifications, both CSV dialects, the golden profile, purity (no Streamlit import, inputs unchanged) | Python 3.11 to 3.13 on Ubuntu and Windows, and 3.14 for the browser's interpreter |
| `tests/app/` | Streamlit's AppTest on each page: loading, the guard without a dataset, metrics, quality tables, filters, charts, downloads, state resets | the same matrix |
| `tests/tools/` | the command line, the generator, kit and web sync, versions, the Dockerfile, the page manifest, config parity, the workflows, these docs | the same matrix |
| `tools/checks/stlite_smoke.mjs` | Playwright in Chromium against the stlite page: start, load samples, chart, CSV download, an upload that sends nothing, 390 px layout, the fallback without WebAssembly, no unexpected console errors (two known download-button messages are allowed), no request to another host (the placeholder host `stlite.invalid` is tolerated below the page's media path, `/media/` locally and `/data-explorer-app/media/` on Pages) | CI on `web/` served locally, and after each Pages deployment on the live page |
| `docker` job | build, health check, `GET /`, non-root user | CI |
