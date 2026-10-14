/* Market strip (owner, 2026-10-14, Q65 = a). Driven in jsdom against the REAL
   docs/index.html with a stubbed indices.json: ten cells under the menu,
   change against the prior close, the 10-year in basis points, nothing drawn
   from a missing file.

       node tests/market_strip.test.js
*/
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const html = fs.readFileSync(path.join(__dirname, '..', 'docs/index.html'), 'utf8');
let pass = 0, fail = 0;
const ok = (name, cond, extra) => {
  if (cond) { pass++; console.log('  ok   ' + name); }
  else { fail++; console.log('  FAIL ' + name + (extra ? '  -> ' + extra : '')); }
};
const t = Math.floor(Date.now() / 1000);
const path5 = (a, b) => [[t - 600, a], [t - 300, (a + b) / 2], [t, b]];
const INDICES = { generated: new Date().toISOString(), indices: [
  { key: '^GSPC', label: 'S&P 500', kind: 'index', last: 7713.64, prev: 7805.45, change: -91.81, change_pct: -1.18, as_of: new Date().toISOString(), path: path5(7790, 7713.64) },
  { key: '^TNX', label: '10-yr yield', kind: 'yield', last: 5.192, prev: 5.217, change_bp: -2.5, as_of: new Date().toISOString(), path: path5(5.21, 5.192) },
  { key: '^VIX', label: 'VIX', kind: 'index', last: 17.19, prev: 15.27, change: 1.92, change_pct: 12.57, as_of: new Date().toISOString(), path: path5(15.5, 17.19) },
  { key: 'BTC-USD', label: 'Bitcoin', kind: 'price', last: 81745.29, prev: 80000, change: 1745.29, change_pct: 2.18, as_of: new Date().toISOString(), path: path5(80100, 81745.29) },
] };

function page(body) {
  const errors = [];
  const vc = new VirtualConsole();
  vc.on('jsdomError', e => errors.push(String(e.message || e)));
  const dom = new JSDOM(html, {
    runScripts: 'dangerously', url: 'https://helioskozak-cloud.github.io/regime-desk/',
    pretendToBeVisual: true, virtualConsole: vc,
    beforeParse(win) {
      win.fetch = url => /indices\.json/.test(url) && body
        ? Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(body) })
        : Promise.resolve({ ok: false, status: 503, json: () => Promise.reject(new Error('offline')) });
    },
  });
  return { dom, errors };
}
const tick = (ms = 60) => new Promise(r => setTimeout(r, ms));

(async () => {
  const { dom, errors } = page(INDICES);
  await tick();
  const doc = dom.window.document;
  const strip = doc.getElementById('mkt-strip');
  const top = doc.getElementById('topbar');
  ok('the strip sits directly under the menu', top.nextElementSibling === strip);
  const cells = Array.from(strip.querySelectorAll('.mk'));
  ok('one cell per instrument', cells.length === 4, String(cells.length));
  const txt = i => cells[i].textContent.replace(/\s+/g, ' ');
  ok('the S&P reads its level and a signed percent', /S&P 500/.test(txt(0)) && /7,713\.64/.test(txt(0)) && /−1\.18%/.test(txt(0)), txt(0));
  ok('down is red', cells[0].querySelector('.mk-c').classList.contains('dn'));
  ok('the 10-year reads percent and basis points', /5\.19%/.test(txt(1)) && /−2\.5 bp/.test(txt(1)), txt(1));
  ok('a rising VIX reads red, line and number, with its real sign', /\+12\.57%/.test(txt(2))
    && cells[2].querySelector('.mk-c').classList.contains('dn') && cells[2].querySelector('polyline').getAttribute('stroke') === '#e5484d', txt(2));
  ok('bitcoin has no cents and up is green', /81,745(?!\.)/.test(txt(3)) && cells[3].querySelector('.mk-c').classList.contains('up'), txt(3));
  ok('each cell draws its path and the prior close', cells.every(c => c.querySelector('polyline') && c.querySelector('line')));
  ok('the tooltip names the prior close', /vs prior close 7,805\.45/.test(cells[0].title), cells[0].title);
  for (const v of ['#news', '#filings', '#analysis', '#bubble']) {
    dom.window.location.hash = v; dom.window.dispatchEvent(new dom.window.HashChangeEvent('hashchange')); await tick(20);
  }
  ok('it stays on every tab', strip.querySelectorAll('.mk').length === 4 && !strip.closest('.view'));
  ok('no page errors', errors.length === 0, errors.slice(0, 3).join(' | '));

  const off = page(null);
  await tick();
  const s2 = off.dom.window.document.getElementById('mkt-strip');
  ok('no file: a quiet note, no zero levels', /unavailable/.test(s2.textContent) && !s2.querySelector('.mk'), s2.textContent);

  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})();
