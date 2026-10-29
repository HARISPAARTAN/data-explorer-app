# ADR 0001: stlite for the live demo

Status: accepted (2026-10-29)

## Context

The brief asks for an app that colleagues use without installing anything, and the portfolio needs a live demo on GitHub Pages, which serves static files only. The demo should be the real app, so that the tests describe what visitors use.

## Decision

The demo page runs the same Streamlit app in the browser with stlite: `web/index.html` imports `@stlite/browser@1.12.0` from cdn.jsdelivr.net, which brings its Streamlit wheel and loads its default Pyodide from the same CDN; micropip installs openpyxl from PyPI. The import happens only after a check for WebAssembly and module workers, so a browser without them gets a fallback card and never contacts the CDN. The page has its own loading and fallback cards, no Content-Security-Policy meta tag and no subresource integrity: a dynamic `import()` cannot carry an integrity value, so the exact version in the URL and the smoke test's host allowlist take its place. The Python files reach the page through `web/py/`, a copy of `src/` that CI checks.

## Consequences

- The page requests three outside hosts: cdn.jsdelivr.net, pypi.org and files.pythonhosted.org. This is the one page in the portfolio that does; its smoke test allows the page's own origin and exactly these three, tolerates one more host, the placeholder `stlite.invalid` below the page's media path (`/media/` locally, `/data-explorer-app/media/` on Pages) that never resolves ([the handover notes](../handover.md#known-console-messages-in-the-browser)), and fails on any other.
- The first visit downloads the Python runtime and libraries; the README Status reports the measured size. Later visits use the browser cache.
- The own-file weight limit of 3 MB applies to the repository's files on the page; the CDN bytes are measured and reported, not capped.
- Browsers without WebAssembly or module workers (for example Firefox before 114, since Pyodide 314) see the fallback card.
- The browser runs with lower limits and loses its data on reload.

## Alternatives considered

- A hosted Streamlit service: needs an account and a running server, sleeps when idle, and uploads would leave the browser.
- A JavaScript copy of the app: a second implementation that the Python tests would not cover.
- Self-hosting stlite and Pyodide on Pages: the npm package alone is about 114 MB unpacked, before the Pyodide distribution.
