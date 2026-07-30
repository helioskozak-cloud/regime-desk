# News tab — redesign spec

Written 2026-07-30. Scoped as a standalone project, to be run against this repo.

## Why

The News tab today is **news-desk's UI, ported wholesale**. `build/build_news_tab.py`
fetches news-desk's page, scopes every CSS rule under `#v-news`, and re-emits its
markup and JS inside a boot wrapper. That was the right call for getting it in
front of a user quickly, and it works — but it has three costs that are now the
visible problem:

1. **It does not use the width.** `#main` was widened to 1760px. news-desk's feed
   was designed for a narrow standalone page: `.row` is
   `grid-template-columns:54px 76px 1fr 130px`. Stretched to 1760px the headline
   column is mostly empty and the meta column floats far right.
2. **It speaks a different visual language.** Every other tab uses `.card`
   (`background:#161b22; border:1px solid #30363d; border-radius:2px;
   padding:13px 14px`), used 64 times. The News tab is full-bleed terminal
   chrome with hardcoded near-blacks (`.tabs` `#050505`, `.toolbar` `#080808`)
   that the palette remap could not reach.
3. **The ticker integration is invisible until hover.** Rows render a bare
   symbol. All the data regime-desk already has — price, session change, edge,
   horizon — only appears via the global `[data-ticker]` hover.

## The architectural decision

**Stop porting news-desk's UI. Consume its DATA.**

regime-desk already fetches news-desk's JSON at runtime:

```
https://helioskozak-cloud.github.io/news-desk/data/headlines.json
https://helioskozak-cloud.github.io/news-desk/data/stocks.json
```

Render the feed natively, as a regime-desk view, from those two files. This
deletes an entire class of problem discovered on 2026-07-30 (see Traps below):
no CSS scoping, no class collisions, no boot wrapper, no handler-exposure
hazard, no vendored SheetJS, and no re-port every time news-desk's shell
changes — which it has done 12 times in 60 days.

`build/build_news_tab.py` is **retired** by this work, not extended. Delete it
and its markers once the native view ships.

## Data contracts

`headlines.json` — the feed. Each entry carries at least:
`title`, `link`, `source`, `published`, `tickers[]`, `type`, `sentiment`,
`summary`. Refreshed by news-desk's own cron **every 5 minutes**; the tab must
keep polling rather than baking headlines in at build time. That liveness is the
whole reason the tab is merged rather than framed.

`window.SNAPSHOT` — already in the page, rebuilt by each daily build:
- `SNAPSHOT.stocks` — 100 entries, the richest: `ticker, name, sector, price,
  change_pct, edge, horizon, p10..p90, hit_rate, hit_alpha, hit_self, beta,
  market_cap, avg_volume, week_closes`
- `SNAPSHOT.all_signals` — 142 entries, signal fields but **no price**

**`change_pct` is a fraction over ONE SESSION**, from `scan/ci_scan.py`:
`(curr - prev) / prev` on the last two closes. AMD's `0.137` is **+13.7%**, not
+0.14%. Render as `(change_pct*100).toFixed(2)+'%'`, green `#3fb950` /
red `#f85149`, matching the rest of the page. Do not label it "today" without
checking the feed's own date — it is last-close-over-previous-close.

Coverage is partial by design: ~100 of the feed's tickers have price data, and
the feed tags many more. **A ticker with no data must render as a bare symbol,
not as a zero or a dash that reads like flat.**

## What to build

- The feed in the `.card` idiom, aligned to the same column as every other tab.
- A row layout that uses 1760px. The empty middle-right is the thing being
  fixed; candidates include surfacing the summary inline, widening the ticker
  cell to carry price + session change, and giving source/type a real column
  rather than a right-floated afterthought.
- **Ticker data inline, not on hover**: price and session change beside the
  symbol wherever `SNAPSHOT` has them, in the house colours.
- Search, source filter, type filter and clear — the reason for merging rather
  than framing, so they must survive.
- NEWS / MY BOOK as-is in behaviour: MY BOOK filters to the watchlist, seeded
  from `rd-watchlist` (see Traps), with upload/paste as the fallback.
- Holdings upload: **.xlsx and .csv both required.** CSV parses natively;
  .xlsx uses the vendored `docs/vendor/xlsx.full.min.js`, loaded same-origin and
  lazily. Keep that arrangement — do not reintroduce a CDN.

## Must not break

- **Self-contained.** No external `<script src>`, no cross-origin `.src`
  assignment, no third-party fetch beyond the two news-desk data URLs the
  validator already allows. `build/validator.py` enforces all three; a build
  that fails validation silently keeps the previous page (see Traps).
- **The 5-minute liveness.** Headlines must stay fetched at runtime.
- **`#v-news` isolation.** Whatever replaces the port must not leak styles into
  the other tabs. The current generator's scope check exists for a reason.
- **Ticker coverage honesty.** Never show a number for a ticker that has none.

## Acceptance

1. No horizontal scrollbar at 1366px or at 2560px.
2. Every interactive control works — clicked, not merely present. The 07-30 bug
   was controls that rendered perfectly and did nothing.
3. A ticker with `SNAPSHOT` data shows price and session change without hover; a
   ticker without shows a bare symbol.
4. Headlines still update within ~5 minutes of news-desk publishing.
5. `python -c "import sys;sys.path.insert(0,'build');from validator import
   validate;validate(open('docs/index.html',encoding='utf-8').read())"` passes.
6. `.xlsx` and `.csv` holdings upload both still populate MY BOOK.
7. `build/build_news_tab.py` and its `@@NEWS-TAB-*@@` markers are gone.

## Traps found on 2026-07-30 — read before starting

- **Annex B block-scoped functions.** The generator exposed handlers
  (`window.switchView = switchView`) *before* the block that declared them. A
  `function` declared inside a block only gets a function-scoped binding holding
  `undefined` until the block runs, and reading it early is legal — so
  `undefined` was copied onto `window` with no error, and every inline `on*`
  handler in the tab was dead while the feed rendered fine.
- **Two watchlists.** news-desk persists to `nd-prefs-v1`; regime-desk keeps
  `rd-watchlist`. MY BOOK read the empty one and showed 0 forever.
- **SheetJS came from a CDN** and was stripped as an external script, so uploads
  waited on an `XLSX` that never arrived — including CSV, which news-desk also
  routes through `XLSX.read()`.
- **A failed validation is silent.** `build.py` rolls back and keeps the previous
  HTML; the commit step then finds nothing staged and the run goes green. The
  dashboard sat frozen at "generated 2026-07-29" for a full day through six
  green runs a day. `_report_frozen()` now emits a GitHub error annotation —
  keep that behaviour.
- **The improver is dead**, unrelated: `ANTHROPIC_API_KEY` has no credit since
  07-12, so every build logs an improvement failure. Ignore it; it fails loudly
  and rolls back correctly.

The common thread in four of the six bugs fixed that day: something looked
completely fine while doing nothing. Prefer loud failure to graceful degradation
anywhere a user could mistake broken for empty.

## Current state

`12abaa9` shipped a stop-gap "blend layer" appended by the generator — it
re-themed `.tabs`/`.toolbar`/`.grp` to the page variables and made the view
full-bleed by cancelling `#main`'s padding. **That pushed toward terminal chrome,
the opposite of the `.card` direction above.** Delete it as part of this work
rather than building on it.
