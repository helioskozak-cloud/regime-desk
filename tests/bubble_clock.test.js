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
  ok('the marker board renders', /How close is each marker, and how fast is it moving\?/.test(text()));
  ok('the timeline card renders, first after the header', /Is the timeline running like the dot-com one\?/.test(text()) && text().indexOf('Is the timeline running') < text().indexOf('How close is each marker'));
  ok('five board rows, each with its history inside', win.document.querySelectorAll('#v-bubble details.bb-row').length === 5);
  ok('all five markers sit on one shared timeline, with the dot-com top marked', /All five on one timeline/.test(text()) && /dot-com top \(Mar 2000\) on this alignment/.test(text()));
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
  ok('halvers over doublers shows the flip as printed', /Flipped: halvers ahead/.test(text()));
  // PACE: a narrowness gap widening week by week reads as moving toward its
  // trigger with a time; the same path reversed reads as backing away.
  const wk = i => new Date(Date.UTC(2026, 6, 6) + i * 7 * 864e5).toISOString().slice(0, 10);
  const mk = (i, gap) => ({ date: wk(i), from: wk(i - 52), n: 500, pct_doubled: 3, pct_halved: 1,
                            median_ret: 10 - gap, sp500_ret: 10 });
  latest.ttm_path = Array.from({ length: 14 }, (_, i) => mk(i, 6 + i * 0.3));
  latest.ttm = latest.ttm_path[13];
  await rerender();
  const row4 = () => [...win.document.querySelectorAll('#v-bubble details.bb-row')][3].textContent.replace(/\s+/g, ' ');
  ok('a widening gap reads "moving forward" with a time to light', /moving forward/.test(row4()) && /lights in ~\d+ months? at this pace/.test(row4()), row4().slice(0, 300));
  latest.ttm_path = Array.from({ length: 14 }, (_, i) => mk(i, 12 - i * 0.3));
  latest.ttm = latest.ttm_path[13];
  await rerender();
  ok('a narrowing gap reads "backing away"', /backing away/.test(row4()) && /not heading for lights/.test(row4()), row4().slice(0, 300));
  latest.ttm = saved; latest.ttm_path = savedPath;

  ok('no page errors', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '));
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
