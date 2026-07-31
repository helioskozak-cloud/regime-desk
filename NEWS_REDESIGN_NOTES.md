# News tab redesign — working notes

Branch: `news-redesign` (from `origin/main` @ `1136a76`). **Never push to main.**
Spec: `NEWS_TAB_REDESIGN.md` (authoritative). This file is the running log.

Written for someone starting cold. Last updated: 2026-07-31 run 1, ~05:4x UTC.

---

## Status: the native view works and is pushed

All seven acceptance criteria in the spec are met and tested. `docs/index.html`
passes the validator. `build/build_news_tab.py` is deleted and no
`@@NEWS-TAB-*@@` marker remains.

One thing could not be verified and one spec statement turned out to be stale —
both below, both flagged rather than worked around.

## What shipped

`docs/index.html` only. The News tab is now a regime-desk view that consumes
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
- **No inline `on*` attributes at all** — asserted by a test. Every control is
  bound by delegated `addEventListener` on `#v-news`. This deletes the entire
  07-30 Annex-B/handler-exposure trap: there is no name for markup to call, so
  there is nothing that can silently resolve to `undefined`.
- **Kept:** search, source filter, type filter, clear, NEWS / MY BOOK,
  ticker click-to-filter (with an active-filter chip), `.csv` + `.xlsx`
  holdings upload, 60s polling, untagged headlines dropped.
- **New, small:** row expansion survives the 60s re-render; a stale/failed feed
  turns the live dot red and says so instead of showing an empty card.
- `window.NEWSTAB` is the tab's only global — a module object, needed because
  the whole page script is wrapped in an IIFE and nothing inside is otherwise
  reachable from a console or a test harness.

## Two things the next run should know

### 1. Egress is blocked here — one decision rests on it
`https://helioskozak-cloud.github.io/**` is denied by this session's egress
policy (proxy answers 403 to CONNECT; see `recentRelayFailures` in
`$HTTPS_PROXY/__agentproxy/status`). Per `/root/.ccr/README.md` that is an org
policy denial, not something to route around. So the live `headlines.json` /
`stocks.json` were never fetched, and news-desk's own field units could not be
checked.

That matters for exactly one decision. news-desk's `stocks.json` has a
`change_pct`, and the code being replaced printed it as
`change_pct.toFixed(2)+'%'` — i.e. news-desk treats it as **already percent**,
the opposite of SNAPSHOT's fraction. Guessing wrong is a silent 100× error.
So **all inline numbers come from `window.SNAPSHOT`**, whose units are verified
in-repo (`scan/ci_scan.py:741` → `(curr - prev) / prev`;
`build/snapshot_builder.py:377` copies it into both `stocks` and
`all_signals`). `stocks.json` is still fetched at runtime and used for company
names only.

This matches acceptance #3 ("a ticker with `SNAPSHOT` data shows price and
session change") and the spec's Data-contracts section, which lists
`headlines.json` + `window.SNAPSHOT` and does *not* list `stocks.json`.

**If a later run can reach the host:** check whether news-desk's `change_pct`
is a fraction or a percent. If it is unambiguous, `stocks.json` could widen
inline coverage beyond SNAPSHOT's 152 tickers. Until then, uncovered tickers
correctly render bare.

### 2. The spec's SNAPSHOT numbers are stale (in our favour)
Spec says `all_signals` is 142 entries with **no price**. In the shipped
snapshot it is **152 entries, every one carrying `price`, `change_pct` and
`week_closes`**, and it is a strict superset of `stocks` by ticker. The price
map is therefore built from `all_signals` first and `stocks` second (richer,
wins on overlap) — 152 covered tickers rather than 100. Not a conflict, just an
out-of-date document; noted so nobody "fixes" it back.

## Book / watchlist resolution order

The 07-30 trap was two watchlists in one page. Order, most specific first:

1. `rd-news-book` — uploaded or pasted here. Persisted.
2. `nd-prefs-v1` — a book left behind by the ported tab. Migrated once.
3. `rd-watchlist` — regime-desk's own. Session seed, never written back.
4. `SNAPSHOT.watchlist` — this build's. Session seed.

Seeds are labelled as seeds in the UI. "Clear book" is remembered (`cleared`
is persisted); "Replace book" only opens the upload panel, so backing out of
it restores the seed rather than silently discarding it.

## Testing — `tests/`, see `tests/README.md`

Rendering is not evidence, so both harnesses drive the real `docs/index.html`
and assert on state *after* events.

- `tests/news_dom.test.js` — **80 assertions, all passing.** jsdom, `fetch`
  stubbed with a fixture built from the page's own SNAPSHOT. Covers every
  control by clicking it, `change_pct` sign/colour/×100, bare-symbol honesty
  (no price element, no change element, no `0.00`, no dash), zero inline `on*`
  attributes, `.csv` upload, `.xlsx` upload through the actual vendored
  SheetJS (a real workbook, generated in-test), SheetJS staying unloaded until
  a spreadsheet is dropped and then loading from a relative same-origin path,
  book seeding, a deliberate feed outage failing loudly, and the pop-out button
  surviving a re-render.
- `tests/news_layout.test.js` — **36 assertions, all passing.** Real Chromium
  (`/opt/pw-browsers/chromium`), `docs/` served over localhost, news-desk
  fetches intercepted. Acceptance #1 at 1366 / 2560 / 1180 / 820 / 390: no
  document-level horizontal scroll and no element escaping the viewport at any
  of them; feed card aligns with Home's card to the pixel; a few interactions
  repeated in a real browser as a cross-check on jsdom.

Neither is wired into CI — nothing was changed under `.github/`.

## Acceptance, line by line

| # | Criterion | State |
|---|---|---|
| 1 | No horizontal scrollbar at 1366 or 2560 | Verified in Chromium, plus 1180/820/390 |
| 2 | Every control works when clicked | Verified — every one, in jsdom and Chromium |
| 3 | Price+change inline where SNAPSHOT has it, bare symbol where not | Verified |
| 4 | Headlines update within ~5 min | 60s poll; re-render on new data verified. Not verified against the live host (egress blocked) |
| 5 | Validator passes | Passes |
| 6 | `.xlsx` and `.csv` both populate MY BOOK | Verified, real SheetJS |
| 7 | `build_news_tab.py` and its markers gone | Done — 0 occurrences of `@@NEWS-TAB`, `_ndBoot`, `_ndMarkup` |

## Left to do

Nothing blocking. If picking this up:

- The units question in §1 above is the only open item, and it needs network
  access this session did not have.
- Nobody has looked at this in a real browser as a human. Screenshots at 1366
  and 2560 were reviewed; a human eye on spacing would still be worth it.
- Not touched, deliberately: `.github/workflows`, `data/`, `scan/`, any other
  repo. No deploy was run. No PR opened.
