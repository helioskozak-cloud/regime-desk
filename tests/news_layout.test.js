/* Acceptance #1: no horizontal scrollbar at 1366px or 2560px.
   jsdom has no layout engine, so this drives real Chromium against the real
   page, with the news-desk fetches intercepted so rows actually exist. */
const fs = require('fs');
const http = require('http');
const path = require('path');
const { chromium } = require('playwright');

const REPO = path.resolve(__dirname, '..');
const OUT = process.env.NEWS_SHOTS || require('os').tmpdir();  // where screenshots land
const DOCS = path.join(REPO, 'docs');

// Build a stressful fixture from the page's own SNAPSHOT tickers.
const html = fs.readFileSync(path.join(DOCS, 'index.html'), 'utf8');
const i = html.indexOf('window.SNAPSHOT = ');
const snap = JSON.parse(html.slice(i + 'window.SNAPSHOT = '.length, html.indexOf('\n</script>', i)).trim().replace(/;$/, ''));
const covered = (snap.all_signals || []).filter(s => typeof s.price === 'number').map(s => s.ticker);

const LONG = 'Supercalifragilisticexpialidocious-Pharmaceuticals-International-Holdings announces a definitive agreement';
const now = Date.now();
const iso = m => new Date(now - m * 60000).toISOString();
const SOURCES = ['Reuters', 'PR Newswire', 'Business Wire', 'GlobeNewswire', 'SEC EDGAR'];
const TYPES = ['earnings', 'upgrade', 'downgrade', 'analyst', 'offering', 'macro', 'filings'];
const headlines = [];
for (let n = 0; n < 60; n++) {
  // Every 4th story leads with a ticker SNAPSHOT has no price for, so the
  // bare-symbol path is exercised in the primary cell, not just the chips.
  const tks = n % 4 === 3 ? ['ZZZZ'] : [covered[n % covered.length]];
  if (n % 3 === 0) tks.push('ZZZZ', 'QQQQ9', covered[(n + 7) % covered.length]);
  headlines.push({
    title: n % 5 === 0 ? LONG : `Headline number ${n} about ${tks[0]} and what it might mean for the sector`,
    link: 'https://example.com/' + n,
    source: SOURCES[n % SOURCES.length],
    published: iso(n * 25),
    tickers: tks,
    type: TYPES[n % TYPES.length],
    sentiment: ['positive', 'negative', 'neutral'][n % 3],
    summary: n % 2 ? 'A reasonably long summary sentence that should clamp to two lines and expand when the row is clicked, repeated to make it long enough to actually wrap on a wide screen as well as a narrow one.' : '',
  });
}
const FEED = JSON.stringify({ generated: iso(2), ticker_names: {}, headlines });

const server = http.createServer((req, res) => {
  const f = path.join(DOCS, decodeURIComponent(req.url.split('?')[0]) === '/' ? 'index.html' : decodeURIComponent(req.url.split('?')[0]));
  if (!f.startsWith(DOCS) || !fs.existsSync(f)) { res.writeHead(404); res.end('no'); return; }
  res.writeHead(200, { 'Content-Type': f.endsWith('.js') ? 'application/javascript' : 'text/html; charset=utf-8' });
  res.end(fs.readFileSync(f));
});

let pass = 0, fail = 0;
const ok = (n, c, x) => { if (c) { pass++; console.log('  ok   ' + n); } else { fail++; console.log('  FAIL ' + n + (x ? '  → ' + x : '')); } };

(async () => {
  await new Promise(r => server.listen(8765, '127.0.0.1', r));
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });

  for (const [w, h, label] of [[1366, 900, '1366 (laptop)'], [2560, 1440, '2560 (wide)'], [1180, 800, '1180 (breakpoint)'], [820, 900, '820 (tablet)'], [390, 844, '390 (phone)']]) {
    const page = await browser.newPage({ viewport: { width: w, height: h } });
    await page.route('**/news-desk/data/headlines.json*', r => r.fulfill({ status: 200, contentType: 'application/json', body: FEED }));
    await page.route('**/news-desk/data/stocks.json*', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{"stocks":{}}' }));
    await page.route('**://fonts.googleapis.com/**', r => r.abort());
    await page.route('**://fonts.gstatic.com/**', r => r.abort());
    await page.route('**://assets.parqet.com/**', r => r.abort());
    const errs = [];
    page.on('pageerror', e => errs.push(String(e)));
    await page.goto('http://127.0.0.1:8765/index.html#news', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#v-news .nd-row', { timeout: 15000 });

    console.log(`\n== ${label} ==`);
    const m = await page.evaluate(() => ({
      docScroll: document.documentElement.scrollWidth,
      docClient: document.documentElement.clientWidth,
      bodyScroll: document.body.scrollWidth,
      rows: document.querySelectorAll('#v-news .nd-row').length,
      widest: Math.max(...Array.from(document.querySelectorAll('#v-news .nd-row')).map(r => r.getBoundingClientRect().right)),
      cardLeft: document.querySelector('#v-news .card').getBoundingClientRect().left,
      otherCardLeft: (document.querySelector('#v-econ .card') || document.querySelector('#v-home .card') || {}).getBoundingClientRect
        ? null : null,
      priced: document.querySelectorAll('#v-news .nd-px').length,
      bare: Array.from(document.querySelectorAll('#v-news .nd-tk')).filter(t => !t.querySelector('.nd-px')).length,
      overflowing: Array.from(document.querySelectorAll('#v-news *'))
        .filter(e => e.getBoundingClientRect().right > document.documentElement.clientWidth + 1)
        .slice(0, 5).map(e => e.className + ' @' + Math.round(e.getBoundingClientRect().right)),
    }));
    ok(`rows rendered (${m.rows})`, m.rows > 0);
    ok('no horizontal document scroll', m.docScroll <= m.docClient, `scrollWidth ${m.docScroll} > clientWidth ${m.docClient}`);
    ok('no element escapes the viewport', m.overflowing.length === 0, m.overflowing.join(' | '));
    ok(`priced tickers shown inline (${m.priced}) and bare ones bare (${m.bare})`, m.priced > 0 && m.bare > 0);
    ok('no page errors', errs.length === 0, errs.slice(0, 2).join(' | '));

    // alignment with the rest of the dashboard
    const home = await page.evaluate(() => {
      location.hash = '#home';
      window.dispatchEvent(new HashChangeEvent('hashchange'));
      const c = document.querySelector('#v-home .card');
      return c ? c.getBoundingClientRect().left : null;
    });
    ok('news card sits on the same column as Home', home === null || Math.abs(home - m.cardLeft) < 1,
      `news ${m.cardLeft} vs home ${home}`);

    await page.goto('http://127.0.0.1:8765/index.html#news', { waitUntil: 'domcontentloaded' });
    await page.waitForSelector('#v-news .nd-row');
    await page.screenshot({ path: `${OUT}/news-${w}.png`, fullPage: false });
    await page.close();
  }

  // One real interaction in a real browser, as a cross-check on jsdom.
  const page = await browser.newPage({ viewport: { width: 1366, height: 900 } });
  await page.route('**/news-desk/data/headlines.json*', r => r.fulfill({ status: 200, contentType: 'application/json', body: FEED }));
  await page.route('**/news-desk/data/stocks.json*', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{"stocks":{}}' }));
  await page.route('**://fonts.googleapis.com/**', r => r.abort());
  await page.goto('http://127.0.0.1:8765/index.html#news', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#v-news .nd-row');
  console.log('\n== real-browser interaction ==');
  const n0 = await page.locator('#v-news .nd-row').count();
  // 'sector' is in the fixture's titles. (Searching 'upgrade' would correctly
  // return nothing: the haystack is title+summary+tickers+source, not type —
  // same as the tab it replaces. That is what the Type select is for.)
  await page.fill('#nd-q', 'sector');
  await page.waitForTimeout(120);
  const n1 = await page.locator('#v-news .nd-row').count();
  ok('typing in search really filters in Chromium', n1 > 0 && n1 < n0, `${n0} -> ${n1}`);
  await page.click('#v-news [data-act="clr"]');
  await page.waitForTimeout(120);
  ok('CLEAR really restores in Chromium', await page.locator('#v-news .nd-row').count() === n0);
  await page.selectOption('#nd-src', 'Reuters');
  await page.waitForTimeout(120);
  const n2 = await page.locator('#v-news .nd-row').count();
  ok('source select really filters in Chromium', n2 > 0 && n2 < n0, `${n0} -> ${n2}`);
  await page.click('#v-news [data-act="clr"]');
  await page.click('#v-news [data-tab="book"]');
  await page.waitForTimeout(150);
  ok('MY BOOK tab really switches in Chromium',
    (await page.locator('#v-news .nd-bookhead, #nd-drop').count()) > 0);
  await page.click('#v-news [data-tab="news"]');
  await page.waitForTimeout(120);
  ok('back to NEWS in Chromium', await page.locator('#v-news .nd-row').count() === n0);
  await page.locator('#v-news .nd-sym').first().click();
  await page.waitForTimeout(120);
  ok('ticker click really filters in Chromium', await page.locator('#nd-chips .rd-chip').count() === 1);
  await page.close();

  await browser.close();
  server.close();
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('HARNESS ERROR', e); process.exit(2); });
