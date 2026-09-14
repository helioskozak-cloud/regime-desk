/* The risk-axis explainer panel, driven in jsdom against the REAL
   docs/index.html handler.

   Owner, 2026-09-14: "this has just become a screen of numbers and I don't know
   what they all mean." The panel is the answer, so the assertions are about the
   two ways it could fail him: a control that renders and does nothing (the
   07-30 bug, same as news_dom.test.js), and a panel that states a threshold
   already crossed as though it were still ahead.

   The handler is lifted out of the shipped page rather than reimplemented here.
   A copy in the test would keep passing after the page stopped working. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const REPO = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(REPO, 'docs/index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ok   ' + name); }
  else { fail++; console.log('  FAIL ' + name + (extra ? '  -> ' + extra : '')); }
};

// ── the shipped handler, verbatim ────────────────────────────────────────────
const HSTART = '/* Risk-axis explainer: open the panel under a row.';
const HEND = '</script>\n<div id="rd-tip"></div>';
if (html.indexOf(HSTART) < 0) {
  console.log('  FAIL the explainer handler is not in docs/index.html');
  process.exit(1);
}
const handler = html.slice(html.indexOf(HSTART), html.indexOf(HEND));

// ── the shipped renderer, verbatim ───────────────────────────────────────────
const RSTART = '  const AX_MEASURES={';
const REND = '  const rows=risks.map(r=>{';
const renderer = html.slice(html.indexOf(RSTART), html.indexOf(REND));

const risks = JSON.parse(
  fs.readFileSync(path.join(REPO, 'data/cross_asset.json'), 'utf8')).risks;

// ── 1. the panel's CONTENT, against the real published snapshot ──────────────
const sandbox = new JSDOM('<!doctype html><body></body>').window;
sandbox.eval("const axCol=v=>v>=0.65?'red':v>=0.45?'amber':'green';\n" + renderer);
const why = sandbox.eval('why');

console.log('\nPanel content, over the real snapshot:');
ok('every axis renders a panel', risks.every((r) => why(r).includes('rax-why-in')));

for (const r of risks) {
  const text = why(r).replace(/<[^>]+>/g, ' ').replace(/\s+/g, ' ');
  const e = r.explain || {};
  const sc = r.score || 0;
  if (e.input_value == null) continue;

  // The reading that produced the score has to be ON the panel. Without it the
  // panel explains the axis but not the number, which is the whole complaint.
  ok(`${r.name}: shows its input`, text.includes(e.input_value));

  // A crossed line must read as crossed. Printing "red at -5.0%" for an axis
  // whose input is already -9.9% describes a future that is the present.
  if (sc >= 0.65) {
    ok(`${r.name}: elevated says both lines are behind it`,
      /already behind it/.test(text) && /elevated now/.test(text),
      text.slice(0, 90));
    ok(`${r.name}: does not promise a future crossing`,
      !/It turns (amber|red) when/.test(text));
  } else if (sc >= 0.45) {
    ok(`${r.name}: moderate says amber is passed and names the red trigger`,
      /Past the amber line already/.test(text) && text.includes(e.elevated_at));
  } else {
    ok(`${r.name}: low names the amber trigger`,
      /Below both lines/.test(text) && text.includes(e.moderate_at));
  }

  // Direction is read off the axis function upstream, not guessed from the
  // sign of a formatted string. An input that LOWERS the score as it rises
  // must say "falls to".
  if (e.input_rises === false && sc < 0.65) {
    ok(`${r.name}: says "falls to" for an inverted input`, /falls to/.test(text));
  }
}

// ── the chip colouring, on a case today's data cannot produce ───────────────
//
// `past` vs `next` decides whether a threshold chip is drawn red. It must be
// read off the SCORE, never by comparing the formatted strings — but on the
// real snapshot the two orderings agree on all seven axes, so a string
// comparison passes every assertion above. This axis is invented precisely
// because it separates them: "10.0" >= "9.0" is FALSE as strings ('1' < '9')
// and TRUE as numbers, and the score says the line is long behind us.
const TRICKY = {
  name: 'Volatility Regime',
  score: 0.72,
  description: 'synthetic',
  invalidation: 'synthetic',
  range90: { lo: 0.1, hi: 0.9 },
  range30: { lo: 0.2, hi: 0.8 },
  explain: {
    input_label: 'VIX', input_value: '10.0',
    moderate_at: '9.0', elevated_at: '9.5', input_rises: true, note: null,
  },
};
{
  const html = why(TRICKY);
  const chips = html.match(/class="rax-chip ([a-z]*)"/g) || [];
  ok('a crossed threshold is marked past even when string order disagrees',
    chips.filter((c) => c.includes('past')).length === 2,
    JSON.stringify(chips));
  ok('an elevated axis says both lines are behind it',
    /already behind it/.test(html.replace(/<[^>]+>/g, ' ')));
}

// A number with no range is the thing he said was meaningless. It must survive
// into the panel.
ok('the 90-day range is restated in the panel',
  risks.filter((r) => r.range90).every((r) =>
    /Over 90 days it has run/.test(why(r))));

// ── 2. the panel's BEHAVIOUR ─────────────────────────────────────────────────
console.log('\nToggle behaviour:');
const dom = new JSDOM(`<!doctype html><body>
 <div class="rax" role="button" tabindex="0" aria-expanded="false" data-why="why-A"><span class="rax-chev">&#9654;</span></div>
 <div class="rax-why" id="why-A" hidden>A</div>
 <div class="rax" role="button" tabindex="0" aria-expanded="false" data-why="why-B"><span class="rax-chev">&#9654;</span></div>
 <div class="rax-why" id="why-B" hidden>B</div>
</body>`, { runScripts: 'outside-only' });
const { window } = dom;
const d = window.document;
window.eval(handler);

const A = d.querySelector('[data-why="why-A"]');
const B = d.querySelector('[data-why="why-B"]');
const pA = d.getElementById('why-A');
const pB = d.getElementById('why-B');
const click = (el) => el.dispatchEvent(new window.MouseEvent('click', { bubbles: true }));
const key = (el, k) => el.dispatchEvent(new window.KeyboardEvent('keydown', { key: k, bubbles: true }));

ok('both panels start closed', pA.hidden && pB.hidden);
click(A);
ok('clicking a row opens its panel', !pA.hidden);
ok('aria-expanded follows the panel', A.getAttribute('aria-expanded') === 'true');
ok('chevron turns down when open', A.querySelector('.rax-chev').innerHTML === '▼');
click(B);
// One at a time: this is a comparison card, and three open panels push the
// other axes off screen -- the exact fault the one-line-per-axis rebuild fixed.
ok('opening another closes the first', !pB.hidden && pA.hidden);
ok('the closed row resets its aria', A.getAttribute('aria-expanded') === 'false');
ok('the closed row resets its chevron', A.querySelector('.rax-chev').innerHTML === '▶');
click(B);
ok('clicking the open row closes it', pB.hidden);
ok('aria resets on self-close', B.getAttribute('aria-expanded') === 'false');
key(A, 'Enter');
ok('Enter opens from the keyboard', !pA.hidden);
key(A, ' ');
ok('Space closes it', pA.hidden);
// [hidden]{display:none!important} is in the page reset; an inline style would
// be overridden by it and the panel would never hide.
ok('toggled by hidden, never inline style', pA.getAttribute('style') === null);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
