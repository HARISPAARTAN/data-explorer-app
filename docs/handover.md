# Handover

Notes for the person who runs or changes the app. Commands run from the repository root.

## Run locally

```bash
uv sync
uv run data-explorer run                       # http://127.0.0.1:8501
uv run data-explorer run --host 0.0.0.0 --port 8600
uv run data-explorer run --dry-run             # print the Streamlit command without starting it
uv run data-explorer samples --out samples-copy
uv run data-explorer --version
```

`run` starts `python -m streamlit run` on the packaged `streamlit_app.py` with the settings of `.streamlit/config.toml` passed as flags, so it works from an installed wheel too. Exit codes: 0 success, 1 runtime error (a non-zero exit code of Streamlit is passed through), 2 usage error.

CI and the Dockerfile install with `uv sync --locked`, which fails when `uv.lock` does not match `pyproject.toml`; `--frozen` is not used, because it would install the lock without that check.

## Run with Docker

```bash
docker build -t data-explorer .
docker run --rm -p 8501:8501 data-explorer
docker run --rm -p 8501:8501 -e DATA_EXPLORER_MAX_MB=20 -e DATA_EXPLORER_LOG_LEVEL=DEBUG data-explorer
```

The image serves on port 8501 as the user `app` (uid 10001); its health check calls `/_stcore/health` with Python (the slim image has no curl). It has no login: put it behind the team's reverse proxy for access control.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `DATA_EXPLORER_MAX_MB` | 50 | largest file in MB (1 MB = 1,048,576 bytes); values above 50 count as 50, the upload widget's own limit |
| `DATA_EXPLORER_MAX_ROWS` | 1,000,000 | most rows; values above the default count as the default |
| `DATA_EXPLORER_MAX_COLS` | 500 | most columns; values above the default count as the default |
| `DATA_EXPLORER_LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`; any other value logs a warning and uses `INFO` |

An empty variable counts as unset. A limit that is not a positive integer stops the Upload page with "DATA_EXPLORER_MAX_ROWS must be a positive integer" (or the name of the variable concerned). The browser demo ignores these variables and uses 20 MB, 200,000 rows and 200 columns.

## Logs

The logger `data_explorer` writes one line per event to stdout: `<time> <LEVEL> data_explorer <message>`. A load logs `load file_type=csv size_bytes=... rows=... cols=... duration_ms=...`; an unexpected error logs `unexpected error while <action>` with the traceback. The load line carries counts and a duration only, never a file name or a cell value; the traceback of an unexpected error ends with the exception message, which a library can word with a value from the data. In the browser the same lines appear in the developer console.

## Adding a sample

1. Write a `build_<name>(rng)` function in `tools/make_data.py` that returns the file's bytes, with its defects planted in exact numbers, and add it to `build_samples()` with a random generator of its own (extend `_rngs()`), so the existing samples keep their bytes.
2. Add a `SampleInfo` entry to `SAMPLES` in `src/data_explorer/core/io.py`, and the file name to `SAMPLE_FILES` in `src/data_explorer/cli.py`.
3. Run `uv run python tools/make_data.py`, then `uv run python tools/sync_web.py`, and add the new file to the `files` map of the `app-config` block in `web/index.html`.
4. Describe it in `docs/data-model.md` and assert its defects in `tests/core/test_samples.py`. `tests/tools/test_docs.py`, `test_web_manifest.py` and `test_sync_web.py` show what else needs updating.

## Adding a chart type

1. Write the chart function in `src/data_explorer/core/charts.py`: aggregate in pandas, keep the inline data at most 5,000 rows, raise `ChartError` with a message for unusable input, and return an Altair chart with a caption.
2. Test it in `tests/core/test_charts.py` from `chart.to_dict()`.
3. Add it to `TYPES` and the controls in `src/data_explorer/app/pages/5_Visualise.py`, and to the parametrized test in `tests/app/test_visualise.py`.
4. Run `uv run python tools/sync_web.py` and the smoke test.

## Updating the pinned versions

The pinned versions are @stlite/browser@1.12.0, which runs Streamlit 1.65.0 on Pyodide 314.0.3 (Python 3.14) with pandas 3.0.2 and Altair 6.0.0, plus openpyxl 3.1.5 from PyPI ([ADR 0004](adr/0004-browser-server-version-parity.md)). To move to a new stlite release:

1. Read the stlite release notes for the new `@stlite/browser` version: the Streamlit version of its wheel, the Pyodide version, the Python version, removed modules.
2. Read the package list of that Pyodide version for pandas, Altair and numpy.
3. Change `src/data_explorer/_versions.py`.
4. Change the pins in `pyproject.toml` (`streamlit`, `pandas`, `altair`, `openpyxl`) and run `uv lock`.
5. Change the two stlite URLs (`STLITE_CSS`, `STLITE_JS`) and, if needed, the `openpyxl==` pin in `web/index.html`.
6. Run `uv sync`, `uv run pytest -q`, the Python 3.14 core tests (`UV_PROJECT_ENVIRONMENT=.venv-314 uv run --python 3.14 pytest tests/core -q`) and the smoke test.
7. Read the end of the smoke test's output: `stlite media-check misses` and `allow-listed console messages fired`. When stlite no longer sends the download-button check to `stlite.invalid`, both counts are 0: remove the two entries of `tools/checks/stlite_console_allow.json` and, if the requests are gone too, the `stlite.invalid` tolerance in `tools/checks/stlite_smoke.mjs` ([Known console messages in the browser](#known-console-messages-in-the-browser)). If an upstream issue exists by then, put its link in an `issue` field instead of the `reason`.
8. Update the README Status after CI and the Pages smoke test have passed.

## Re-checking the Docker digests

Both base images are pinned by digest, with the date of resolution in the Dockerfile's header comment. To read the current digests of the two tags:

```bash
TOKEN=$(curl -fsS "https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/python:pull" | uv run python -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -fsSI -H "Authorization: Bearer $TOKEN" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
  https://registry-1.docker.io/v2/library/python/manifests/3.12-slim | grep -i '^docker-content-digest'
GHCR=$(curl -fsS "https://ghcr.io/token?scope=repository:astral-sh/uv:pull" | uv run python -c "import json,sys; print(json.load(sys.stdin)['token'])")
curl -fsSI -H "Authorization: Bearer $GHCR" \
  -H "Accept: application/vnd.oci.image.index.v1+json" \
  -H "Accept: application/vnd.docker.distribution.manifest.list.v2+json" \
  https://ghcr.io/v2/astral-sh/uv/manifests/0.11.8 | grep -i '^docker-content-digest'
```

With Docker installed, `docker buildx imagetools inspect python:3.12-slim` prints the same value as `Digest:`. Put a new digest into both places of the Dockerfile (the header comment and the instruction) with today's date; `tests/tools/test_dockerfile.py` checks that they agree. Dependabot opens pull requests for new digests but changes only the instruction, so such a pull request fails that test until the header comment is updated in the same branch. A new uv version also changes the three `version:` lines of the setup-uv steps in `.github/workflows/ci.yml` (`tests/tools/test_workflows.py` compares them). The same holds for a Dependabot pull request for the uv image: it changes only the `COPY --from` line of the Dockerfile, so the uv line of the header comment and the three `version:` lines in `ci.yml` need a follow-up commit on its branch. `astral-sh/setup-uv` is pinned by commit (the one of release v10.3.3, named in a comment on the `uses:` line); the other actions use major version tags.

## Updating the kit

The frame of the demo page comes from portfolio-kit, vendored into `web/kit/` at the tag in `tools/sync_kit.py` (`KIT_TAG`). To move to a new tag: change `KIT_TAG`, run `uv run python tools/sync_kit.py` (it reads `git archive` of the local kit clone, next to this repository or at `PORTFOLIO_KIT_REPO`), and the same command rewrites the palette block in `core/charts.py` from the new `echarts-theme.js`. CI checks out the kit at the same tag (`.github/workflows/ci.yml`, job `lint`) and runs `--check`.

## Checks

| Command | What it checks |
|---|---|
| `uv run python tools/checks/scrub.py` | names and terms that must not appear in files or commit messages; the committed terms are stored as hashes. A maintainer can add a local, never-committed list of patterns with `--banned-file <path>` |
| `node tools/checks/verify-site.mjs` | links and anchors in the READMEs, the CHANGELOG, `docs/` and `web/index.html`; `OFFLINE=1` skips outside links, `PUBLISHED=1` checks the links into this repository too |
| `node tools/checks/contrast.mjs` | WCAG contrast of the kit tokens and the Streamlit theme colours in both themes; it only reports, without enforcing it, white text on the primary colour, which is how Streamlit draws its primary button |
| `node tools/checks/page-weight.mjs` | at most 3 MB of the repository's own files under `web/`; with `WEIGHTS=<weights.json>` also the bytes per host of a smoke run |
| `OUT=<folder> node tools/checks/stlite_smoke.mjs` | the browser smoke test against `URL` (default `http://127.0.0.1:8000/`, serve it with `uv run python -m http.server 8000 --bind 127.0.0.1 -d web`); needs Playwright (`npm install --no-save playwright@1.64.1` and `npx playwright install chromium` in a scratch folder, or `PLAYWRIGHT_FROM=<package.json>` of an existing installation) |

`OUT` must be outside the repository; the script refuses a folder inside it. The smoke test fails on every console error that is not on its allow-list and on every request to an unlisted host, so a pass means no unexpected console errors; it does not mean that the console is empty (see the next section).

The text on the primary button is below the usual contrast minimum in the dark theme: `contrast.mjs` reports 2.00:1 for white on the amber primary `#F2A93B`, and the smoke test prints the ratio it measures on the rendered Load button at rest, about 2.0:1. In the light theme `contrast.mjs` reports 5.02:1 for white on the light primary `#B45309`. These are measurements, not a compliance statement: the repository makes no claim of WCAG compliance for the primary button, and the owner decides what to do about the dark one.

Playwright 1.64.1 is pinned only in the `npm install` lines of the two smoke jobs (`stlite-local` in `ci.yml`, `smoke` in `pages.yml`), where Dependabot does not look; `tests/tools/test_workflows.py` pins the same text, so a new version is a manual change in both workflows and in that test. Both smoke jobs also need cdn.jsdelivr.net and pypi.org (and files.pythonhosted.org, where PyPI serves its files) to answer: an outage of one of them fails the job without any change in this repository.

## Known console messages in the browser

Streamlit 1.65 checks the media URL of every download button when the button renders. stlite 1.12.0 answers with a placeholder host, `stlite.invalid`, which never resolves, so the Download page shows two console errors per button render, `Failed to load resource: net::ERR_NAME_NOT_RESOLVED` and `Client Error: Download Button fetch error - Failed to fetch`, and the browser makes a harmless DNS lookup that fails. Clicking a download button works: the smoke test saves the CSV and counts its lines. No upstream issue was found.

The smoke test handles this in two places. It tolerates requests to `stlite.invalid` below `/media/` only (any other path on that host fails), counts them and prints the count as `stlite media-check misses`. It allow-lists the two console messages in `tools/checks/stlite_console_allow.json`, each with a `reason` (the first only for the `stlite.invalid` media URL), and prints how many allow-listed messages fired, so an entry that has become dead shows. After a stlite update, re-check both and remove the two entries when the messages are gone ([Updating the pinned versions](#updating-the-pinned-versions), step 7).

The outbound hosts of the page are therefore the allow-list of the smoke test (the page's own origin, cdn.jsdelivr.net, pypi.org and files.pythonhosted.org) plus that `.invalid` probe.

## Pages deployment

`.github/workflows/pages.yml` runs on every push to `main` and when started manually. Its `deploy` job checks `web/py` against `src` with `tools/sync_web.py --check`, uploads `web/` and publishes it to the `github-pages` environment; its `smoke` job then runs the smoke test against the published address. The deployment is not gated on CI: it does not wait for the `ci.yml` jobs of the same commit, so a push to `main` goes live even when those jobs fail, and the smoke job reports a broken page only after it is live. The owner should restrict the `github-pages` environment to the `main` branch (repository settings, Environments, `github-pages`, deployment branches), so that no other branch or tag can publish.

## Releasing

1. Move the `## Unreleased` entries of `CHANGELOG.md` under `## vX.Y.Z (YYYY-MM-DD)` and set `version` in `pyproject.toml` and `__version__` in `src/data_explorer/__init__.py`; run `uv lock` and `uv run python tools/sync_web.py`.
2. Commit as `chore: release X.Y.Z`, tag with `git tag -a vX.Y.Z -m "vX.Y.Z"` and push the branch and the tag.
3. `uv build` writes the wheel and the sdist to `dist/`; attach both to the GitHub Release (`gh release create vX.Y.Z dist/* --title vX.Y.Z --notes-file <notes>`).
