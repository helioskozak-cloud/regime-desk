/* Filings tab, 2026-10-13. Owner: "a little summary line of what the filing
   means in plain english" and "I thought we left the terminal typesets behind";
   plus "the status bar with calm uptrend ... not just the home/market tab where
   it belongs". Driven in jsdom against the REAL docs/index.html with a fixture
   filings file, so the assertions are about what a reader sees.

       node tests/filings_plain.test.js
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

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', e => errors.push(String(e.message || e)));
const dom = new JSDOM(html, {
  runScripts: 'dangerously', url: 'https://helioskozak-cloud.github.io/regime-desk/',
  pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(win) { win.fetch = () => Promise.resolve({ ok: false, status: 503, json: () => Promise.reject(new Error('offline')) }); },
});
const win = dom.window, doc = win.document;
const tick = (ms = 40) => new Promise(r => setTimeout(r, ms));

(async () => {
  await tick(80);
  const today = new Date().toISOString().slice(0, 10);
  win.SNAPSHOT.filings = { as_of: today, window_days: 7, universe: 3462, insiders: [], filings: [
    { ticker: 'AUD', name: 'Auditco', sector: 'Healthcare', date: today, form: '8-K', kind: '8-K', rank: 1,
      what: '4.01 auditor change; 2.03 new debt; 5.02 officer/director change', url: 'https://www.sec.gov/a' },
    { ticker: 'ACT', name: 'nan', sector: 'nan', date: today, form: 'SC 13D', kind: 'activist', rank: 2,
      what: '13D activist stake', url: 'https://www.sec.gov/b' },
    { ticker: 'LATE', name: 'Lateco', sector: 'Energy', date: today, form: 'NT 10-K', kind: 'late', rank: 0,
      what: 'Late 10-K filing', url: 'https://www.sec.gov/c' },
  ] };
  win.location.hash = '#filings';
  win.dispatchEvent(new win.HashChangeEvent('hashchange'));
  await tick(80);

  const rows = Array.from(doc.querySelectorAll('#v-filings tr.fl-row'));
  const row = t => rows.find(r => r.querySelector('.fl-tk') && r.querySelector('.fl-tk').textContent.startsWith(t));
  console.log('\n== plain English ==');
  const aud = row('AUD');
  ok('the most material item leads, in plain words', /changed its outside auditor/.test(aud.textContent), aud.textContent);
  ok('the other items follow after "Also:"', /Also: new debt, leadership or pay change\./.test(aud.textContent));
  ok('no item codes in the line itself', !/4\.01|2\.03|5\.02/.test(aud.querySelector('.fl-what').textContent + aud.querySelector('.fl-also').textContent));
  ok('the codes are still one hover away on the link', /4\.01 auditor change/.test(aud.querySelector('.fl-link').getAttribute('title')));
  ok('a 13D says what an activist stake is', /owns 5% or more/.test(row('ACT').textContent));
  ok('a late filing says the report will be late', /annual report will be late/.test(row('LATE').textContent));
  ok('"nan" never shows as a company or sector', !/\bnan\b/.test(row('ACT').textContent), row('ACT').textContent);

  console.log('\n== type ==');
  ok('company names are not set in the mono face', /#v-filings \.fl-co\{font-size:13px/.test(html) && !/#v-filings \.fl-co\{[^}]*--mono/.test(html));
  ok('the heading is sentence case, not terminal caps', /#v-filings \.card h2\{font-family:var\(--sans\)[^}]*text-transform:none/.test(html));
  ok('the filings table reads in the sans face', /#v-filings table\{font-family:var\(--sans\)/.test(html));

  console.log('\n== the regime banner belongs to Home ==');
  ok('Filings is not Home', doc.body.dataset.view === 'filings');
  ok('no regime banner (removed 2026-10-14)', !doc.getElementById('regime-banner'));
  win.location.hash = '#home'; win.dispatchEvent(new win.HashChangeEvent('hashchange')); await tick(40);
  ok('and Home marks itself', doc.body.dataset.view === 'home');

  const real = errors.filter(e => !/Could not parse CSS|Not implemented/i.test(e));
  ok('no page errors', real.length === 0, real.slice(0, 3).join(' | '));
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('HARNESS ERROR', e); process.exit(2); });
