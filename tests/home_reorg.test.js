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
  ok(nInval === nAxes, 'every axis shows an invalidation (' + nInval + '/' + nAxes + ')');
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

  console.log('\n== console errors ==');
  ok(errors.length === 0, 'no page errors (' + errors.join('; ') + ')');

  console.log('\n' + pass + ' passed, ' + fail + ' failed');
  process.exit(fail ? 1 : 0);
}, 1500);
