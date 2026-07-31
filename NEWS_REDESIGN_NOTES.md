# News tab redesign — working notes

Branch: `news-redesign` (from `origin/main` @ `1136a76`). **Never push to main.**
Spec: `NEWS_TAB_REDESIGN.md` (authoritative). This file is the running log.

Written for someone starting cold. Last updated: 2026-07-31 run 2, ~08:2x UTC.

---

## Status: complete, independently re-verified, ready for review

Run 1 (05:0x UTC) built the native view and pushed it. Run 2 (this one) did not
add features — it re-verified the whole thing from scratch, on the theory that a
test suite written by the same run that wrote the code can agree with itself.
Everything run 1 claimed held up. No product bug was found in re-verification.

All seven acceptance criteria pass. The only unverifiable item is #4's live half
(egress to the news-desk host is blocked in this environment) — detail below.

## What shipped

`docs/index.html` only, plus a comment-only touch to `build/validator.py` and
the new `tests/`. The News tab is now a regime-desk view that consumes
news-desk's JSON instead of re-hosting its UI.

- **Markup/CSS.** Two `.card`s — controls, then feed — on `#main`'s 1760px
  column, in the house palette. The old scoped port (~30KB of news-desk CSS,
  its `:root` remap, and the 07-30 "blend layer") is gone; the new block is
  8.4KB and every rule is still prefixed `#v-news`.
- **Row grid.** `58px | 200px | minmax(0,1fr) | 108px | 154px` —
  time, ticker + price + session change, headline + inline summary, type,
  source. `minmax(0,1fr)` rather than `1fr` on the headline is what stops a
  long unbroken title forcing a horizontal scrollbar. Breakpoints at 1180px
  (source drops under the headline) and 820px (two columns, explicit
  placement).
- **Inline ticker data.** Price and session change beside the symbol, no hover
  needed. Secondary tickers become chips carrying their own % where known.
  Symbols keep `data-ticker`, so the page-wide `#rd-tip` still gives the rich
  hover for free.
- **No inline `on*` attributes at all** — asserted by both suites and again by
  run 2's independent harness (walks every element in `#v-news`, every
  attribute, finds zero). Every control is bound by delegated
  `addEventListener` on `#v-news`. This deletes the entire 07-30
  Annex-B/handler-exposure trap: there is no name for markup to call, so there
  is nothing that can silently resolve to `undefined`.
- **Kept:** search, source filter, type filter, clear, NEWS / MY BOOK,
  ticker click-to-filter (with an active-filter chip), `.csv` + `.xlsx`
  holdings upload, 60s polling, untagged headlines dropped.
- **New, small:** row expansion survives the 60s re-render; a stale/failed feed
  turns the live dot red and says so instead of showing an empty card.
- `window.NEWSTAB` is the tab's only global — a module object, needed because
  the whole page script is wrapped in an IIFE and nothing inside is otherwise
  reachable from a console or a test harness.

## The one thing that could not be verified

`https://helioskozak-cloud.github.io/**` is denied by this session's egress
policy (proxy answers 403 to CONNECT). Per `/root/.ccr/README.md` that is an
org policy denial, not something to route around. Both runs hit it. So the live
`headlines.json` / `stocks.json` were never fetched, and news-desk's own field
units could not be checked against the real file.

That matters for exactly one decision. news-desk's `stocks.json` has a
`change_pct`, and the code being replaced printed it as
`change_pct.toFixed(2)+'%'` — i.e. news-desk treats it as **already percent**,
the opposite of SNAPSHOT's fraction. Guessing wrong is a silent 100× error.
So **all inline numbers come from `window.SNAPSHOT`**, whose units are verified
in-repo (`scan/ci_scan.py:741` → `(curr - prev) / prev`;
`build/snapshot_builder.py:377` copies it into both `stocks` and
`all_signals`). `stocks.json` is still fetched at runtime and used for company
names only.

**If a later run can reach the host:** check whether news-desk's `change_pct`
is a fraction or a percent. If unambiguous, `stocks.json` could widen inline
coverage beyond SNAPSHOT's 152 tickers. Until then, uncovered tickers correctly
render bare.

## The spec's SNAPSHOT numbers are stale (in our favour)

Spec says `all_signals` is 142 entries with **no price**. Measured directly from
the shipped page in both runs:

    all_signals: 152, with price: 152
    stocks:      100, with price: 100
    stocks tickers not in all_signals: 0   → strict superset
    total priced tickers covered: 152

The price map is therefore built from `all_signals` first and `stocks` second
(richer fields win on overlap) — 152 covered tickers rather than 100. Not a
conflict with the spec's intent, just an out-of-date document; noted so nobody
"fixes" it back.

## Book / watchlist resolution order

The 07-30 trap was two watchlists in one page. Order, most specific first:

1. `rd-news-book` — uploaded or pasted here. Persisted.
2. `nd-prefs-v1` — a book left behind by the ported tab. Migrated once.
3. `rd-watchlist` — regime-desk's own. Session seed, never written back.
4. `SNAPSHOT.watchlist` — this build's. Session seed.

Seeds are labelled as seeds in the UI. "Clear book" is remembered (`cleared`
is persisted); "Replace book" only opens the upload panel, so backing out of
it restores the seed rather than silently discarding it.

Consequence worth knowing when testing: because the book seeds, MY BOOK opens
on the filtered feed, **not** the upload panel. To reach the upload panel you
click "Replace book" (or "Clear book") first. Run 2's harness initially failed
here and the behaviour, not the harness, was right.

## Testing — `tests/`, see `tests/README.md`

Rendering is not evidence, so every harness drives the real `docs/index.html`
and asserts on state *after* events.

    npm i jsdom playwright     # not vendored; node_modules/ is gitignored
    node tests/news_dom.test.js       # 80 assertions
    node tests/news_layout.test.js    # 36 assertions, real Chromium

- `tests/news_dom.test.js` — **80 assertions, 80 passing** (re-run in run 2 on a
  clean container). jsdom, `fetch` stubbed with a fixture built from the page's
  own SNAPSHOT. Covers every control by clicking it, `change_pct`
  sign/colour/×100, bare-symbol honesty, zero inline `on*` attributes, `.csv`
  and `.xlsx` upload through the actual vendored SheetJS, SheetJS staying
  unloaded until a spreadsheet is dropped, book seeding, a deliberate feed
  outage, and the pop-out button surviving a re-render.
- `tests/news_layout.test.js` — **36 assertions, 36 passing** (re-run in run 2).
  Real Chromium (`/opt/pw-browsers/chromium`), `docs/` served over localhost,
  news-desk fetches intercepted. Acceptance #1 at 1366 / 2560 / 1180 / 820 /
  390: no document-level horizontal scroll and no element escaping the viewport
  at any of them; feed card aligns with Home's card to the pixel; interactions
  repeated in a real browser as a cross-check on jsdom.

Run 2 additionally wrote and ran two throwaway harnesses (scratchpad, not
committed — the committed suites already cover the same ground) that were
written without reference to the existing tests: **49 assertions** re-deriving
every acceptance criterion, and **19 assertions** round-tripping a genuine
`.xlsx` workbook — generated in-process with the vendored SheetJS — through the
real `#nd-file` input, plus the same for `.csv`. All 68 passed.

Neither committed suite is wired into CI — nothing under `.github/` was touched.

## Acceptance, line by line — as re-verified in run 2

| # | Criterion | Result | How |
|---|---|---|---|
| 1 | No horizontal scrollbar at 1366 or 2560 | **PASS** | Real Chromium, measured `scrollWidth` vs `clientWidth` and every element's bounding box, at 1366/2560/1180/820/390 |
| 2 | Every control works when clicked | **PASS** | Both tabs, search, both dropdowns, clear, ticker click + chip — driven by dispatched events in jsdom and by real clicks in Chromium; asserted on row counts *after* the event |
| 3 | Price+change inline where SNAPSHOT has it, bare where not | **PASS** | Priced rows print `(chg*100).toFixed(2)%` in `#3fb950`/`#f85149`; unpriced rows carry no `.nd-px`, no `.nd-chg`, no `0.00`, no dash |
| 4 | Headlines update within ~5 min | **PARTIAL** | `setInterval(load, POLL_MS)`, `POLL_MS=60000`, fetched at runtime — verified. Re-render on new data and recovery-after-outage verified. **Not** verified against the live host: egress blocked |
| 5 | Validator passes | **PASS** | Command below, real output |
| 6 | `.xlsx` and `.csv` both populate MY BOOK | **PASS** | Real workbook built with the vendored SheetJS, pushed through the real file input; both populate, both drop cash-like rows, both persist |
| 7 | `build_news_tab.py` and its markers gone | **PASS** | File deleted; 0 occurrences of `@@NEWS-TAB`, `_ndBoot`, `_ndMarkup` outside `history/` (an archived 07-30 snapshot, deliberately untouched) |

Validator, run 2, verbatim:

    $ python -c "import sys;sys.path.insert(0,'build');from validator import validate;validate(open('docs/index.html',encoding='utf-8').read());print('OK')"
    OK

Self-contained checks: the only remote origin the news block references is
news-desk's two data URLs; SheetJS loads from the relative
`vendor/xlsx.full.min.js`, lazily, and `XLSX` is confirmed undefined until a
spreadsheet is actually dropped. (The `fonts.googleapis.com` stylesheet link in
`<head>` is pre-existing on `main` — 2 occurrences on both — and untouched by
this work.)

## Left to do

Nothing blocking.

- The `change_pct` units question above is the only open item, and it needs
  network access neither run had.
- **Nobody has seen this in a browser as a human.** Chromium measured it and
  screenshots were captured, but a human eye on spacing and density is still
  worth having before merge.
- Not touched, deliberately: `.github/workflows`, `data/`, `scan/`, any other
  repo. No deploy was run. Nothing was merged.
- `origin/main` had not moved since the branch point at either run
  (`1136a76`, the 07-30 daily build), so no rebase was needed and the branch
  merges cleanly. Worth a glance before merging in case the daily build lands
  first — if it conflicts inside `docs/index.html`, keep OUR News tab markup and
  CSS and take THEIRS for the `window.SNAPSHOT` blob.
