// Home re-org acceptance — REORG_SPEC criteria 1 and 2.
//
// Like the news tests, this drives the real docs/index.html and asserts on the
// RENDERED DOM rather than on source text. Both criteria are the kind that fail
// silently: a duplicated reading and a merged card that quietly stopped merging
// both look fine to the validator, which only checks for id="v-*", script tags,
// fetch and file size.
//
//     npm i jsdom          # not vendored; install where you run it
//     node tests/home_reorg.test.js
//
// Criterion 1: no reading appears twice on the same screen without a reason.
//   The banner used to repeat the eight readings the REGIME ANALYSIS card shows
//   ~200px below it, on every tab including Bubble and News.
// Criterion 2: each risk axis shows its reading AND its invalidation condition.
//   These were two cards, four panels apart, with the score printed in both.
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const PAGE = path.resolve(__dirname, '..', 'docs', 'index.html');
const html = fs.readFileSync(PAGE, 'utf8');

const errors = [];
const dom = new JSDOM(html, {
  runScripts: 'dangerously',
  pretendToBeVisual: true,
  url: 'https://helioskozak-cloud.github.io/regime-desk/',
  beforeParse(w) {
    // The live feeds are not this test's subject; refuse them so the run is
    // hermetic. A failure here must come from the page, not the network.
    w.fetch = () => Promise.reject(new Error('offline in this check'));
    w.addEventListener('error', (e) => errors.push(String(e.error || e.message)));
  },
});

const w = dom.window;
let pass = 0;
let fail = 0;
const ok = (cond, label) => {
  if (cond) { pass++; console.log('  ok   ' + label); }
  else { fail++; console.log('  FAIL ' + label); }
};

setTimeout(() => {
  const vhome = w.document.getElementById('v-home');
  const home = vhome ? vhome.innerHTML : '';

  console.log('\n== criterion 2: reading and invalidation together ==');
  const nAxes = ((w.SNAPSHOT && w.SNAPSHOT.risks) || []).length;
  const nInval = (home.match(/Invalidation:/g) || []).length;

  ok(home.length > 0, 'Home rendered');
  ok(nAxes > 0, 'snapshot has risk axes (' + nAxes + ')');
  ok(nInval === nAxes, 'every axis carries an invalidation (' + nInval + '/' + nAxes + ')');

  // ── criterion 2b: one line per axis, with a meter and its two ranges ──────
  //
  // Owner, 2026-09-11: "fit them all on one line again with an actual meter for
  // the metric and a 30 and 90 day range for each metric", and separately that
  // the first screen stopped at Rate Re-pricing. Seven three-line blocks cannot
  // clear the fold, so the card meant to be read at a glance had become one you
  // scrolled. The invalidation moved to the row's tooltip rather than being
  // dropped, which is why the count above still has to match.
  console.log('\n== criterion 2b: one line per axis, meter and ranges ==');
  const rows = Array.from(w.document.querySelectorAll('#v-home .rax'));
  ok(rows.length === nAxes, 'one row per axis (' + rows.length + '/' + nAxes + ')');
  ok(rows.every((r) => /Invalidation:/.test(r.getAttribute('title') || '')),
     'every row keeps its invalidation, on the row itself');
  ok(rows.every((r) => r.querySelector('.rax-meter') && r.querySelector('.rax-now')),
     'every row draws a meter with a marker for today');
  ok(rows.every((r) => (r.textContent.match(/30d/g) || []).length === 1
                    && (r.textContent.match(/90d/g) || []).length === 1),
     'every row states a 30-day and a 90-day range');

  // A RANGE WE DO NOT HAVE MUST BE DRAWN AS NOTHING. A zero-width band parked at
  // today's value reads as "this axis has not moved in three months", which is
  // the opposite of "it could not be measured" — the suite's oldest bug shape.
  const axes = (w.SNAPSHOT && w.SNAPSHOT.risks) || [];
  const withRange = axes.filter((a) => a.range90 && typeof a.range90.lo === 'number').length;
  const drawn = rows.filter((r) => r.querySelector('.rax-b90')).length;
  const naShown = rows.filter((r) => /n\/a/.test(r.textContent)).length;
  ok(drawn === withRange,
     'bands are drawn only where a range exists (' + drawn + '/' + withRange + ')');
  ok(naShown === nAxes - withRange,
     'a missing range reads as n/a, never as a flat band (' + naShown + ')');
  ok(/<h2>Risk Axes<\/h2>/.test(home), 'the merged Risk Axes card is on Home');
  ok(!/Aggregate Risk Score/.test(home), 'the separate Aggregate Risk Score card is gone');
  ok(!/Invalidation Levels/.test(home), 'the separate Invalidation card is gone');
  ok(/Composite/.test(home), 'composite score retained');

  console.log('\n== criterion 1: no reading twice on one screen ==');
  const banner = w.document.getElementById('regime-banner').innerHTML;
  ['SPY 5d', 'SPY 20d', 'Drawdown 60d', 'Breadth', 'Persistence', 'Rev. Risk']
    .forEach((d) => ok(!banner.includes(d), 'banner no longer repeats "' + d + '"'));
  ok(banner.includes('VIX'), 'banner keeps VIX (the one reading NOT in the card)');
  ok(/regime-label/.test(banner), 'banner keeps the regime label');

  console.log('\n== the card still owns those readings ==');
  ['5d return', '20d return', 'Breadth', 'Persistence']
    .forEach((d) => ok(home.includes(d), 'card still carries "' + d + '"'));

  // ---- criterion 5: the charts earn their width ----
  // history carries four series; the panel used to plot two of them and
  // stretch each 440px viewBox to ~880px. All four are plotted now.
  console.log('\n== criterion 5: four series, not two ==');
  // Match the chart's own <text> label, NOT a bare substring: "60d drawdown"
  // is also a tile label in the regime card, so home.includes() passed even
  // with the chart deleted. Caught by mutation, not by reading it.
  ['Rolling 5d return', 'Rolling 20d return', 'Annualized vol', '60d drawdown']
    .forEach((l) => ok(home.includes('>' + l + '</text>'), 'trajectory plots "' + l + '"'));
  ok(!/class="grid2"[^>]*>\s*<svg/.test(home),
    'trajectory no longer uses the 2-up grid that stretched each chart');

  // ---- item 2: fewer full-width rows before the first panel ----
  // The overnight deltas were their own row above the card showing the very
  // readings they are deltas of. They moved onto the tiles.
  console.log('\n== item 2: deltas sit on the reading they belong to ==');
  ok(!/Since yesterday/i.test(home), 'the separate daily-brief strip is gone');
  const nDeltas = (home.match(/>1d<\/span>/g) || []).length;
  ok(nDeltas >= 4, 'four readings carry an overnight delta on their tile (' + nDeltas + ')');
  ok(!!(w.SNAPSHOT && w.SNAPSHOT.generated) && home.includes(w.SNAPSHOT.generated),
    'the build timestamp survived the strip removal');

  console.log('\n== console errors ==');
  ok(errors.length === 0, 'no page errors (' + errors.join('; ') + ')');

  console.log('\n' + pass + ' passed, ' + fail + ' failed');
  process.exit(fail ? 1 : 0);
}, 1500);
