// WCAG 2.x contrast of the kit tokens around the stlite frame and of the Streamlit theme
// colours that web/index.html passes to stlite, in both themes. Text pairs need 4.5:1; the primary colour as a
// component colour on the app backgrounds needs 3:1. White text on the primary colour (Streamlit draws its
// primary button that way) is reported, not enforced: the colour is the kit accent, the text colour is Streamlit's.
// Usage (from the repository root): node tools/checks/contrast.mjs
import fs from 'node:fs';

const css = fs.readFileSync('web/kit/tokens.css', 'utf8');
const html = fs.readFileSync('web/index.html', 'utf8');
const split = css.indexOf(':root[data-theme="light"]');
if (split < 0) throw new Error('web/kit/tokens.css has no :root[data-theme="light"] block');
const vars = (text) =>
  Object.fromEntries([...text.matchAll(/--([\w-]+)\s*:\s*(#[0-9a-fA-F]{6})\b/g)].map((match) => [match[1], match[2]]));
const dark = vars(css.slice(0, split));
const kit = { dark, light: { ...dark, ...vars(css.slice(split)) } };
const block = /<script type="application\/json" id="app-config">([\s\S]*?)<\/script>/.exec(html);
if (!block) throw new Error('web/index.html has no app-config block');
const themes = JSON.parse(block[1]).themes;

function luminance(hex) {
  const [r, g, b] = [1, 3, 5]
    .map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function ratio(a, b) {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

const KIT_PAIRS = [
  ['text', 'bg', 4.5],
  ['text', 'surface', 4.5],
  ['text', 'surface-2', 4.5],
  ['muted', 'bg', 4.5],
  ['muted', 'surface', 4.5],
  ['muted', 'surface-2', 4.5],
  ['accent', 'bg', 4.5],
  ['accent', 'surface', 4.5],
  ['accent-fg', 'accent', 4.5],
];
const THEME_PAIRS = [
  ['theme.textColor', 'theme.backgroundColor', 4.5],
  ['theme.textColor', 'theme.secondaryBackgroundColor', 4.5],
  ['theme.primaryColor', 'theme.backgroundColor', 3],
  ['theme.primaryColor', 'theme.secondaryBackgroundColor', 3],
];

let checked = 0;
let failed = 0;
function check(scope, fgName, fg, bgName, bg, min) {
  checked += 1;
  if (!fg || !bg) {
    failed += 1;
    console.log(`FAIL   ${scope.padEnd(15)} missing ${fgName} or ${bgName}`);
    return;
  }
  const value = ratio(fg, bg);
  const pass = value >= min;
  if (!pass) failed += 1;
  console.log(
    `${pass ? 'ok    ' : 'FAIL  '} ${scope.padEnd(15)} ${fgName} on ${bgName} ${fg} / ${bg}  ${value.toFixed(2)}:1 (min ${min})`,
  );
}

for (const mode of ['dark', 'light']) {
  for (const [fg, bg, min] of KIT_PAIRS) check(`kit ${mode}`, `--${fg}`, kit[mode][fg], `--${bg}`, kit[mode][bg], min);
  const theme = themes[mode];
  for (const [fg, bg, min] of THEME_PAIRS) check(`streamlit ${mode}`, fg, theme[fg], bg, theme[bg], min);
}
for (const mode of ['dark', 'light']) {
  const primary = themes[mode]['theme.primaryColor'];
  console.log(
    `report streamlit ${mode.padEnd(5)}   white on theme.primaryColor #FFFFFF / ${primary}  ${ratio('#FFFFFF', primary).toFixed(2)}:1 (primary button text, not enforced)`,
  );
}
console.log(failed ? `contrast: ${failed} of ${checked} pairs below the minimum` : `contrast: ${checked} pairs ok`);
process.exit(failed ? 1 : 0);
