// Page weight (ADR 0001). The repository's own files under web/ are at
// most 3 MB (1 MB = 1,048,576 bytes, as in the app's size limits). Every file under web/ counts, the fallback
// images too, so the figure is an upper bound of what the page loads from its own origin. With
// WEIGHTS=<weights.json written by stlite_smoke.mjs> the bytes the browser received per host are printed as
// well; the CDN bytes are reported for the README Status, not capped.
// Usage (from the repository root): node tools/checks/page-weight.mjs
import fs from 'node:fs';
import path from 'node:path';

const LIMIT = 3 * 1024 * 1024;
const mb = (bytes) => `${(bytes / 1024 / 1024).toFixed(2)} MB`;

function files(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(dir, entry.name);
    return entry.isDirectory() ? files(full) : [full];
  });
}

const groups = new Map();
let total = 0;
for (const file of files('web')) {
  const parts = path.relative('web', file).split(path.sep);
  const group = parts.length > 1 ? `${parts[0]}/` : parts[0];
  const size = fs.statSync(file).size;
  groups.set(group, (groups.get(group) ?? 0) + size);
  total += size;
}
for (const [group, size] of [...groups].sort((a, b) => b[1] - a[1])) console.log(`${group.padEnd(14)} ${mb(size)}`);
let failed = total > LIMIT;
console.log(`page-weight: own files ${mb(total)} of at most ${mb(LIMIT)}: ${failed ? 'FAIL' : 'ok'}`);

if (process.env.WEIGHTS) {
  const weights = JSON.parse(fs.readFileSync(process.env.WEIGHTS, 'utf8'));
  for (const [host, entry] of Object.entries(weights.hosts).sort((a, b) => b[1].bytes - a[1].bytes)) {
    console.log(`${host.padEnd(26)} ${String(entry.requests).padStart(4)} requests  ${mb(entry.bytes)}`);
  }
  const own = weights.hosts[weights.origin]?.bytes ?? 0;
  console.log(`page-weight: received ${mb(weights.total_bytes)} in total, ${mb(own)} from ${weights.origin}`);
  if (own > LIMIT) failed = true;
}
process.exit(failed ? 1 : 0);
