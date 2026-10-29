# ADR 0002: Pure core, thin Streamlit shell

Status: accepted (2026-10-29)

## Context

The app runs in two runtimes, and the browser runtime has no `streamlit.testing`, so page-level tests run only on the server. Reading files, statistics, filters, charts and downloads are where the bugs would be, and they should be testable quickly and on the browser's interpreter as well.

## Decision

All computation lives in `data_explorer.core`: `io`, `profile`, `quality`, `filters`, `charts`, `export`. Core imports only the standard library, numpy, pandas, Altair and openpyxl. Its functions are pure: they never change the frame they receive and return new objects, mostly frozen dataclasses with a `to_dict()`. `data_explorer.app` holds the Streamlit pages, the session-state keys, the cache wrappers and small display helpers, and contains no rules of its own. A test imports every core module with Streamlit blocked and checks that no public function changes its input.

## Consequences

- Most behaviour is covered by fast pytest and hypothesis tests, which also run on Python 3.14 for the browser.
- mypy runs in strict mode on core.
- The pages are tested with AppTest for wiring and messages, not for computation.
- A new feature usually needs a core function and a page change, in that order.

## Alternatives considered

- Logic inside the page scripts: testable only through AppTest, which the browser runtime lacks, and slow to test thoroughly.
- A separate API service behind the pages: contradicts a demo without a server.
