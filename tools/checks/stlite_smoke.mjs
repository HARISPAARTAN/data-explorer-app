// Smoke test of the stlite page (docs/architecture.md, "Tests"), locally against web/ served on 127.0.0.1 and in CI, also
// against the live Pages URL. Fails on any console error or page error (except exact texts allowed in
// stlite_console_allow.json with an upstream issue link or a stated reason), on any request to a host other than the page's own
// origin, cdn.jsdelivr.net, pypi.org and files.pythonhosted.org, and on any step that does not finish in time.
// One host is tolerated, and only below /media/: stlite.invalid, the placeholder host (.invalid never resolves) in
// the media URLs that Streamlit's download button checks when it renders. stlite 1.12.0 cannot answer that check,
// the download itself works (the Download step saves the file and counts its lines). Those requests are counted
// and printed as "stlite media-check misses", never as external requests; any other path on that host fails.
// The number of allow-listed console messages that fired is printed too, so an allow-list entry that has become
// dead (or a new flood of the same text) shows. After every step of the app context no Streamlit exception
// element may be on the page. Both browser contexts use colorScheme dark, the published look of the kit; the
// page follows prefers-color-scheme.
//
// Environment: URL (default http://127.0.0.1:8000/), OUT (required; screenshots, download.csv, weights.json and
// thumb-1440.jpg go there, never into the repository), PLAYWRIGHT_FROM (a package.json for createRequire; unset in
// CI, where playwright comes from npm install --no-save), BROWSER_CHANNEL (chrome for the installed Chrome),
// FALLBACK (0 skips the fallback context), THUMB_QUALITY (JPEG quality of the thumbnail, default 80).
// Usage (from the repository root): OUT=<folder> node tools/checks/stlite_smoke.mjs
import fs from 'node:fs';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, '..', '..');
const PAGE_URL = process.env.URL || 'http://127.0.0.1:8000/';
const OUT = process.env.OUT ? path.resolve(process.env.OUT) : '';
const FALLBACK = process.env.FALLBACK !== '0';
const THUMB_QUALITY = Number(process.env.THUMB_QUALITY || 80);
const BOOT_TIMEOUT = 240_000;
const STEP_TIMEOUT = 120_000;
const ORIGIN = new URL(PAGE_URL).host;
const MEDIA_CHECK_HOST = 'stlite.invalid';
const ALLOWED_HOSTS = new Set([ORIGIN, 'cdn.jsdelivr.net', 'pypi.org', 'files.pythonhosted.org']);
const UPLOAD_FIXTURE = path.join(REPO, 'fixtures', 'utf8_bom_semicolon_decimal_comma.csv');

if (!OUT) {
  console.error('stlite_smoke: set OUT to a folder outside the repository');
  process.exit(2);
}
if (OUT === REPO || OUT.startsWith(REPO + path.sep)) {
  console.error(`stlite_smoke: OUT must be outside the repository, got ${OUT}`);
  process.exit(2);
}
fs.mkdirSync(OUT, { recursive: true });

// An allow-list entry is { text, issue } with an upstream stlite issue link or, while no upstream issue exists,
// { text, reason } with the reason in words. An optional url_prefix limits the entry to console messages whose
// source URL starts with it. The two entries in the file belong to the stlite.invalid media check described above.
const allowList = JSON.parse(fs.readFileSync(path.join(HERE, 'stlite_console_allow.json'), 'utf8'));
for (const entry of allowList) {
  const linked = /^https:\/\/github\.com\/whitphx\/stlite\/issues\/\d+$/.test(entry.issue ?? '');
  const explained = typeof entry.reason === 'string' && entry.reason.trim() !== '';
  if (typeof entry.text !== 'string' || !(linked || explained)) {
    console.error('stlite_smoke: every allow-list entry needs "text" and either an upstream "issue" link or a "reason"');
    process.exit(2);
  }
}
const isAllowed = (message) =>
  allowList.some(
    (entry) => entry.text === message.text() && (!entry.url_prefix || (message.location().url ?? '').startsWith(entry.url_prefix)),
  );

async function loadPlaywright() {
  if (process.env.PLAYWRIGHT_FROM) return createRequire(process.env.PLAYWRIGHT_FROM)('playwright');
  const module = await import('playwright');
  return module.chromium ? module : module.default;
}

const failures = [];
const mediaMisses = [];
let allowedConsole = 0;
const fail = (message) => {
  failures.push(message);
  console.log(`FAIL ${message}`);
};
const ok = (message) => console.log(`ok   ${message}`);

async function step(name, action) {
  const started = Date.now();
  try {
    await action();
    ok(`${name} (${((Date.now() - started) / 1000).toFixed(1)} s)`);
    return true;
  } catch (error) {
    fail(`${name}: ${error.message.split('\n')[0]}`);
    return false;
  }
}

function watch(context, page, label, hosts) {
  const nonGet = [];
  const onConsole = (message) => {
    if (message.type() !== 'error') return;
    if (isAllowed(message)) allowedConsole += 1;
    else fail(`${label}: console error: ${message.text()}`);
  };
  page.on('console', onConsole);
  page.on('pageerror', (error) => fail(`${label}: page error: ${error.message}`));
  page.on('crash', () => fail(`${label}: the page crashed`));
  page.on('worker', (worker) => worker.on('console', onConsole));
  context.on('request', (request) => {
    const url = new URL(request.url());
    if (url.protocol === 'blob:' || url.protocol === 'data:') return;
    if (url.host === MEDIA_CHECK_HOST && url.pathname.startsWith('/media/')) mediaMisses.push(request.url());
    else if (!ALLOWED_HOSTS.has(url.host)) fail(`${label}: request to ${url.host}: ${request.url()}`);
    if (request.method() !== 'GET') nonGet.push(`${request.method()} ${request.url()}`);
  });
  if (hosts) {
    context.on('requestfinished', async (request) => {
      const url = new URL(request.url());
      if (url.protocol === 'blob:' || url.protocol === 'data:') return;
      const sizes = await request.sizes().catch(() => null);
      const entry = hosts[url.host] ?? (hosts[url.host] = { requests: 0, bytes: 0 });
      entry.requests += 1;
      entry.bytes += sizes ? sizes.responseBodySize + sizes.responseHeadersSize : 0;
    });
  }
  return nonGet;
}

function luminance([r, g, b]) {
  const [R, G, B] = [r, g, b].map((v) => v / 255).map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * R + 0.7152 * G + 0.0722 * B;
}
const rgb = (css) => (css.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);

const { chromium } = await loadPlaywright();
const launch = { headless: true };
if (process.env.BROWSER_CHANNEL) launch.channel = process.env.BROWSER_CHANNEL;
const browser = await chromium.launch(launch);
const hosts = {};
const weights = { url: PAGE_URL, origin: ORIGIN, date: new Date().toISOString(), browser: `chromium ${browser.version()}` };

// --- main context: the app itself -----------------------------------------------------------------
const context = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark', acceptDownloads: true });
const page = await context.newPage();
const nonGet = watch(context, page, 'app', hosts);
const app = page.locator('[data-testid="stApp"]');
const sidebar = page.locator('[data-testid="stSidebar"]');
const heading = (text) => app.locator('h1').filter({ hasText: new RegExp(`^${text}$`) });
const visible = (locator, timeout = STEP_TIMEOUT) => locator.first().waitFor({ state: 'visible', timeout });
// A page that raised shows a Streamlit exception element; every step of the app context must end without one.
const appStep = (name, action) =>
  step(name, async () => {
    await action();
    const raised = await app.locator('[data-testid="stException"]').count();
    if (raised) throw new Error(`${raised} Streamlit exception element(s) on the page`);
  });
// Streamlit shows stSkeleton placeholders while its widgets load; a screenshot waits until they are gone.
const shot = async (name) => {
  await app.locator('[data-testid="stSkeleton"]').first().waitFor({ state: 'detached', timeout: STEP_TIMEOUT });
  await page.screenshot({ path: path.join(OUT, name) });
};
// Scroll the app's main area so that the element's top sits `margin` px below the main area's top, which leaves
// room for Streamlit's header (60 px, opaque). Only the main area moves: web/index.html sizes stMain to the
// frame below the banner, and element.scrollIntoView() would still be free to shift the frame itself.
const scrollMain = (locator, margin = 80) =>
  locator.first().evaluate((element, offset) => {
    const main = element.closest('[data-testid="stMain"]');
    main.scrollTop += element.getBoundingClientRect().top - main.getBoundingClientRect().top - offset;
  }, margin);
const openPage = async (label, title) => {
  await sidebar.getByRole('link', { name: label, exact: true }).click();
  await visible(heading(title));
};
const chooseSample = async (title) => {
  await app.getByText('Use a sample dataset', { exact: true }).click();
  await app.locator('[data-testid="stSelectbox"]').filter({ hasText: 'Sample dataset' }).click();
  await page.getByRole('option', { name: title, exact: true }).click();
  await app.getByRole('button', { name: 'Load', exact: true }).click();
};

const booted = await appStep('the app starts and shows the Upload page', async () => {
  await page.goto(PAGE_URL, { waitUntil: 'domcontentloaded' });
  await visible(heading('Upload'), BOOT_TIMEOUT);
});

if (booted) {
  await appStep('the retail sample loads', async () => {
    await chooseSample('Retail orders');
    await visible(page.getByText('Loaded retail_orders.csv: 6,060 rows × 11 columns.'));
    // The pointer rests on the button after the click and Streamlit darkens a hovered button: measure it at rest.
    await page.mouse.move(0, 0);
    await page.waitForTimeout(800);
    const style = await app
      .getByRole('button', { name: 'Load', exact: true })
      .evaluate((button) => ({ color: getComputedStyle(button).color, background: getComputedStyle(button).backgroundColor }));
    const [high, low] = [luminance(rgb(style.color)), luminance(rgb(style.background))].sort((a, b) => b - a);
    weights.primary_button = { ...style, ratio: Number(((high + 0.05) / (low + 0.05)).toFixed(2)) };
    await shot('upload-1440.png');
  });
  await appStep('Overview', async () => {
    await openPage('Overview', 'Overview');
    await visible(app.getByText('First 100 of 6,060 rows', { exact: true }));
    await shot('overview-1440.png');
  });
  await appStep('Quality', async () => {
    await openPage('Quality', 'Quality');
    await visible(app.getByText('60 duplicate rows in 60 groups', { exact: true }));
    await visible(app.locator('.vega-embed canvas, .vega-embed svg'));
    await shot('quality-1440.png');
  });
  await appStep('Explore', async () => {
    await openPage('Explore', 'Explore');
    const caption = app.getByText('6,060 of 6,060 rows match (100.0 %)', { exact: true });
    await visible(caption);
    // The result sits below the filter builder: scroll to the end of the page, where the 1440 x 900 frame holds
    // the heading, the caption and the table. The page ends with about 140 px of padding, so a margin of 150
    // reaches that end without relying on the browser to clamp the scroll position.
    await scrollMain(app.getByRole('heading', { name: 'Result', exact: true }), 150);
    await page.waitForTimeout(500);
    await shot('explore-1440.png');
  });
  await appStep('Visualise renders a Vega chart', async () => {
    await openPage('Visualise', 'Visualise');
    await visible(app.locator('.vega-embed canvas, .vega-embed svg'));
    await app.locator('[data-testid="stRadio"]').getByText('Line', { exact: true }).click();
    await visible(app.getByText('Weekly count of rows; weeks run Monday to Sunday.', { exact: true }));
    await visible(app.locator('.vega-embed canvas, .vega-embed svg'));
    // The chart starts below the controls and its bottom edge is below the fold of a 1440 x 900 frame: put the
    // Measure control 70 px below the top of the main area (Streamlit's header is 60 px tall and opaque, and the
    // control above stays hidden behind it), which leaves the controls, the whole chart with its axes and the
    // caption in view.
    await scrollMain(app.locator('[data-testid="stSelectbox"]').filter({ hasText: 'Measure' }), 70);
    // The pointer rests where the Line option was; over the chart it would show Streamlit's chart toolbar.
    await page.mouse.move(1400, 880);
    await page.waitForTimeout(1500);
    await shot('visualise-1440.png');
    await page.screenshot({ path: path.join(OUT, 'thumb-1440.jpg'), type: 'jpeg', quality: THUMB_QUALITY });
  });
  await appStep('Download gives the CSV with 6,061 lines', async () => {
    await openPage('Download', 'Download');
    await visible(app.getByText('Current view: 6,060 rows × 11 columns · filter: none', { exact: true }));
    const [download] = await Promise.all([
      page.waitForEvent('download', { timeout: STEP_TIMEOUT }),
      app.getByRole('button', { name: 'Download CSV', exact: true }).click(),
    ]);
    const target = path.join(OUT, 'download.csv');
    await download.saveAs(target);
    const lines = (fs.readFileSync(target, 'utf8').match(/\n/g) ?? []).length;
    if (lines !== 6061) throw new Error(`the CSV has ${lines} lines, expected 6,061`);
    await shot('download-1440.png');
  });
  await appStep('the survey workbook loads with openpyxl', async () => {
    await openPage('Upload', 'Upload');
    await chooseSample('Client survey');
    await visible(page.getByText('Loaded client_survey.xlsx: 1,224 rows × 11 columns.'));
  });
  await appStep('an uploaded file is read in the browser without sending it anywhere', async () => {
    await app.getByText('Upload a file', { exact: true }).click();
    const before = nonGet.length;
    await app.locator('[data-testid="stFileUploader"] input[type="file"]').setInputFiles(UPLOAD_FIXTURE);
    const load = app.getByRole('button', { name: 'Load', exact: true });
    await load.and(page.locator(':enabled')).waitFor({ timeout: STEP_TIMEOUT });
    await load.click();
    await visible(page.getByText('Loaded utf8_bom_semicolon_decimal_comma.csv: 20 rows × 4 columns.'));
    const sent = nonGet.slice(before);
    if (sent.length) throw new Error(`requests other than GET during the upload: ${sent.join(', ')}`);
  });
  await appStep('Overview at 390 px has no horizontal scrolling', async () => {
    await chooseSample('Retail orders');
    await visible(page.getByText('Loaded retail_orders.csv: 6,060 rows × 11 columns.'));
    await openPage('Overview', 'Overview');
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForTimeout(1500);
    const size = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
    if (size.scroll > size.inner) throw new Error(`scrollWidth ${size.scroll} > innerWidth ${size.inner}`);
    await shot('overview-390.png');
  });
}
await context.close();

// --- second context: no WebAssembly, so the fallback card must appear and stlite is never requested -----
if (FALLBACK) {
  const fallbackContext = await browser.newContext({ viewport: { width: 1440, height: 900 }, colorScheme: 'dark' });
  await fallbackContext.addInitScript(() => {
    delete globalThis.WebAssembly;
  });
  const fallbackPage = await fallbackContext.newPage();
  watch(fallbackContext, fallbackPage, 'fallback', null);
  const cdn = [];
  fallbackContext.on('request', (request) => {
    if (new URL(request.url()).host === 'cdn.jsdelivr.net') cdn.push(request.url());
  });
  await step('without WebAssembly the fallback card appears and the CDN is not contacted', async () => {
    await fallbackPage.goto(PAGE_URL, { waitUntil: 'load' });
    await fallbackPage
      .getByRole('heading', { name: 'The live demo cannot start in this browser', exact: true })
      .waitFor({ state: 'visible', timeout: 5000 });
    await fallbackPage.waitForLoadState('networkidle');
    if (cdn.length) throw new Error(`requests to cdn.jsdelivr.net: ${cdn.join(', ')}`);
    await fallbackPage.screenshot({ path: path.join(OUT, 'fallback-1440.png') });
  });
  await fallbackContext.close();
}
await browser.close();

weights.hosts = hosts;
weights.total_bytes = Object.values(hosts).reduce((sum, entry) => sum + entry.bytes, 0);
fs.writeFileSync(path.join(OUT, 'weights.json'), JSON.stringify(weights, null, 2) + '\n');
for (const [host, entry] of Object.entries(hosts)) console.log(`     ${host}: ${entry.requests} requests, ${entry.bytes} bytes`);
console.log(`     stlite media-check misses: ${mediaMisses.length} requests to ${MEDIA_CHECK_HOST} (never resolves, not counted as external requests)`);
console.log(`     allow-listed console messages fired: ${allowedConsole} (${allowList.length} entries in the allow-list)`);
if (weights.primary_button) console.log(`     primary button: ${weights.primary_button.color} on ${weights.primary_button.background}, ${weights.primary_button.ratio}:1`);
console.log(failures.length ? `stlite_smoke: ${failures.length} failures` : `stlite_smoke: all steps passed (${PAGE_URL})`);
process.exit(failures.length ? 1 : 0);
