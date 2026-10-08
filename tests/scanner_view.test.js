/* The page reads the scanner, not the analog edge (owner, 2026-10-08).

   The analog stock edge lost to random picks once beta was removed
   (scan/validate.py), so every live place that described a stock was moved to
   the scanner: the Filings/Earnings dot (earnings_view.test.js), the ticker
   hover card, and the Methods description. This pins the last two.

   Needs jsdom, like the other *.test.js here:  node tests/scanner_view.test.js */
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const html = fs.readFileSync(path.resolve(__dirname, '..', 'docs', 'index.html'), 'utf8');
let pass = 0, fail = 0;
const ok = (cond, label, extra) => {
  if (cond) { pass++; console.log('  ok   ' + label); }
  else { fail++; console.log('  FAIL ' + label + (extra ? '  -> ' + extra : '')); }
};
const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => errors.push(e.message));
const dom = new JSDOM(html, { runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'https://regime-desk.test/#analysis', virtualConsole: vc });
const w = dom.window;
w.fetch = () => Promise.reject(new Error('offline in test'));
const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');

setTimeout(() => {
  const d = w.document, S = w.SNAPSHOT;
  const rows = S.scanner.csv.split('\n').slice(1).map((l) => l.split(','));

  console.log('\n== Methods describes the scanner ==');
  const m = d.getElementById('v-analysis');
  const mt = text(m);
  ok(/Stock ranking — the scanner/.test(mt), 'Methods has the scanner card');
  ok(!/the analog engine/.test(mt), 'and no longer presents the analog engine as the stock method');
  const card = [...m.querySelectorAll('.card')].find((c) => /the scanner/.test(text(c.querySelector('h2'))));
  const trs = card ? [...card.querySelectorAll('table tr')].slice(1) : [];
  ok(trs.length === (S.scanner_test || []).length && trs.length === 3, 'one test row per horizon', trs.length);
  const r60 = (S.scanner_test || []).find((r) => r.horizon === 60);
  ok(r60 && trs[1] && text(trs[1]).includes('+' + (r60.scanner_vs_matched * 100).toFixed(1) + '%'),
    'the 60-session number is the one in the result file', trs[1] && text(trs[1]));
  ok(/A backtest, not a track record/.test(mt), 'says it is a backtest');

  console.log('\n== hovering a ticker shows its scanner reading ==');
  const tip = () => d.getElementById('rd-tip');
  const hover = (tk) => {
    const el = d.createElement('span'); el.dataset.ticker = tk; el.textContent = tk;
    d.body.appendChild(el);
    el.dispatchEvent(new w.MouseEvent('mouseover', { bubbles: true, clientX: 10, clientY: 10 }));
    const out = tip().style.display === 'block' ? text(tip()) : '';
    el.remove(); return out;
  };
  const top = rows[0];
  const t1 = hover(top[1]);
  ok(/Scanner/.test(t1) && t1.includes(`${top[0]} of ${S.scanner.n.toLocaleString()}`),
    `${top[1]} shows rank ${top[0]} of ${S.scanner.n}`, t1.slice(0, 160));
  ok(!/Edge|Hits/.test(t1), 'and no analog Edge or Hits', t1.slice(0, 160));
  ok(/3m vs SPY/.test(t1) && /vs 200d/.test(t1) && /Off 1y high/.test(t1), 'with three of the readings');
  ok(hover('ZZZNOTATICKER') === '', 'a name the scanner did not rank shows no card');

  console.log('\n== console errors ==');
  ok(errors.length === 0, 'no page errors (' + errors.join('; ') + ')');
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
}, 1500);
