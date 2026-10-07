/* The Bubble tab's dot-com clock (owner, 2026-10-07: "what point in the
   dot-com bubble does this signal look like … and is the overall timeline
   similar"). Driven in jsdom against the REAL docs/index.html: a "now" reading
   set equal to a dot-com year must read as that year, so the clock cannot
   drift from the bars it is read against.

       node tests/bubble_clock.test.js
*/
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const REPO = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(REPO, 'docs/index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ok   ' + name); }
  else { fail++; console.log('  FAIL ' + name + (extra ? '  -> ' + extra : '')); }
};
const pageErrors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => pageErrors.push(String(e.message || e)));
const dom = new JSDOM(html, {
  runScripts: 'dangerously', url: 'https://helioskozak-cloud.github.io/regime-desk/',
  pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(win) { win.fetch = () => Promise.resolve({ ok: false, status: 503, json: () => Promise.reject(new Error('offline')) }); },
});
const win = dom.window;
const tick = (ms = 60) => new Promise(r => setTimeout(r, ms));
const text = () => win.document.querySelector('#v-bubble').textContent.replace(/\s+/g, ' ');
// Views render once (route() marks them data-rendered); clear the mark to redraw.
const rerender = async () => { delete win.document.getElementById('v-bubble').dataset.rendered;
  win.location.hash = '#home'; win.dispatchEvent(new win.HashChangeEvent('hashchange')); await tick();
  win.location.hash = '#bubble'; win.dispatchEvent(new win.HashChangeEvent('hashchange')); await tick(); };

(async () => {
  await tick(10);
  await rerender();
  const years = win.SNAPSHOT.bubble_watch.years;
  const latest = years[years.length - 1];
  const y98 = years.find(y => y.year === 1998), y99 = years.find(y => y.year === 1999);

  console.log('\nOn the real snapshot:');
  ok('the clock card renders', /Where this sits on the dot-com clock/.test(text()));
  ok('the timeline card renders', /Is the timeline running like the dot-com one\?/.test(text()));
  ok('every marker chart carries a "now" line note', (text().match(/Dotted line = now/g) || []).length === 5,
     (text().match(/Dotted line = now/g) || []).length);
  ok('the reading is the trailing 12 months when the scan wrote one',
     !latest.ttm || text().includes('12 months to ' + latest.ttm.date.slice(5).replace('-', '/')));

  console.log('\nA "now" equal to a dot-com year reads as that year:');
  const saved = latest.ttm, savedPath = latest.ttm_path;
  const pick = r => ({ date: '2026-10-06', from: '2025-10-06', n: 500, pct_doubled: r.pct_doubled,
                       pct_halved: r.pct_halved, median_ret: r.median_ret, sp500_ret: r.sp500_ret });
  latest.ttm = pick(y98); latest.ttm_path = [latest.ttm];
  await rerender();
  ok('1998\'s readings read "≈ 1998"', /Now: ≈ 1998\./.test(text()), text().match(/Now: [^.]*\./));
  latest.ttm = Object.assign(pick(y99), { pct_doubled: y99.pct_doubled + 1, pct_halved: y99.pct_halved + 1,
                                           median_ret: y99.median_ret - 5 });
  latest.ttm_path = [latest.ttm];
  await rerender();
  ok('readings above 1999 read "at or past 1999"', /Now: at or past 1999\./.test(text()), text().match(/Now: [^.]*\./));
  latest.ttm = Object.assign(pick(y99), { pct_doubled: 1, pct_halved: 6 });
  latest.ttm_path = [latest.ttm];
  await rerender();
  ok('halvers over doublers shows the flip as printed', /5 · flip LIT/.test(text()));
  latest.ttm = saved; latest.ttm_path = savedPath;

  ok('no page errors', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '));
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
