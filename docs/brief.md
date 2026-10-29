# Client brief

Rebuilt from memory as a demo. The original client's name and data are not used. Meridian Analytics Collective is a fictional company, and every dataset in this repository is invented.

## The brief as the client wrote it

> We are a small analytics team in Milan. Colleagues from other departments keep sending us CSV and Excel files with the same question: what is in here, and is it usable? We want a web app where anyone on the team can upload a CSV or Excel file and immediately see summary statistics, missing values and duplicates, filter the rows, draw a few standard charts and download the filtered data together with a short profile of the file. Users should not have to install anything. Exports from Italian and English Excel settings must both work (semicolons, decimal commas). Python on our side, so we can extend it later. Contact: data-team@meridian.example.

## Goal

A working, tested Streamlit app that opens any reasonable CSV or Excel file, explains what is in it and lets a colleague without a technical background filter, chart and download it. It runs in two places from one code base: in the browser on GitHub Pages, with no server, and on a server from a Docker image. All computation sits in a pure `core/` package with unit tests; the Streamlit pages are a thin shell over it.

## Users

| Role | Who | What they do in the app |
|---|---|---|
| Contributor | A colleague outside the analytics team | Uploads a file, reads Overview and Quality, downloads a CSV |
| Analyst | A member of the team | Builds filters with the widgets or as text, draws charts, exports the profile as JSON or Markdown to attach to a ticket |
| Maintainer | The team member who runs the server | Builds and runs the Docker image, lowers the limits with environment variables, updates the pinned versions with [the handover notes](handover.md) |

There is no login and no role logic: every visitor sees the same six pages. Access control for a server deployment belongs to the team's reverse proxy.

## Scope

In scope: the package (`core/`, `app/`, the command line), three sample datasets and their seeded generator, test fixtures, the browser demo page, the Docker image, tests, CI and Pages workflows, these docs, the README in English and German, release `v0.1.0` with the wheel and the sdist.

Out of scope: authentication; storing uploads or sessions (everything stays in memory); databases and SQL sources; Parquet, JSON and legacy `.xls` input; editing cells; joining several files; reading files larger than memory in chunks; XLSX or PDF downloads; OCR or machine-learning features; a hosted Streamlit service; publishing the image to a registry.

## Acceptance

1. All six pages work on the server and in the browser with the three samples and with every fixture that should load.
2. `uv run pytest` passes on Ubuntu and Windows with Python 3.11, 3.12 and 3.13; `tests/core` passes on Python 3.14; ruff, ruff format and strict mypy on `core` are clean.
3. The Docker image builds in CI and its health check answers 200.
4. The browser smoke test passes against `web/` in CI and against the live page after each deployment, with no unexpected console errors (two known download-button messages are allowed, see [the handover notes](handover.md#known-console-messages-in-the-browser)) and no request to a host outside the allowed three, apart from the harmless lookup of the placeholder host `stlite.invalid`; the fallback check passes.
5. The repository checks pass: scrub, links, contrast, and at most 3 MB of the repository's own files on the demo page.
6. The README in English and German, these docs and the five ADRs are complete; the README Status section claims only what CI and the smoke test show.
7. Release `v0.1.0` has a CHANGELOG entry, an annotated tag and a GitHub Release with the wheel and the sdist.
