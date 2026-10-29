// Link check for README.md, README.de.md, CHANGELOG.md, docs/**/*.md and web/index.html.
// Relative links must name an existing file or folder, an anchor must name a heading of the target Markdown
// file (GitHub heading ids), and external links must answer with a status below 400. Links into this
// repository or its Pages site exist only after the first push, so they are listed as pending unless PUBLISHED=1.
// Usage (from the repository root): node tools/checks/verify-site.mjs
//   OFFLINE=1 skips the external links; PUBLISHED=1 checks the links into this repository too.
import fs from 'node:fs';
import path from 'node:path';

const ROOT = process.cwd();
const OWN = ['https://github.com/HARISPAARTAN/data-explorer-app', 'https://harispaartan.github.io/data-explorer-app'];
const OFFLINE = process.env.OFFLINE === '1';
const PUBLISHED = process.env.PUBLISHED === '1';

function markdownFiles(dir) {
  const full = path.join(ROOT, dir);
  if (!fs.existsSync(full)) return [];
  return fs.readdirSync(full, { withFileTypes: true }).flatMap((entry) => {
    const rel = path.posix.join(dir, entry.name);
    if (entry.isDirectory()) return markdownFiles(rel);
    return entry.name.endsWith('.md') ? [rel] : [];
  });
}

const FILES = ['README.md', 'README.de.md', 'CHANGELOG.md', ...markdownFiles('docs'), 'web/index.html'].filter((file) =>
  fs.existsSync(path.join(ROOT, file)),
);

function slug(heading) {
  return heading
    .trim()
    .toLowerCase()
    .replace(/<[^>]+>/g, '')
    .replace(/[^\p{L}\p{N}\s_-]/gu, '')
    .replace(/\s/g, '-');
}

const headingCache = new Map();
function headings(file) {
  if (headingCache.has(file)) return headingCache.get(file);
  const text = fs.readFileSync(path.join(ROOT, file), 'utf8');
  const ids = new Set();
  const seen = new Map();
  let fenced = false;
  for (const line of text.split('\n')) {
    if (/^(```|~~~)/.test(line)) {
      fenced = !fenced;
      continue;
    }
    const match = fenced ? null : /^#{1,6}\s+(.*?)\s*#*\s*$/.exec(line);
    if (!match) continue;
    const base = slug(match[1]);
    const count = seen.get(base) ?? 0;
    seen.set(base, count + 1);
    ids.add(count ? `${base}-${count}` : base);
  }
  for (const match of text.matchAll(/<a\s+(?:id|name)="([^"]+)"/g)) ids.add(match[1]);
  headingCache.set(file, ids);
  return ids;
}

function links(file) {
  let text = fs.readFileSync(path.join(ROOT, file), 'utf8');
  if (file.endsWith('.md')) text = text.replace(/```[\s\S]*?```/g, '').replace(/`[^`\n]*`/g, '');
  const found = [];
  for (const match of text.matchAll(/\]\(\s*<?([^)\s>]+)>?(?:\s+"[^"]*")?\s*\)/g)) found.push(match[1]);
  for (const match of text.matchAll(/\b(?:href|src)="([^"]+)"/g)) found.push(match[1]);
  return [...new Set(found)];
}

async function probe(url) {
  for (const method of ['HEAD', 'GET']) {
    try {
      const response = await fetch(url, {
        method,
        redirect: 'follow',
        signal: AbortSignal.timeout(20000),
        headers: { 'user-agent': 'data-explorer-app link check' },
      });
      if (method === 'HEAD' && [403, 405, 501].includes(response.status)) continue;
      return response.status;
    } catch {
      if (method === 'GET') return 0;
    }
  }
  return 0;
}

const count = { ok: 0, pending: 0, skipped: 0, failed: 0 };
const fail = (message) => {
  count.failed += 1;
  console.log(`FAIL    ${message}`);
};
const external = new Map();
for (const file of FILES) {
  for (const link of links(file)) {
    if (/^(mailto:|data:|tel:)/.test(link)) continue;
    if (/^https?:\/\//.test(link)) {
      external.set(link, [...(external.get(link) ?? []), file]);
      continue;
    }
    const [target, anchor] = link.split('#');
    const resolved = target ? path.posix.normalize(path.posix.join(path.posix.dirname(file), decodeURI(target))) : file;
    if (resolved.startsWith('..')) {
      fail(`${file}: ${link} points outside the repository`);
    } else if (!fs.existsSync(path.join(ROOT, resolved))) {
      fail(`${file}: ${link} does not exist`);
    } else if (anchor && resolved.endsWith('.md') && !headings(resolved).has(anchor)) {
      fail(`${file}: ${link} has no heading #${anchor}`);
    } else {
      count.ok += 1;
    }
  }
}
for (const [url, files] of external) {
  if (!PUBLISHED && OWN.some((prefix) => url.startsWith(prefix))) {
    count.pending += 1;
    console.log(`pending ${url} (exists after the first push)`);
  } else if (OFFLINE) {
    count.skipped += 1;
  } else {
    const status = await probe(url);
    if (status === 0 || status >= 400) fail(`${url} answered ${status || 'nothing'} (${files.join(', ')})`);
    else count.ok += 1;
  }
}
console.log(
  `verify-site: ${FILES.length} files, ${count.ok} links ok, ${count.pending} pending, ${count.skipped} skipped, ${count.failed} failed`,
);
process.exit(count.failed ? 1 : 0);
