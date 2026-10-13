/* News tab context (2026-10-13, owner Q55 = c).

   Pins: a headline's row says when its company reports and links a material
   filing from this page's own scans; a big move carries its size in sigma
   (a small one does not); the releases line lists the week's major US data;
   and "Why it moved" pairs each unusual mover with its newest headline, or
   says "no headline in our feeds" when there is none.

   Run: node tests/news_context.test.js */
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

const et = d => d.toLocaleDateString('en-CA', { timeZone: 'America/New_York' });
const day = n => { const d = new Date(); d.setUTCDate(d.getUTCDate() + n); return et(d); };
const TODAY = day(0), TOMORROW = day(1);
const now = new Date().toISOString();
const hoursAgo = h => new Date(Date.now() - h * 3600e3).toISOString();

const HEADLINES = {
  generated: now,
  headlines: [
    { title: 'Acme beats on revenue', link: 'https://example.com/a', source: 'CNBC Top', published: now,
      tickers: ['ACME'], type: 'earnings', sentiment: 'positive', summary: '' },
    { title: 'Quiet Corp names new CFO', link: 'https://example.com/q', source: 'Benzinga', published: now,
      tickers: ['QUIET'], type: 'stocks', sentiment: 'neutral', summary: '' },
    { title: 'Profusa, Inc. (PFX) files 8-K: auditor change', link: 'https://www.sec.gov/x', source: 'SEC EDGAR',
      published: now, tickers: ['PFX'], type: '8k', sentiment: 'negative', summary: '' },
    { title: 'Old story about Zoomer', link: 'https://example.com/old', source: 'CNBC Top', published: hoursAgo(60),
      tickers: ['ZOOM2'], type: 'stocks', sentiment: 'neutral', summary: '' },
  ],
};
const STOCKS = { generated: now, stocks: {
  ACME:  { price: 52.0, prev_close: 50.0, sigma: 3.4, vol_20d: 1.1 },
  QUIET: { price: 10.1, prev_close: 10.0, sigma: 0.6, vol_20d: 1.6 },
} };
const MOVERS = { generated: now, as_of: TODAY, universe: 1752, priced: 1691, threshold: 2.5, min_abs_pct: 2,
  movers: [
    { ticker: 'ACME', name: 'Acme Corp', price: 52, change_pct: 4.0, vol_20d: 1.1, sigma: 3.4 },
    { ticker: 'ZOOM2', name: 'Zoomer Inc', price: 8, change_pct: -9.5, vol_20d: 3.0, sigma: -3.2 },
  ] };

const vc = new VirtualConsole();
const errors = [];
vc.on('jsdomError', e => errors.push(String(e.message || e)));
const dom = new JSDOM(html, {
  runScripts: 'dangerously', url: 'https://helioskozak-cloud.github.io/regime-desk/',
  pretendToBeVisual: true, virtualConsole: vc,
  beforeParse(win) {
    win.fetch = (url) => {
      const body = /headlines\.json/.test(url) ? HEADLINES : /movers\.json/.test(url) ? MOVERS : STOCKS;
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) });
    };
  },
});
const win = dom.window, doc = win.document;
const tick = (ms = 30) => new Promise(r => setTimeout(r, ms));
const row = t => Array.from(doc.querySelectorAll('#v-news .nd-row')).find(r => r.textContent.includes(t));

(async () => {
  await tick(80);
  // This page's own scans, as the build embeds them.
  Object.assign(win.SNAPSHOT, {
    earnings: { earnings: [
      { date: TODAY, ticker: 'ACME', time: 'pre' },
      { date: TOMORROW, ticker: 'QUIET', time: 'post' },
    ] },
    filings: { filings: [
      { ticker: 'QUIET', date: TODAY, form: '8-K', kind: '8-K', rank: 3, what: '5.02 officer/director change',
        url: 'https://www.sec.gov/q' },
      { ticker: 'PFX', date: TODAY, form: '8-K', kind: '8-K', rank: 1, what: '4.01 auditor change',
        url: 'https://www.sec.gov/x' },
      { ticker: 'ACME', date: TODAY, form: '8-K', kind: '8-K', rank: 6, what: '8-K', url: 'https://www.sec.gov/r' },
    ] },
    releases: { releases: [
      { date: TOMORROW, time: '08:30', name: 'CPI', agency: 'BLS', importance: 3 },
      { date: TOMORROW, time: '10:00', name: 'Minor survey', agency: 'X', importance: 1 },
    ] },
  });
  win.location.hash = '#news';
  win.dispatchEvent(new win.HashChangeEvent('hashchange'));
  await tick(150);

  console.log('\n== context on each row ==');
  const acme = row('Acme beats').querySelector('.nd-tks');
  ok('reporter today says so, with the session', /Reported today, before the open|Reports today, before the open/.test(acme.textContent), acme.textContent);
  ok('a routine 8-K (rank 6) is not shown', !acme.querySelector('.nd-ctx.fil'));
  const quiet = row('Quiet Corp').querySelector('.nd-tks');
  ok('reporter tomorrow, after the close', /Reports tomorrow, after the close/.test(quiet.textContent), quiet.textContent);
  const fil = quiet.querySelector('a.nd-ctx.fil');
  ok('a material filing links to EDGAR', fil && fil.href === 'https://www.sec.gov/q', fil && fil.outerHTML);
  ok('item numbers are dropped from the label', fil && /officer\/director change/.test(fil.textContent) && !/5\.02/.test(fil.textContent));
  ok('an EDGAR headline does not repeat its own filing', !row('files 8-K').querySelector('.nd-ctx.fil'));

  console.log('\n== move size ==');
  ok('a 3.4 sd move shows its size', /3\.4σ/.test(acme.querySelector('.nd-tk').textContent));
  ok('a 0.6 sd move shows none', !quiet.querySelector('.nd-sg'));

  console.log('\n== releases line ==');
  const mac = doc.getElementById('nd-macro').textContent;
  ok('CPI tomorrow is listed with its time', /tomorrow 08:30 ET CPI/.test(mac), mac);
  ok('a minor release is not', !/Minor survey/.test(mac));

  console.log('\n== the tab is news only: no regime banner, no movers ==');
  ok('body carries view-news', doc.body.classList.contains('view-news'));
  ok('the regime banner shows on Home only', /body:not\(\[data-view="home"\]\) #regime-banner\{display:none\}/.test(html)
    && doc.body.dataset.view === 'news');
  ok('Why it moved is not on the News tab', !doc.querySelector('#v-news #nd-movers'));

  console.log('\n== both News sections fold, and stay folded ==');
  const cards = Array.from(doc.querySelectorAll('#v-news .card[data-fold]'));
  ok('two foldable sections', cards.map(c => c.dataset.fold).join() === 'controls,feed', cards.map(c => c.dataset.fold).join());
  const feedCard = cards[1];
  feedCard.querySelector('h2').click(); await tick(5);
  ok('clicking a heading folds it', feedCard.classList.contains('folded'));
  ok('the fold is remembered', JSON.parse(win.localStorage.getItem('rd-news-folds')).feed === true);
  await win.NEWSTAB.load(); await tick(20);
  ok('a 60s refresh does not unfold it', feedCard.classList.contains('folded'));
  feedCard.querySelector('h2').click(); await tick(5);
  ok('clicking again opens it', !feedCard.classList.contains('folded'));
  ok('the heading shows a visible Hide / Show control', /content:"Hide \\25B4"/.test(html) && /content:"Show \\25BE"/.test(html));
  const grp = doc.querySelector('#v-news .nd-gblk .nd-grp');
  grp.click(); await tick(5);
  ok('a date group folds its headlines', grp.parentElement.classList.contains('folded'));
  grp.click(); await tick(5);

  console.log('\n== why it moved, now on Filings ==');
  win.location.hash = '#filings';
  win.dispatchEvent(new win.HashChangeEvent('hashchange'));
  await tick(60);
  doc.querySelector('#v-filings [data-fil-view="movers"]').click();
  await tick(60);
  const mv = Array.from(doc.querySelectorAll('#v-filings #nd-movers .nd-mv'));
  ok('both movers listed', mv.length === 2, String(mv.length));
  ok('a mover with a headline shows it', /Acme beats on revenue/.test(mv[0].textContent));
  ok('and its earnings', /Reported today|Reports today/.test(mv[0].textContent));
  ok('a mover whose only story is 60h old reads "no headline in our feeds"',
    /no headline in our feeds/.test(mv[1].textContent), mv[1].textContent);
  ok('size is unsigned sigma, direction is in the percent', /3\.2σ/.test(mv[1].textContent) && /-9\.5%/.test(mv[1].textContent));
  ok('the footer counts movers with a headline', /1 of 2 have a headline/.test(doc.getElementById('nd-movers').textContent));
  mv[1].querySelector('[data-tk]').click();
  await tick(60);
  ok('clicking a mover opens News filtered to it', win.NEWSTAB.state.ticker === 'ZOOM2' && win.location.hash === '#news');
  win.dispatchEvent(new win.HashChangeEvent('hashchange')); await tick(30);
  win.NEWSTAB.state.ticker = null; win.NEWSTAB.render(); await tick(10);

  console.log('\n== the ticker card is news-desk\'s ==');
  const card = win.NEWSTAB.cardHTML('ACME');
  ok('price and move size', /\$52\.00/.test(card) && /3\.4σ/.test(card), card.slice(0, 200));
  win.NEWSTAB.state.nd.ACME.closes = [48, 49, 50, 49.5, 52];
  ok('the week\'s closes draw a sparkline and a 7-day range', /<polyline/.test(win.NEWSTAB.cardHTML('ACME'))
    && /7d range/.test(win.NEWSTAB.cardHTML('ACME')));
  ok('headline count, types and the latest titles', /1<\/strong> headline in the feed/.test(card) && /EARNINGS 1|earnings 1/.test(card) && /Acme beats on revenue/.test(card));
  ok('and its earnings date', /Reported today|Reports today/.test(card));
  ok('no link to news-desk anywhere on the tab', !/news-desk\/"/.test(doc.getElementById('v-news').innerHTML));
  ok('a ticker with nothing to show gets no card', win.NEWSTAB.cardHTML('NOPE') === null);

  const real = errors.filter(e => !/Could not parse CSS|Not implemented/i.test(e));
  ok('no page errors', real.length === 0, real.slice(0, 3).join(' | '));
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('HARNESS ERROR', e); process.exit(2); });
