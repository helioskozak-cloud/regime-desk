/* UI review harness — screenshots + measured geometry for every tab at every
   width, plus a hard horizontal-scrollbar assertion.

   Not a unit test: this exists so a spacing pass can be reviewed against real
   rendered pixels instead of guesses. Modelled on news_layout.test.js — same
   server, same fetch interception, same Chromium.

     OUT=.ui-review/before node tests/ui_shots.js

   Writes <tab>-<width>.png and measurements.json into $OUT. Exits non-zero if
   any tab at any width has a horizontal scrollbar. */
const fs = require('fs');
const http = require('http');
const path = require('path');
const { chromium } = require('playwright');

const REPO = path.resolve(__dirname, '..');
const DOCS = path.join(REPO, 'docs');
const OUT = path.resolve(REPO, process.env.OUT || '.ui-review/tmp');
const PORT = Number(process.env.PORT || 8766);

const TABS = ['home', 'analysis', 'bubble', 'news'];
const WIDTHS = [1366, 1920, 2560, 1180, 820];

fs.mkdirSync(OUT, { recursive: true });

// ── Synthetic news feed, same shape as news_layout.test.js ──────────────────
const html = fs.readFileSync(path.join(DOCS, 'index.html'), 'utf8');
const i = html.indexOf('window.SNAPSHOT = ');
const snap = JSON.parse(html.slice(i + 'window.SNAPSHOT = '.length, html.indexOf('\n</script>', i)).trim().replace(/;$/, ''));
const covered = (snap.all_signals || []).filter(s => typeof s.price === 'number').map(s => s.ticker);

const LONG = 'Supercalifragilisticexpialidocious-Pharmaceuticals-International-Holdings announces a definitive agreement';
const NOW = Date.UTC(2026, 6, 31, 12, 0, 0);   // fixed clock: screenshots must be diffable
const iso = m => new Date(NOW - m * 60000).toISOString();
const SOURCES = ['Reuters', 'PR Newswire', 'Business Wire', 'GlobeNewswire', 'SEC EDGAR'];
const TYPES = ['earnings', 'upgrade', 'downgrade', 'analyst', 'offering', 'macro', 'filings'];
const headlines = [];
for (let n = 0; n < 60; n++) {
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

const MIME = { '.js': 'application/javascript', '.json': 'application/json', '.css': 'text/css', '.png': 'image/png' };
const server = http.createServer((req, res) => {
  const rel = decodeURIComponent(req.url.split('?')[0]);
  const f = path.join(DOCS, rel === '/' ? 'index.html' : rel);
  if (!f.startsWith(DOCS) || !fs.existsSync(f) || fs.statSync(f).isDirectory()) { res.writeHead(404); res.end('no'); return; }
  res.writeHead(200, { 'Content-Type': MIME[path.extname(f)] || 'text/html; charset=utf-8' });
  res.end(fs.readFileSync(f));
});

// ── Geometry probe. Runs in the page; returns plain JSON. ───────────────────
function probe(tab) {
  const R = e => e.getBoundingClientRect();
  const px = (e, p) => parseFloat(getComputedStyle(e)[p]) || 0;
  const view = document.querySelector('#v-' + tab);
  const de = document.documentElement;

  // every element that pokes past the viewport
  const overflowing = Array.from(view.querySelectorAll('*'))
    .filter(e => R(e).width > 0 && R(e).right > de.clientWidth + 1)
    .slice(0, 6)
    .map(e => (e.tagName + '.' + (typeof e.className === 'string' ? e.className : '')).slice(0, 60) + ' @' + Math.round(R(e).right));

  const cards = Array.from(view.querySelectorAll(':scope > .card, :scope > * > .card'))
    .filter(c => R(c).width > 0);

  // Top-level blocks directly under the view — the things whose left edges
  // ought to agree with each other and with #topbar's contents.
  const blocks = Array.from(view.children).filter(e => R(e).width > 0);

  const topbar = document.querySelector('#topbar');
  const topbarH1 = document.querySelector('#topbar h1');
  const banner = document.querySelector('#regime-banner');
  const main = document.querySelector('#main');

  return {
    tab,
    overflowing,
    doc: { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, scrollHeight: de.scrollHeight },
    topbar: {
      left: R(topbar).left, padLeft: px(topbar, 'paddingLeft'), padRight: px(topbar, 'paddingRight'),
      h1Left: topbarH1 ? R(topbarH1).left : null,
      contentRight: R(topbar).right - px(topbar, 'paddingRight'),
      height: R(topbar).height,
    },
    banner: banner ? { left: R(banner).left + px(banner, 'paddingLeft'), padTop: px(banner, 'paddingTop'), padBottom: px(banner, 'paddingBottom') } : null,
    main: { left: R(main).left, right: R(main).right, width: R(main).width, padLeft: px(main, 'paddingLeft'), padTop: px(main, 'paddingTop'), contentLeft: R(main).left + px(main, 'paddingLeft'), contentRight: R(main).right - px(main, 'paddingRight') },
    blocks: blocks.map(e => ({
      cls: (typeof e.className === 'string' ? e.className : '').slice(0, 40),
      tag: e.tagName,
      left: +R(e).left.toFixed(1), right: +R(e).right.toFixed(1), width: +R(e).width.toFixed(1),
      mb: px(e, 'marginBottom'), mt: px(e, 'marginTop'),
    })),
    cards: cards.map(c => ({
      h2: (c.querySelector('h2') || {}).textContent ? c.querySelector('h2').textContent.trim().slice(0, 34) : '(no h2)',
      left: +R(c).left.toFixed(1), right: +R(c).right.toFixed(1), width: +R(c).width.toFixed(1),
      padT: px(c, 'paddingTop'), padR: px(c, 'paddingRight'), padB: px(c, 'paddingBottom'), padL: px(c, 'paddingLeft'),
      mb: px(c, 'marginBottom'),
      // where the card's first real content starts, relative to the card box
      firstChildTop: (() => {
        const k = Array.from(c.children).find(e => R(e).height > 0);
        return k ? +(R(k).top - R(c).top).toFixed(1) : null;
      })(),
    })),
    // Anything inside the view drawn as a card-like panel but not via .card
    fauxCards: Array.from(view.querySelectorAll('div[style*="border"]'))
      .filter(e => {
        const s = getComputedStyle(e);
        return R(e).width > 200 && s.backgroundColor === 'rgb(22, 27, 34)' && !e.classList.contains('card');
      })
      .slice(0, 12)
      .map(e => ({
        left: +R(e).left.toFixed(1), width: +R(e).width.toFixed(1),
        pad: [px(e, 'paddingTop'), px(e, 'paddingRight'), px(e, 'paddingBottom'), px(e, 'paddingLeft')].join('/'),
        mb: px(e, 'marginBottom'), radius: getComputedStyle(e).borderRadius,
        txt: (e.textContent || '').trim().slice(0, 30),
      })),
    tables: Array.from(view.querySelectorAll('table')).slice(0, 8).map(t => {
      const th = t.querySelector('th'), td = t.querySelector('td');
      return {
        right: +R(t).right.toFixed(1), width: +R(t).width.toFixed(1),
        thPad: th ? [px(th, 'paddingTop'), px(th, 'paddingRight'), px(th, 'paddingBottom'), px(th, 'paddingLeft')].join('/') : null,
        tdPad: td ? [px(td, 'paddingTop'), px(td, 'paddingRight'), px(td, 'paddingBottom'), px(td, 'paddingLeft')].join('/') : null,
      };
    }),
    // rightmost painted edge of anything in the view — reveals orphaned
    // right-hand whitespace when it falls well short of main's content box
    contentMaxRight: Math.max(0, ...Array.from(view.querySelectorAll('*'))
      .filter(e => R(e).width > 0 && R(e).height > 0)
      .map(e => R(e).right)),
  };
}

let fail = 0;
const results = [];

(async () => {
  await new Promise(r => server.listen(PORT, '127.0.0.1', r));
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });

  for (const w of WIDTHS) {
    for (const tab of TABS) {
      const page = await browser.newPage({ viewport: { width: w, height: 900 }, deviceScaleFactor: 1 });
      await page.route('**/news-desk/data/headlines.json*', r => r.fulfill({ status: 200, contentType: 'application/json', body: FEED }));
      await page.route('**/news-desk/data/stocks.json*', r => r.fulfill({ status: 200, contentType: 'application/json', body: '{"stocks":{}}' }));
      await page.route('**://assets.parqet.com/**', r => r.abort());
      const errs = [];
      page.on('pageerror', e => errs.push(String(e)));

      await page.goto(`http://127.0.0.1:${PORT}/index.html#${tab}`, { waitUntil: 'domcontentloaded' });
      await page.waitForSelector(`#v-${tab}.active`, { timeout: 15000 });
      if (tab === 'news') await page.waitForSelector('#v-news .nd-row', { timeout: 20000 }).catch(() => {});
      await page.evaluate(() => document.fonts.ready);
      await page.waitForTimeout(tab === 'bubble' ? 1400 : 700);   // charts/animation settle

      const m = await page.evaluate(probe, tab);
      m.width = w;
      m.pageErrors = errs.slice(0, 3);
      results.push(m);

      const bad = m.doc.scrollWidth > m.doc.clientWidth;
      if (bad) fail++;
      console.log(`${bad ? 'FAIL' : 'ok  '} ${tab}@${w}  scrollW ${m.doc.scrollWidth} / clientW ${m.doc.clientWidth}` +
        (m.overflowing.length ? `  overflow: ${m.overflowing.join(' | ')}` : '') +
        (errs.length ? `  ERR ${errs[0].slice(0, 80)}` : ''));

      await page.screenshot({ path: path.join(OUT, `${tab}-${w}.png`), fullPage: true });
      await page.close();
    }
  }

  await browser.close();
  server.close();
  fs.writeFileSync(path.join(OUT, 'measurements.json'), JSON.stringify(results, null, 1));
  console.log(`\nwrote ${results.length} shots + measurements.json to ${OUT}`);
  console.log(fail ? `${fail} horizontal-scroll failures` : 'no horizontal scrollbar at any width');
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('HARNESS ERROR', e); process.exit(2); });
