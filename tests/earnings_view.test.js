/* The Earnings view of the Filings tab (2026-10-07, owner Q35 = b), driven in
   jsdom against the REAL docs/index.html. Like news_dom.test.js, the
   assertions are about what happens after a click: a toggle that renders and
   does nothing is the failure this guards.

       node tests/earnings_view.test.js
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
  runScripts: 'dangerously',
  url: 'https://helioskozak-cloud.github.io/regime-desk/',
  pretendToBeVisual: true,
  virtualConsole: vc,
  beforeParse(win) {
    win.fetch = () => Promise.resolve({ ok: false, status: 503, json: () => Promise.reject(new Error('offline')) });
  },
});
const win = dom.window;
const doc = win.document;
const $ = s => doc.querySelector(s);
const $$ = s => Array.from(doc.querySelectorAll(s));
const tick = (ms = 40) => new Promise(r => setTimeout(r, ms));
const click = el => el.dispatchEvent(new win.MouseEvent('click', { bubbles: true, cancelable: true }));
const view = () => $('#v-filings');

(async () => {
  await tick(10);
  win.location.hash = '#filings';
  win.dispatchEvent(new win.HashChangeEvent('hashchange'));
  await tick(80);

  const E = win.SNAPSHOT.earnings || {};
  console.log('\nToggle:');
  ok('the snapshot carries an earnings calendar', (E.earnings || []).length > 0 && (E.days_read || []).length > 0);
  ok('Filings tab opens on Filings', /SEC filings/.test(view().textContent));
  const tEarn = $('#v-filings [data-fil-view="earnings"]');
  ok('an Earnings toggle is at the top', !!tEarn);
  click(tEarn);
  ok('clicking Earnings shows the calendar', /Earnings — the scan universe/.test(view().textContent));
  ok('…and the filings table is gone', !/SEC filings/.test(view().textContent));

  console.log('\nCalendar:');
  ok('ten weekday blocks, this week and next', $$('#v-filings [data-earn-day]').length === 10,
     $$('#v-filings [data-earn-day]').length);
  const days = $$('#v-filings [data-earn-day]').map(d => d.dataset.earnDay);
  ok('blocks start on the file\'s Monday and end on its Friday', days[0] === E.start && days[9] === E.end, days.join(','));
  const first = E.earnings[0];
  const block = $(`#v-filings [data-earn-day="${first.date}"]`);
  ok(`${first.ticker} sits under its own day`, block && block.textContent.includes(first.ticker));
  const sig = new Set([...(win.SNAPSHOT.all_signals || []), ...(win.SNAPSHOT.stocks || [])].map(s => s && s.ticker));
  const dotted = E.earnings.find(r => sig.has(r.ticker));
  if (dotted) {
    const row = $$(`#v-filings [data-earn-day="${dotted.date}"] tr`).find(tr => tr.textContent.includes(dotted.ticker));
    ok(`${dotted.ticker} (on the signal list) carries the blue dot`, row && /signal list/.test(row.innerHTML));
  }

  console.log('\nFilters carry across the toggle:');
  const q = $('#v-filings [data-fil-q]');
  q.value = first.ticker;
  q.dispatchEvent(new win.Event('input', { bubbles: true }));
  await tick();
  const shown = $$('#v-filings [data-earn-day] tr').map(tr => tr.textContent);
  ok(`search "${first.ticker}" narrows the calendar`, shown.length >= 1 && shown.every(t => t.includes(first.ticker)), shown.length);
  ok('the view stays on Earnings after a filter', /Earnings — the scan universe/.test(view().textContent));
  q.value = '';
  q.dispatchEvent(new win.Event('input', { bubbles: true }));
  await tick();

  console.log('\nA day that failed says so:');
  const keep = E.days_failed;
  E.days_failed = [E.end];
  click($('#v-filings [data-fil-view="earnings"]'));
  ok('a failed day is marked "not refreshed"', /not refreshed/.test($(`#v-filings [data-earn-day="${E.end}"]`).textContent));
  E.days_failed = keep;

  console.log('\nBack:');
  click($('#v-filings [data-fil-view="filings"]'));
  ok('clicking Filings brings the filings table back', /SEC filings/.test(view().textContent));

  console.log('\nNo file:');
  const saved = win.SNAPSHOT.earnings;
  win.SNAPSHOT.earnings = {};
  click($('#v-filings [data-fil-view="earnings"]'));
  ok('no calendar reads as "not read", never as "nobody reports"', /not read/.test(view().textContent));
  win.SNAPSHOT.earnings = saved;

  ok('no page errors', pageErrors.length === 0, pageErrors.slice(0, 3).join(' | '));
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
