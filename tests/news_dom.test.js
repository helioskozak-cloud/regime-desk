/* Drives the REAL docs/index.html in jsdom with fetch stubbed, then clicks
   things. The 07-30 bug was controls that rendered perfectly and did nothing,
   so every assertion here is about what happens AFTER an event, not about
   what the markup looks like. */
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

// ── fetch stub ───────────────────────────────────────────────────────────────
let feedMode = 'ok';
const fetchLog = [];
let FIXTURE = null;

function buildFixture(win) {
  // Real tickers out of the page's own SNAPSHOT, plus deliberately uncovered ones.
  const snap = win.SNAPSHOT;
  const px = {};
  (snap.all_signals || []).concat(snap.stocks || []).forEach(s => {
    if (s && typeof s.price === 'number') px[s.ticker] = s;
  });
  const covered = Object.keys(px);
  const up = covered.find(t => px[t].change_pct > 0.02);
  const down = covered.find(t => px[t].change_pct < -0.02);
  const now = new Date();
  const iso = m => new Date(now.getTime() - m * 60000).toISOString();
  return {
    covUp: up, covDown: down, pxMap: px,
    doc: {
      generated: iso(2),
      ticker_names: { [up]: 'Covered Up Co' },
      headlines: [
        { title: 'Covered mover beats on earnings', link: 'https://example.com/a', source: 'Reuters',
          published: iso(5), tickers: [up, 'ZZZZ'], type: 'earnings', sentiment: 'positive',
          summary: 'A summary that should render inline under the headline.' },
        { title: 'Uncovered name announces offering', link: 'https://example.com/b', source: 'PR Newswire',
          published: iso(40), tickers: ['ZZZZ'], type: 'offering', sentiment: 'neutral', summary: '' },
        { title: 'Covered laggard cut to sell', link: 'https://example.com/c', source: 'Reuters',
          published: iso(400), tickers: [down], type: 'downgrade', sentiment: 'negative',
          summary: 'Downgrade note.' },
        { title: 'Untagged macro story', link: 'https://example.com/d', source: 'Fed',
          published: iso(10), tickers: [], type: 'macro', sentiment: 'neutral', summary: '' },
      ],
    },
    stocks: { stocks: { [up]: { name: 'Covered Up Co', price: 1, change_pct: 1 } } },
  };
}

const vc = new VirtualConsole();
const pageErrors = [];
vc.on('jsdomError', e => pageErrors.push(String(e.message || e)));
vc.on('error', (...a) => pageErrors.push('console.error: ' + a.join(' ')));

const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  url: 'https://helioskozak-cloud.github.io/regime-desk/',
  pretendToBeVisual: true,
  virtualConsole: vc,
  beforeParse(win) {
    win.fetch = (url) => {
      fetchLog.push(url);
      if (!FIXTURE) FIXTURE = buildFixture(win);
      if (feedMode === 'down') return Promise.resolve({ ok: false, status: 503, json: () => Promise.reject(new Error('no')) });
      if (feedMode === 'throw') return Promise.reject(new Error('network'));
      const body = /headlines\.json/.test(url) ? FIXTURE.doc : FIXTURE.stocks;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    };
  },
});

const win = dom.window;
const doc = win.document;
const $ = s => doc.querySelector(s);
const $$ = s => Array.from(doc.querySelectorAll(s));
const tick = (ms = 30) => new Promise(r => setTimeout(r, ms));
const click = (el, init) => el.dispatchEvent(new win.MouseEvent('click', Object.assign({ bubbles: true, cancelable: true }, init)));
const rows = () => $$('#v-news .nd-row');
// The "clear book" button only exists when a book is loaded, so resetting has
// to cope with both states.
const resetBook = async () => {
  const b = $('#v-news [data-act="bookclear"]');
  if (b) click(b);
  else { win.NEWSTAB.state.book = []; win.NEWSTAB.state.bookMsg = null; win.NEWSTAB.render(); }
  await tick(10);
};

(async () => {
  await tick(80);
  console.log('\n== page loaded ==');
  ok('page script ran (SNAPSHOT present)', !!win.SNAPSHOT);
  ok('no jsdom page errors on load', pageErrors.length === 0, pageErrors.join(' | '));

  // ── open the News view the way a user does ────────────────────────────────
  win.location.hash = '#news';
  win.dispatchEvent(new win.HashChangeEvent('hashchange'));
  await tick(80);

  console.log('\n== initial render ==');
  ok('#v-news is active', $('#v-news').classList.contains('active'));
  ok('feed container exists', !!$('#nd-feed'));
  ok('fetched headlines.json', fetchLog.some(u => /headlines\.json/.test(u)), fetchLog.join(','));
  ok('fetched stocks.json', fetchLog.some(u => /stocks\.json/.test(u)));
  ok('all fetches are news-desk data URLs',
    fetchLog.every(u => u.startsWith('https://helioskozak-cloud.github.io/news-desk/data/')), fetchLog.join(','));

  eq('3 ticker-tagged rows render (untagged dropped)', rows().length, 3);
  eq('NEWS count = ticker-tagged total', $('#nd-n-news').textContent, '3');
  ok('counts label shows n / total', /3 \/ 3 shown/.test($('#nd-counts').textContent), $('#nd-counts').textContent);

  console.log('\n== no inline handlers anywhere in the view ==');
  const inlineAttrs = [];
  $$('#v-news *').forEach(el => Array.from(el.attributes).forEach(a => {
    if (/^on/i.test(a.name)) inlineAttrs.push(el.tagName + '@' + a.name);
  }));
  ok('zero inline on* attributes in #v-news', inlineAttrs.length === 0, inlineAttrs.join(','));

  console.log('\n== ticker coverage honesty ==');
  const up = FIXTURE.covUp, down = FIXTURE.covDown;
  const upRow = rows()[0];
  const upCell = upRow.querySelector('.nd-tks');
  eq('covered ticker symbol', upCell.querySelector('.nd-sym').textContent, up);
  const wantPx = '$' + FIXTURE.pxMap[up].price.toFixed(2);
  eq('covered ticker shows price inline (no hover)', upCell.querySelector('.nd-px').textContent, wantPx);
  const wantChg = '+' + (FIXTURE.pxMap[up].change_pct * 100).toFixed(2) + '%';
  eq('change_pct rendered *100 as one-session %', upCell.querySelector('.nd-chg').textContent, wantChg);
  ok('positive change is green #3fb950', /3fb950/.test(upCell.querySelector('.nd-chg').getAttribute('style')));
  ok('sanity: that is a percent, not a fraction printed raw',
    Math.abs(parseFloat(wantChg) - FIXTURE.pxMap[up].change_pct * 100) < 1e-9);

  const bare = rows()[1].querySelector('.nd-tks');
  eq('uncovered ticker renders bare symbol', bare.querySelector('.nd-sym').textContent, 'ZZZZ');
  ok('uncovered ticker has NO price element', !bare.querySelector('.nd-px'));
  ok('uncovered ticker has NO change element', !bare.querySelector('.nd-chg'));
  ok('uncovered ticker shows no 0.00 / dash', !/0\.00|—|--/.test(bare.textContent), bare.textContent);

  const downCell = rows()[2].querySelector('.nd-tks');
  ok('negative change is red #f85149', /f85149/.test(downCell.querySelector('.nd-chg').getAttribute('style')));
  eq('negative change value', downCell.querySelector('.nd-chg').textContent,
    (FIXTURE.pxMap[down].change_pct * 100).toFixed(2) + '%');

  ok('symbols carry data-ticker for the page-wide tooltip', !!upCell.querySelector('[data-ticker]'));
  ok('secondary tickers rendered', !!upRow.querySelector('.nd-more span'));

  console.log('\n== search box actually filters ==');
  const q = $('#nd-q');
  q.value = 'offering';
  q.dispatchEvent(new win.Event('input', { bubbles: true }));
  await tick(10);
  eq('search narrows to 1 row', rows().length, 1);
  ok('the surviving row is the right one', /offering/i.test(rows()[0].textContent));
  q.value = 'nothingmatchesthis';
  q.dispatchEvent(new win.Event('input', { bubbles: true }));
  await tick(10);
  eq('no-match shows empty state, not a blank card', rows().length, 0);
  ok('empty state is explained', /nothing matches/i.test($('#nd-feed').textContent));
  q.value = '';
  q.dispatchEvent(new win.Event('input', { bubbles: true }));
  await tick(10);
  eq('clearing search restores all rows', rows().length, 3);

  console.log('\n== source filter actually filters ==');
  const src = $('#nd-src');
  eq('source options built from feed', src.options.length, 4); // All + Fed + PR Newswire + Reuters
  src.value = 'Reuters';
  src.dispatchEvent(new win.Event('change', { bubbles: true }));
  await tick(10);
  eq('source=Reuters leaves 2 rows', rows().length, 2);

  console.log('\n== type filter actually filters ==');
  const typ = $('#nd-typ');
  typ.value = 'downgrade';
  typ.dispatchEvent(new win.Event('change', { bubbles: true }));
  await tick(10);
  eq('source+type combine to 1 row', rows().length, 1);
  ok('it is the downgrade', /cut to sell/i.test(rows()[0].textContent));

  console.log('\n== CLEAR actually clears ==');
  click($('#v-news [data-act="clr"]'));
  await tick(10);
  eq('clear restores all rows', rows().length, 3);
  eq('clear resets search input', $('#nd-q').value, '');
  eq('clear resets source select', $('#nd-src').value, '');
  eq('clear resets type select', $('#nd-typ').value, '');

  console.log('\n== ticker click filters the feed ==');
  click(rows()[1].querySelector('.nd-sym'));
  await tick(10);
  eq('clicking ZZZZ filters to its stories', rows().length, 2);
  ok('an active-filter chip appears', /ZZZZ/.test($('#nd-chips').textContent));
  click($('#v-news [data-act="unpick"]'));
  await tick(10);
  eq('chip clears the ticker filter', rows().length, 3);
  eq('chip row is empty again', $('#nd-chips').textContent.trim(), '');

  console.log('\n== shift-click is left to the page-wide handler ==');
  const before = rows().length;
  win.open = () => {};
  click(rows()[1].querySelector('.nd-sym'), { shiftKey: true });
  await tick(10);
  eq('shift-click does not hijack into a feed filter', rows().length, before);

  console.log('\n== row expand ==');
  const r0 = rows()[0];
  ok('summary is present inline', !!r0.querySelector('.nd-sum'));
  click(r0.querySelector('.nd-sum'));
  await tick(5);
  ok('row toggles open on click', rows()[0].classList.contains('open'));
  await win.NEWSTAB.load(); await tick(20);
  ok('expansion survives the 60s re-render', rows()[0].classList.contains('open'));
  click(rows()[0].querySelector('.nd-sum'));
  await tick(5);
  ok('clicking again collapses', !rows()[0].classList.contains('open'));

  console.log('\n== MY BOOK ==');
  win.localStorage.clear();
  win.NEWSTAB.state.book = []; win.NEWSTAB.state.bookLabel = null; win.NEWSTAB.state.bookSeeded = false;
  click($('#v-news [data-act="tab"][data-tab="book"]'));
  await tick(10);
  ok('empty book shows the upload panel', !!$('#nd-drop'), $('#nd-feed').textContent.slice(0, 80));
  ok('panel offers both .xlsx and .csv', /\.xlsx/.test($('#nd-drop').textContent) && /\.csv/.test($('#nd-drop').textContent));
  eq('file input accepts xlsx and csv', $('#nd-file').getAttribute('accept'), '.xlsx,.xls,.csv');

  $('#nd-paste').value = `${up}, ZZZZ  notaticker!!!`;
  click($('#v-news [data-act="paste"]'));
  await tick(10);
  eq('paste loads a book', win.NEWSTAB.state.book.join(','), [up, 'ZZZZ'].sort().join(','));
  // book = {covered-up, ZZZZ}; headline 3 (the downgrade) is not in the book.
  eq('book view filters to book names', rows().length, 2);
  ok('book header reports the count', /2 tickers/.test($('#v-news .nd-bookhead').textContent));
  eq('MY BOOK tab count is live', $('#nd-n-book').textContent, '2');

  $('#nd-q').value = 'earnings';
  $('#nd-q').dispatchEvent(new win.Event('input', { bubbles: true }));
  await tick(10);
  eq('search still works inside MY BOOK', rows().length, 1);
  click($('#v-news [data-act="clr"]'));
  await tick(10);

  click($('#v-news [data-act="tab"][data-tab="news"]'));
  await tick(10);
  eq('switching back to NEWS restores the full feed', rows().length, 3);
  ok('NEWS tab is marked active', $('#v-news [data-tab="news"]').classList.contains('on'));

  console.log('\n== .csv upload ==');
  click($('#v-news [data-act="tab"][data-tab="book"]'));
  await tick(10);
  click($('#v-news [data-act="bookclear"]'));
  await tick(10);
  ok('clear book returns to the upload panel', !!$('#nd-file'));

  const csv = 'Account,Description,Symbol / CUSIP / ID,Quantity,Value\n' +
              'X1,Apple Inc,AAPL,10,100\n' +
              'X1,Cash,CASH,1,1\n' +
              'X1,Nvidia,NVDA,5,50\n' +
              'X1,Weird,NOT A TICKER,1,1\n';
  const csvFile = new win.File([csv], 'holdings.csv', { type: 'text/csv' });
  const inp = $('#nd-file');
  Object.defineProperty(inp, 'files', { value: [csvFile], configurable: true });
  inp.dispatchEvent(new win.Event('change', { bubbles: true }));
  await tick(120);
  eq('CSV populates the book', win.NEWSTAB.state.book.join(','), 'AAPL,NVDA');
  ok('CSV skips cash-like rows', !win.NEWSTAB.state.book.includes('CASH'));
  ok('CSV result message names the column', /Symbol \/ CUSIP \/ ID/.test($('#v-news').textContent) ||
     /2 tickers/.test($('#v-news .nd-bookhead').textContent), $('#v-news .nd-bookhead').textContent);

  console.log('\n== .xlsx upload (vendored SheetJS, same-origin, lazy) ==');
  ok('SheetJS is NOT loaded until a spreadsheet is dropped', typeof win.XLSX === 'undefined');
  await resetBook();
  const fakeXlsx = new win.File([new Uint8Array([1, 2, 3])], 'book.xlsx');
  const inp2 = $('#nd-file');
  Object.defineProperty(inp2, 'files', { value: [fakeXlsx], configurable: true });
  inp2.dispatchEvent(new win.Event('change', { bubbles: true }));
  await tick(30);
  const tag = Array.from(doc.head.querySelectorAll('script')).pop();
  ok('a script element was injected for SheetJS', !!tag && /xlsx/.test(tag.src || tag.getAttribute('src') || ''));
  eq('SheetJS src is relative / same-origin', tag.getAttribute('src'), 'vendor/xlsx.full.min.js');
  ok('SheetJS src is not a CDN', !/:\/\//.test(tag.getAttribute('src')));

  // Now actually run the vendored library and a real workbook through the path.
  const lib = fs.readFileSync(path.join(REPO, 'docs/vendor/xlsx.full.min.js'), 'utf8');
  win.eval(lib);
  ok('vendored SheetJS evaluates and defines XLSX', typeof win.XLSX !== 'undefined');
  const X = win.XLSX;
  const wsData = [['Account', 'Description', 'Symbol', 'Quantity', 'Value'],
                  ['X1', 'Microsoft', 'MSFT', 3, 30],
                  ['X1', 'Cash', 'SPAXX', 1, 1],
                  ['X1', 'Tesla', 'TSLA', 2, 20]];
  const wb = X.utils.book_new();
  X.utils.book_append_sheet(wb, X.utils.aoa_to_sheet(wsData), 'Sheet1');
  const buf = X.write(wb, { type: 'array', bookType: 'xlsx' });
  const realXlsx = new win.File([buf], 'Account-Investments-2026.xlsx');
  await resetBook();
  const inp3 = $('#nd-file');
  Object.defineProperty(inp3, 'files', { value: [realXlsx], configurable: true });
  inp3.dispatchEvent(new win.Event('change', { bubbles: true }));
  await tick(200);
  eq('.xlsx populates the book', win.NEWSTAB.state.book.join(','), 'MSFT,TSLA');
  ok('.xlsx skips cash-like rows', !win.NEWSTAB.state.book.includes('SPAXX'));

  console.log('\n== persistence + seeding ==');
  eq('uploaded book persisted to rd-news-book',
    JSON.parse(win.localStorage.getItem('rd-news-book')).tickers.join(','), 'MSFT,TSLA');
  win.localStorage.clear();
  win.localStorage.setItem('rd-watchlist', 'ADBE, DDOG ,TSLA');
  const S2 = win.NEWSTAB.state;
  S2.book = []; S2.bookLabel = null; S2.bookSeeded = false; S2.booted = false;
  // re-run the seeding path only
  win.eval('NEWSTAB.state.book=[];');
  const before2 = S2.book.length;
  win.NEWSTAB.boot(); // booted was reset; re-binds listeners but exercises loadBook
  await tick(30);
  eq('MY BOOK seeds from rd-watchlist, not the empty nd store', S2.book.join(','), 'ADBE,DDOG,TSLA');
  ok('seeded book is labelled as a seed', S2.bookSeeded === true && /watchlist/i.test(S2.bookLabel || ''));
  ok('a seed is not written back to storage', win.localStorage.getItem('rd-news-book') === null);

  console.log('\n== feed failure is loud, not blank ==');
  feedMode = 'down';
  const S3 = win.NEWSTAB.state;
  S3.headlines = []; S3.loaded = false;
  await win.NEWSTAB.load();
  await tick(30);
  click($('#v-news [data-act="tab"][data-tab="news"]'));
  await tick(10);
  ok('a failed feed says so', /unreachable/i.test($('#nd-feed').textContent), $('#nd-feed').textContent.slice(0, 120));
  ok('failure links to news-desk itself', /news-desk/.test($('#nd-feed').innerHTML));
  ok('live dot goes stale on failure', $('#nd-dot').className.includes('stale'));
  feedMode = 'ok';
  await win.NEWSTAB.load();
  await tick(30);
  eq('feed recovers on the next poll', rows().length, 3);
  ok('live dot is healthy again', !$('#nd-dot').className.includes('stale'));

  console.log('\n== isolation ==');
  const otherViews = ['v-home', 'v-stocks', 'v-econ'];
  ok('news markup stayed inside #v-news',
    otherViews.every(v => !doc.getElementById(v).querySelector('.nd-row')));
  ok('pop-out button still on the feed card (not clobbered by re-render)',
    !!$('#v-news .card .popout-btn'));

  console.log('\n== console errors during the whole run ==');
  const expected = /headlines\.json did not load/;   // the deliberate outage above
  ok('the deliberate outage DID log loudly', pageErrors.some(e => expected.test(e)));
  const real = pageErrors.filter(e =>
    !/Could not parse CSS|Not implemented|jsdom/i.test(e) && !expected.test(e));
  ok('no unexpected page errors', real.length === 0, real.slice(0, 4).join(' | '));

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('HARNESS ERROR', e); process.exit(2); });
