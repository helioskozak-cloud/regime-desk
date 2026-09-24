/* Home is three dashboards, and every number on the first two explains itself.

   Owner, 2026-09-14: "Can you do a similar expanding tooltip for the regime
   analysis and trajectory verdict sections. You can also get rid of the rest or
   move it elsewhere, I never look past these three dashboards."

   Drives the REAL docs/index.html in jsdom. Assertions are about what the owner
   reads after a click, because the two failures worth guarding against are a
   panel that does not open and a panel that says something false. The second
   one already happened once while this was being built: the "closest other
   label" compared absolute distances and named Bull Trend, 7.3pp away, over
   Pullback at 2.7pp. The synthetic case at the bottom pins that.

   Needs jsdom, like the other *.test.js here:  node tests/home_explain.test.js */
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('jsdom');

const html = fs.readFileSync(path.resolve(__dirname, '..', 'docs', 'index.html'), 'utf8');

let pass = 0, fail = 0;
const ok = (cond, label, extra) => {
  if (cond) { pass++; console.log('  ok   ' + label); }
  else { fail++; console.log('  FAIL ' + label + (extra ? '  -> ' + extra : '')); }
};

const errors = [];
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => errors.push(e.message));
const dom = new JSDOM(html, {
  runScripts: 'dangerously', pretendToBeVisual: true,
  url: 'https://regime-desk.test/#home', virtualConsole: vc,
});
const w = dom.window;
w.fetch = () => Promise.reject(new Error('offline in test'));

// Lift a pure function out of the shipped page. Reimplementing it here would
// keep passing after the page's copy broke.
const lift = (from, to, name) => {
  const a = html.indexOf(from), b = html.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('cannot find ' + name + ' in docs/index.html');
  return new Function(html.slice(a, b) + ';return ' + name + ';')();
};

const text = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
const click = (el) => el.dispatchEvent(new w.MouseEvent('click', { bubbles: true }));

setTimeout(() => {
  const d = w.document;
  const home = d.getElementById('v-home');
  const spy = w.SNAPSHOT.spy;

  // ── the three dashboards, and only those ─────────────────────────────────
  console.log('\n== Home is the three dashboards ==');
  const cards = [...home.querySelectorAll('.card > h2')].map((h) => h.textContent);
  ok(JSON.stringify(cards) === JSON.stringify(['Regime Analysis', 'Trajectory Verdict', 'Risk Axes']),
    'Home carries exactly Regime Analysis, Trajectory Verdict, Risk Axes', JSON.stringify(cards));

  // ── nothing deleted: the rest is one tab away ────────────────────────────
  // Checked BEFORE any click, while Analysis is still unrendered; it is
  // rendered on route below.
  // ── every trigger has a panel, and every panel opens ─────────────────────
  console.log('\n== every trigger opens its own panel ==');
  const triggers = [...home.querySelectorAll('[data-why]')];
  const ids = [...new Set(triggers.map((t) => t.dataset.why))];
  ok(ids.length >= 10, 'at least ten distinct panels on Home (' + ids.length + ')');
  ok(ids.every((id) => d.getElementById(id)), 'no trigger points at a missing panel',
    ids.filter((id) => !d.getElementById(id)).join(','));
  ok(ids.every((id) => d.getElementById(id).hidden), 'every panel starts closed');

  for (const id of ['why-regime', 'why-r20', 'why-breadth', 'why-rev', 'why-verdict']) {
    const t = home.querySelector(`[data-why="${id}"]`);
    click(t);
    const open = ids.filter((x) => !d.getElementById(x).hidden);
    ok(open.length === 1 && open[0] === id, `clicking ${id} opens it and only it`, open.join(','));
    ok(t.getAttribute('aria-expanded') === 'true', `${id} trigger reports expanded`);
  }
  click(home.querySelector('[data-why="why-verdict"]'));
  ok(ids.every((id) => d.getElementById(id).hidden), 'clicking the open trigger closes it');

  // Four verdict tiles and the verdict hero share one panel: whichever you
  // click, the same explanation opens.
  const vt = [...home.querySelectorAll('[data-why="why-verdict"]')];
  ok(vt.length === 5, 'the verdict hero and its four tiles all open the verdict panel (' + vt.length + ')');

  // ── Regime Analysis says true things ─────────────────────────────────────
  console.log('\n== Regime Analysis ==');
  const regimePanel = d.getElementById('why-regime');
  const fired = [...regimePanel.querySelectorAll('.rd-rule.fired')];
  ok(fired.length === 1, 'exactly one rule is marked as the one that fired (' + fired.length + ')');
  ok(fired[0] && text(fired[0]).includes(spy.regime),
    'the fired rule is the label on the card (' + spy.regime + ')', text(fired[0]).slice(0, 60));
  ok(/label, not a forecast/.test(text(regimePanel)), 'the panel says the regime is a label, not a forecast');

  // ── Breadth, Persistence, Reversal: measured, or honestly not ──────────
  //
  // Until 2026-09-14 the first two were a hardcoded 0.5 and the third a
  // four-step lookup. The page has to render two worlds correctly: a snapshot
  // whose scan has not produced the measurements yet, and one where it has.
  console.log('\n== the three measured tiles ==');

  // Re-render Home against edited snapshot values. Views cache their HTML on
  // first render (data-rendered), so the cache is cleared and the router fired.
  const rerender = (measures) => {
    spy.measures = measures;
    home.removeAttribute('data-rendered');
    w.dispatchEvent(new w.HashChangeEvent('hashchange'));
  };
  const saved = JSON.parse(JSON.stringify(spy.measures || null));

  // World 1: nothing measured. Every tile says so, with the scan's reason.
  rerender({
    breadth: { value: null, reason: 'only 12 names measurable on the latest session' },
    persistence: { value: null, reason: 'only 9 past sessions in 1 spell of Neutral in the history' },
    reversal: { value: null, reason: 'only 4 analog days have a finished 20-session window' },
  });
  for (const [id, reason] of [['why-breadth', '12 names'], ['why-persist', '1 spell'], ['why-rev', '4 analog days']]) {
    const tile = home.querySelector(`[data-why="${id}"]`);
    ok(/not measured/.test(text(tile)) && !/\d%/.test(text(tile)),
      `${id}: an unmeasured value reads "not measured", never a percentage`, text(tile));
    ok(text(d.getElementById(id)).includes(reason), `${id}: the panel gives the scan's reason`);
  }

  // World 2: measured, with today's real figures from the 2026-09-14 scan.
  const REAL = {
    breadth: { value: 0.402, n: 3010, n_typical: 3006, days: 703, ma: 50, pct_rank: 0.1422,
      range30: { lo: 0.3672, hi: 0.6963 }, range90: { lo: 0.3672, hi: 0.7169 } },
    persistence: { value: 0.8589, label: 'Neutral', horizon: 20, days: 567, held: 487, spells: 34,
      median_spell: 8, streak: 12, base_rate: 0.80, history_sessions: 732 },
    reversal: { value: 0.3667, horizon: 20, analogs: 30, reversed: 11, episodes: 8,
      base_days: 712, base_reversed: 259, base_rate: 0.3638, trailing_20d: -0.0186 },
  };
  rerender(REAL);
  const tB = text(home.querySelector('[data-why="why-breadth"]'));
  ok(/40%/.test(tB) && /14th pctile/.test(tB), 'Breadth tile shows 40% and its 14th percentile', tB);
  const pB = text(d.getElementById('why-breadth'));
  ok(/3,010 names/.test(pB) && /37%–70%/.test(pB), 'Breadth panel shows the name count and 30-day range');
  ok(/Lower than on 86%/.test(pB), 'Breadth panel turns the percentile into a sentence', pB.slice(0, 400));
  ok(/delisted/.test(pB), 'Breadth panel states the survivorship lean');

  const tP = text(home.querySelector('[data-why="why-persist"]'));
  ok(/86%/.test(tP) && /any day: 80%/.test(tP), 'Persistence tile shows 86% beside its 80% base rate', tP);
  const pP = text(d.getElementById('why-persist'));
  ok(/487 of 567/.test(pP) && /34/.test(pP), 'Persistence panel shows sessions and spells');
  // 86% vs 80% on 34 spells: one standard error is ~6.9 points, the gap 5.9.
  ok(/no stickier than that, within the noise/.test(pP),
    'a common label is NOT called sticky when the gap is inside the noise', pP.slice(0, 600));
  ok(/already run longer than a typical Neutral spell/.test(pP), 'today\'s 12-session spell is compared with the typical 8');

  const tR = text(home.querySelector('[data-why="why-rev"]'));
  ok(/37%/.test(tR) && /any day: 36%/.test(tR), 'Reversal tile shows 37% beside 36% any day', tR);
  const pR = text(d.getElementById('why-rev'));
  ok(/11 of 30/.test(pR) && /259 of 712/.test(pR), 'Reversal panel shows both counts');
  ok(/no clear difference from any day/.test(pR) && /within a point/.test(pR),
    'a 0.3-point gap reads as no difference, without printing "0-point gap"', pR.slice(0, 700));
  ok(/go up instead/.test(pR), 'SPY is down over 20 sessions, so a reversal means going up');
  ok(!/0-point/.test(pR), 'never prints the awkward "0-point gap"');

  // The verdict flips when the gap clears the noise, in either direction.
  rerender({ ...REAL,
    persistence: { ...REAL.persistence, value: 0.97, base_rate: 0.60 },
    reversal: { ...REAL.reversal, value: 0.70, reversed: 21, base_rate: 0.36 } });
  ok(/genuinely sticky/.test(text(d.getElementById('why-persist'))), 'a gap beyond the noise is called sticky');
  ok(/reversals have been more common/.test(text(d.getElementById('why-rev'))), 'a reversal rate well above any day says so');
  rerender({ ...REAL, reversal: { ...REAL.reversal, value: 0.05, reversed: 2, base_rate: 0.40 } });
  ok(/reversals have been less common/.test(text(d.getElementById('why-rev'))), 'and well below any day says that');

  // Noise is judged on SEPARATE EPISODES, not analog days. 50% vs 36% is a
  // 14-point gap: inside the ~17 points of noise in 8 episodes, but outside the
  // ~9 points you would claim by pretending 30 overlapping days were 30 draws.
  rerender({ ...REAL, reversal: { ...REAL.reversal, value: 0.50, reversed: 15, episodes: 8, base_rate: 0.36 } });
  ok(/no clear difference from any day/.test(text(d.getElementById('why-rev'))),
    'a 14-point gap on 8 episodes is still called noise — overlapping days are not independent');

  // Put the page back as it was published.
  rerender(saved);

  // ── the nearest-label bug, pinned ────────────────────────────────────────
  // A 20-day return of -2.3% is 2.7pp above the -5% Pullback line and 7.3pp
  // below the +5% Bull Trend line. Comparing absolute values scores both as
  // 2.7pp, and the first of the tie wins -- which named the wrong label on the
  // live page before this was caught.
  console.log('\n== nearest label uses signed distance ==');
  const nearest = lift('function _rdNearest(ex){', '// Which rules a reading feeds', '_rdNearest');
  const synthetic = {
    rules: [
      { result: 'Bull Trend', fired: false,
        conditions: [{ key: 'ret_20d', op: '>', threshold: 0.05, value: -0.023, met: false }] },
      { result: 'Pullback', fired: false,
        conditions: [{ key: 'ret_20d', op: '<', threshold: -0.05, value: -0.023, met: false }] },
    ],
  };
  const n = nearest(synthetic);
  ok(n && n.r.result === 'Pullback', 'from -2.3%, the nearest label is Pullback, not Bull Trend',
    n && n.r.result);
  ok(n && Math.abs(n.gap - 2.7) < 0.01, 'and the gap is 2.7pp (' + (n && n.gap.toFixed(2)) + ')');

  // ── Trajectory Verdict: same labels as before, one branch fixed ──────────
  console.log('\n== Trajectory Verdict ==');
  const tv = lift('const TV_R=0.005', 'function _cardVerdict(){', '_tvVerdict');
  // The pre-2026-09-14 ladder, verbatim, as the reference.
  const oldLadder = (rDelta, vDelta) => {
    if (rDelta > 0.005 && vDelta < 0) return 'Goldilocks';
    if (rDelta > 0.005 && vDelta >= 0) return 'Bullish but Choppy';
    if (rDelta <= 0.005 && rDelta >= -0.005 && Math.abs(vDelta) < 0.02) return 'Stable';
    if (rDelta < -0.005 && vDelta > 0) return 'Deteriorating';
    if (rDelta < -0.005) return 'Losing Momentum';
    return 'Vol Compression';
  };
  const E = 1e-7;
  const rs = [-0.05, -0.005 - E, -0.005, -0.005 + E, 0, 0.005 - E, 0.005, 0.005 + E, 0.05];
  const vs = [-0.1, -0.02 - E, -0.02, -0.02 + E, -E, 0, E, 0.02 - E, 0.02, 0.02 + E, 0.1];
  let same = 0, changed = [], wrongFix = [];
  for (const r of rs) for (const v of vs) {
    const was = oldLadder(r, v), now = tv(r, v).name;
    // The ONE deliberate change: flat returns with vol up 2pp or more used to be
    // called compression. Everything else must be identical.
    const isFixedCase = Math.abs(r) <= 0.005 && v >= 0.02;
    if (isFixedCase) { if (now !== 'Vol Expansion') wrongFix.push([r, v, now]); }
    else if (was === now) same++;
    else changed.push([r, v, was, now]);
  }
  ok(changed.length === 0, 'every other state labels exactly as the old ladder (' + same + ' checked)',
    JSON.stringify(changed.slice(0, 3)));
  ok(wrongFix.length === 0, 'flat returns with vol RISING 2pp now reads Vol Expansion, not Compression',
    JSON.stringify(wrongFix.slice(0, 3)));
  ok(tv(0, -0.03).name === 'Vol Compression', 'flat returns with vol FALLING 2pp still reads Vol Compression');

  // The label on the card is the rule the panel highlights.
  const vPanel = d.getElementById('why-verdict');
  const vFired = [...vPanel.querySelectorAll('.rd-rule.fired')];
  const heroLabel = text(home.querySelector('.card:nth-of-type(2) [data-why="why-verdict"]'));
  ok(vFired.length === 1, 'exactly one verdict rule is marked');
  ok(vFired[0] && heroLabel.includes(text(vFired[0].querySelector('b'))),
    'the highlighted verdict rule is the label on the card', text(vFired[0] && vFired[0].querySelector('b')));

  // The trajectory charts moved INTO this panel rather than off the site.
  ['Rolling 5d return', 'Rolling 20d return', 'Annualized vol', '60d drawdown']
    .forEach((l) => ok(vPanel.innerHTML.includes('>' + l + '</text>'), `verdict panel plots "${l}"`));

  // ── the rest moved to Analysis ───────────────────────────────────────────
  w.location.hash = '#analysis';
  setTimeout(() => {
    console.log('\n== the rest moved to Analysis, not deleted ==');
    const a = d.getElementById('v-analysis');
    const acards = [...a.querySelectorAll('.card > h2')].map((h) => h.textContent);
    ok(acards.some((t) => /Macro dashboard/.test(t)), 'the macro dashboard is on Analysis', JSON.stringify(acards));
    ok(acards.some((t) => /Cross-Asset Signals/.test(t)), 'the cross-asset signals are on Analysis');
    // Books moved to PAPA 2026-07-29; a frozen "YTD" strip read as live (removed 2026-09-24).
    ok(!/Paper portfolios YTD/.test(text(a)), 'no frozen paper-portfolio strip on Analysis');
    ok(/SPY next \d+ sessions, from the analog days/.test(text(a)),
      'the analog distribution tile says what it measures');
    ok(!/Stock Return Distribution/.test(text(a)), 'the old top-30-stocks tile is gone');
    ok((text(a).match(/not investment advice/g) || []).length === 1,
      'embedded sections do not stack their own disclaimer footers');

    console.log('\n== console errors ==');
    ok(errors.length === 0, 'no page errors (' + errors.join('; ') + ')');
    console.log(`\n${pass} passed, ${fail} failed`);
    process.exit(fail ? 1 : 0);
  }, 700);
}, 1500);
