/* News tab prices from news-desk's quote file, the fallback (2026-09-21).

   The trap this pins: news-desk's change_pct is a PERCENT (2.31 = +2.31%),
   SNAPSHOT's is a FRACTION (0.0231). The tab must never read news-desk's
   change_pct; it derives the change from price and prev_close instead. The
   fixture below is the LIVE file's shape ({generated, stocks: [ {ticker, ...} ]}),
   with its change_pct deliberately set to a wrong value, so any code path that
   reads it shows up as a wrong percentage here.

   Run: node tests/news_quotes.test.js */
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const REPO = path.resolve(__dirname, '..');
const html = fs.readFileSync(path.join(REPO, 'docs/index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ok   ' + name); }
  else { fail++; console.log('  FAIL ' + name + (extra ? '  → ' + extra : '')); }
};
const eq = (name, got, want) => ok(name, got === want, `got ${JSON.stringify(got)} want ${JSON.stringify(want)}`);

let FIX = null;
function fixture(win) {
  const snap = win.SNAPSHOT;
  const covered = (snap.all_signals || []).concat(snap.stocks || [])
    .find(s => s && typeof s.price === 'number' && typeof s.change_pct === 'number');
  const now = new Date().toISOString();
  return {
    covered,
    doc: {
      generated: now,
      headlines: [
        { title: 'Priced by news-desk only', link: 'https://example.com/1', source: 'Reuters',
          published: now, tickers: ['NDONLY', 'NOPREV', 'ZZZZ'], type: 'news', sentiment: 'neutral', summary: '' },
        { title: 'Covered by the scan too', link: 'https://example.com/2', source: 'Reuters',
          published: now, tickers: [covered.ticker], type: 'news', sentiment: 'neutral', summary: '' },
        { title: 'No prev close', link: 'https://example.com/3', source: 'Reuters',
          published: now, tickers: ['NOPREV'], type: 'news', sentiment: 'neutral', summary: '' },
      ],
    },
    stocks: {
      generated: now,
      stocks: [
        // Real numbers from the live file (AAOI, 2026-09-21), change_pct POISONED:
        // the right answer is +2.31%; reading change_pct would show 99.00% or 9900.00%.
        { ticker: 'NDONLY', price: 107.6, prev_close: 105.17, change: 2.43, change_pct: 99 },
        { ticker: 'NOPREV', price: 10, change_pct: 5 },
        // The scan covers this one; news-desk's absurd price must NOT win.
        { ticker: covered.ticker, price: 1, prev_close: 0.5, change_pct: 100 },
        { ticker: 'BADPX', price: 'n/a', prev_close: 3 },
      ],
    },
  };
}

const vc = new VirtualConsole();
const errors = [];
vc.on('jsdomError', e => errors.push(String(e.message || e)));
const dom = new JSDOM(html, {
  runScripts: 'dangerously', url: 'https://helioskozak-cloud.github.io/regime-desk/',
  pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(win) {
    win.fetch = (url) => {
      if (!FIX) FIX = fixture(win);
      const body = /headlines\.json/.test(url) ? FIX.doc : FIX.stocks;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    };
  },
});
const win = dom.window, doc = win.document;
const tick = (ms = 30) => new Promise(r => setTimeout(r, ms));
const rows = () => Array.from(doc.querySelectorAll('#v-news .nd-row'));

(async () => {
  await tick(80);
  win.location.hash = '#news';
  win.dispatchEvent(new win.HashChangeEvent('hashchange'));
  await tick(120);

  const byTitle = t => rows().find(r => r.textContent.includes(t));
  const nd = byTitle('Priced by news-desk only').querySelector('.nd-tks');

  console.log('\n== a ticker only news-desk prices ==');
  eq('news-desk price shows inline', nd.querySelector('.nd-px').textContent, '$107.60');
  eq('change is derived from price / prev close, not change_pct',
    nd.querySelector('.nd-chg').textContent, '+2.31%');
  ok('the price says where it came from', /news-desk/.test(nd.querySelector('.nd-px').title));
  ok('secondary chip for a news-desk-only ticker shows nothing it cannot derive',
    !/NOPREV\s*[+-]/.test(nd.querySelector('.nd-more').textContent), nd.querySelector('.nd-more').textContent);
  ok('an unpriced secondary ticker stays bare',
    /ZZZZ/.test(nd.querySelector('.nd-more').textContent) && !/ZZZZ\s*[+-]/.test(nd.querySelector('.nd-more').textContent));

  console.log('\n== no prev close ==');
  const np = byTitle('No prev close').querySelector('.nd-tks');
  eq('price still shows', np.querySelector('.nd-px').textContent, '$10.00');
  ok('no change is invented', !np.querySelector('.nd-chg'));

  console.log('\n== the scan wins where it covers the ticker ==');
  const cv = byTitle('Covered by the scan too').querySelector('.nd-tks');
  const c = FIX.covered;
  eq('scan price, not news-desk\'s', cv.querySelector('.nd-px').textContent, '$' + c.price.toFixed(2));
  eq('scan change, as a fraction x100',
    cv.querySelector('.nd-chg').textContent, (c.change_pct >= 0 ? '+' : '') + (c.change_pct * 100).toFixed(2) + '%');
  ok('and it says it is from the scan', /daily scan/.test(cv.querySelector('.nd-px').title));

  console.log('\n== garbage in the quote file ==');
  ok('a non-numeric price is ignored, not rendered', !('BADPX' in win.NEWSTAB.state.nd));

  const real = errors.filter(e => !/Could not parse CSS|Not implemented/i.test(e));
  ok('no page errors', real.length === 0, real.slice(0, 3).join(' | '));
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('HARNESS ERROR', e); process.exit(2); });
