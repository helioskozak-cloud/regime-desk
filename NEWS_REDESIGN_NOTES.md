# News tab redesign — working notes

Branch: `news-redesign` (from `origin/main` @ `1136a76`). **Never push to main.**
Spec: `NEWS_TAB_REDESIGN.md` (authoritative). This file is the running log.

Written for someone starting cold. Last updated: 2026-07-31, run 1 (05:0x UTC).

---

## Status

**In progress.** Reconnaissance done, implementation starting.

## What I established before writing code (all verified in-repo)

### The page's shape
- `docs/index.html` is one 41k-line self-contained file.
- Views are `<div class="view" id="v-NAME">` inside `#main`
  (`max-width:1760px;padding:20px 28px`). `#v-news` is at line ~256.
- Router: `renderers={...,news:renderNews}` → `route()` sets
  `el.innerHTML=renderers[view]()` once (`dataset.rendered`), then calls
  `window['_rd_postrender_'+view]()` if it exists. So the view renders exactly
  once and any wiring must happen in the postrender hook.
- House idiom: `.card{background:#161b22;border:1px solid #30363d;
  border-radius:2px;padding:13px 14px;margin-bottom:12px}` + `.card h2`
  (mono, 12px, uppercase, bottom border). Used 64×.
- A `MutationObserver` appends a `.popout-btn` to **every** `.card` under
  `#main`. Consequence for us: the feed must re-render into an inner
  container, never by replacing the card's own `innerHTML`, or the pop-out
  button gets destroyed on every poll.
- `#rd-tip` is regime-desk's own global hover tooltip, bound to
  `[data-ticker]` anywhere on the page. It already renders price, session
  change (`(change_pct*100).toFixed(2)`), edge, median, hits — and it
  `return`s early when the ticker has no SNAPSHOT entry, i.e. it is already
  honest about coverage. So putting `data-ticker` on our symbols gives the
  rich hover for free; the redesign's job is the *inline* numbers.

### The data
- `window.SNAPSHOT.stocks` — 100 entries. `window.SNAPSHOT.all_signals` —
  **152** entries (the spec says 142 and says all_signals has *no price*;
  **both are now out of date**: every one of the 152 carries `price`,
  `change_pct` and `week_closes`). all_signals is a strict superset of
  stocks by ticker (union = 152). So the inline price map is built from
  all_signals first, then stocks overwriting — 152 covered tickers, not 100.
- `change_pct` units **confirmed as a fraction**, not a percent:
  `scan/ci_scan.py:741` writes `round((curr - prev) / prev, 4)` into
  `price_data.json`; `build/snapshot_builder.py:377` copies that straight
  into both `stocks` and `all_signals`. Observed range in the shipped
  snapshot: `-0.1701 … +0.2044`. Render `*100`, green `#3fb950` /
  red `#f85149`.
- `headlines.json` fields used: `title, link, source, published, tickers[],
  type, sentiment, summary`; envelope also has `generated` and `ticker_names`.

### Egress is blocked — the one thing I could not verify
`https://helioskozak-cloud.github.io/**` is **denied by this session's egress
policy** (proxy answers 403 to CONNECT; confirmed in
`$HTTPS_PROXY/__agentproxy/status` under `recentRelayFailures`). Per
`/root/.ccr/README.md` that is an org policy denial, not something to route
around. So I could not fetch `headlines.json` / `stocks.json` and could not
check news-desk's own field units.

That matters for exactly one decision: **news-desk's `stocks.json` also has a
`change_pct`, and the ported code renders it as `change_pct.toFixed(2)+'%'`
— i.e. news-desk treats it as already-percent, the opposite of SNAPSHOT's
fraction.** I cannot confirm which is right without fetching the file, and
guessing wrong is a silent 100× error — the exact failure the spec's Traps
section is about. Decision: **inline price and session change come from
SNAPSHOT only** (units verified in-repo). That is also literally what
acceptance criterion #3 asks for ("a ticker with `SNAPSHOT` data shows price
and session change"), and the spec's own Data-contracts section lists
`headlines.json` + `window.SNAPSHOT` — not `stocks.json`. `stocks.json` is
still fetched at runtime and used for non-numeric fields only. If a later run
can reach the host, verify the units and widen coverage from it.

## Plan

1. Native `renderNews()` returning regime-desk `.card` markup; wiring in
   `_rd_postrender_news`.
2. **No inline `on*` attributes anywhere** — event delegation on `#v-news`
   plus direct listeners on the static control card. This deletes the entire
   Annex B / handler-exposure trap class rather than working around it.
3. Row grid that uses 1760px: TIME | TICKER+price+change | HEADLINE+summary
   | TYPE | SOURCE.
4. Keep: search, source filter, type filter, CLR, NEWS/MY BOOK, ticker
   click-to-filter, .csv + .xlsx holdings upload (vendored SheetJS, lazy,
   same-origin), 60s polling.
5. Book seeding order: uploaded/pasted book (`rd-news-book`) → legacy
   `nd-prefs-v1` → `rd-watchlist` (session-only seed).
6. Delete `build/build_news_tab.py`, the `@@NEWS-TAB-*@@` markers, the ported
   CSS/JS, and the blend layer — only once the native view actually works.

## Testing approach

Rendering is not evidence. Tests run the real `docs/index.html` in **jsdom**
with `fetch` stubbed to serve a synthetic `headlines.json`, then *click*
things and assert on resulting DOM — tabs, search, both selects, CLR, ticker
chips, paste, CSV upload.

## Left to do

- Everything below "Plan".
