# Wishlist

Items for the daily improvement agent to implement — one per run. Move to Done when applied.

## Pending

- **Bubble Watch upgrades** — the base #bubble view was built by hand on 2026-07-13 (improver was down: API credits exhausted). Candidate follow-ups, one per run: (a) custom hover tooltip card (currently native SVG `<title>`), (b) a third mini-panel plotting the index-vs-median-member gap over time, (c) light-theme color audit of the two SVG panels.

<!-- original spec for reference; base view is DONE, do not rebuild: new hash-routed view (`id="v-bubble"`) from `SNAPSHOT.bubble_watch` (`{as_of, meta, years: [{year, partial, n_members, coverage_pct, pct_doubled, pct_halved, n_doubled, n_halved, pct_up50, pct_down30, median_ret, sp500_ret, nasdaq_ret, top5, bottom5}]}`). Add "Bubble" to the nav bar; show a "Bubble data not yet available" banner if `bubble_watch` is empty. Layout: (1) Intro line: "Share of S&P 500 members that doubled (≥+100%) or halved (≤−50%) each year, point-in-time membership — the dot-com signature was both rising together under a rising tape." (2) Stat tiles: current-year doublers count + %, current-year halvers count + %, and a "flip status" tile — "flip" = pct_halved > pct_doubled, the 2000 top-marker; show "Not lit" in green or "LIT" in red using the latest year row. (3) The centerpiece: two side-by-side SVG diverging bar panels, "Dot-com era 1995–2002" (years ≤2002) and "AI era 2021–now" (years ≥2021), shared y-scale: for each year, pct_doubled as a bar above the zero baseline (blue), pct_halved below (red); year labels under each column, partial year marked with an asterisk; hover/tap a column shows a tooltip with counts, coverage_pct, sp500_ret, median_ret, and top5/bottom5 tickers. (4) A "narrowness" row under each panel: per year, sp500_ret minus median_ret in small text (the 1999 extreme was a 20-pt gap). (5) Methodology footnote from `meta.survivorship_note` + `meta.method`, and per-year coverage_pct in the tooltip — dot-com era bars are survivor floors, say so plainly. Keep the styling consistent with existing views (same card/panel classes). -->

## Done

- **Bubble Watch view (#bubble)** — 2026-07-13: built by hand (improver down, API credits). Nav entry, stat tiles (doubled/halved YTD, flip status, churn-vs-1999), two SVG diverging bar panels (dot-com vs AI era) with native tooltips + Δ narrowness row, survivorship-caveat method card. Data: SNAPSHOT.bubble_watch from scan/bubble_scan.py.
- **Stock Memory view (#memory)** — was already implemented (renderMemory + nav + router present); entry moved out of Pending 2026-07-13 to stop the improver rebuilding it.
- **Paper Portfolios view (#portfolios)** — was already implemented (renderPortfolios + v1/v2 toggle present); entry moved out of Pending 2026-07-13 to stop the improver rebuilding it.

- **Regime comparison table** — 2026-05-07: in #analog, table of top 5 historical precedents with date, regime label, SPY +20d return (color-coded), and Equities Up/Down badge; synthetic illustrative rows keyed to current regime until ci_scan.py writes analog_matches to spy_state.json

- **Watchlist overlay** — 2026-05-07: text input in #stocks view; filters to client holdings; green/red row tint for edge direction; "no signal data" row for unmatched tickers; synced with advisor watchlist via shared _watchlist state; persists to localStorage
- **Horizon selector filter** — 2026-05-07: [ All / 5d / 20d / 60d / 120d ] toggle on #stocks and #sectors; sectors dynamically recomputed from filtered stock list client-side
- **Meeting prep view (#meeting)** — 2026-05-07: single-page client-meeting brief with regime summary, key metrics, top 3 sectors with plain-English rationale, dynamic "what to watch" list, composite risk level, print button, disclosure
- **Risk-first narrative reorder** — 2026-05-07: Risk/Reversal card now appears before Constructive Read in #narrative; fiduciary framing
- **Tail risk emphasis** — 2026-05-07: "Adverse: p10%" callout below each distribution bar in #stocks; color-coded red/green
- **Sector allocation delta** — 2026-05-07: second card in #sectors showing SPX benchmark weight and Overweight/Underweight/Neutral tilt per sector
- **Advisor view (#advisor)** — 2026-05-07: full advisor page with SVG charts, signal table, watchlist, export, disclosure
- **SPY momentum line chart** — 2026-05-07: rolling 20d return and annualized vol over last 20 sessions
- **Sector edge bar chart** — 2026-05-07: horizontal SVG with factor tilt labels and winner/loser badges
- **Risk axes chart** — 2026-05-07: horizontal bar chart for all 7 risk axes colored by severity
- **Annualized edge label** — 2026-05-07: shown in #stocks table and #advisor signal table
- **Signal confidence badge** — 2026-05-07: Low/Med/High badge in #advisor signal table from hit_rate × log(n_obs)
- **Factor tilt labels** — 2026-05-07: Growth/Value/Quality/Cyclical/Defensive/Income/Speculative labels in #advisor
- **Watchlist filter** — 2026-05-07: type tickers to filter advisor signal table; persists to localStorage
- **Export CSV** — 2026-05-07: data-URI download of signal table in #advisor
- **Compliance disclosure** — 2026-05-07: full disclaimer footer on advisor view; configurable via SNAPSHOT.config
- **Aggregate risk score composite display** — 2026-05-07: 0–100 composite from 7 risk scores, displayed in #risks
- **Sparklines on home KPIs** — 2026-05-07: SVG polylines on SPY 5d/20d/vol/drawdown in regime banner
- **Dark/light mode toggle** — 2026-05-07: ☀/🌙 button in topbar, persists to localStorage
- **Keyboard shortcuts modal** — 2026-05-07: press ? for modal with 1–9/0 nav shortcuts and d for theme toggle
- **Column sort on stocks table** — 2026-05-07: click any column header in #stocks to sort
- **Copy-to-clipboard button** — 2026-05-07: 📋 button per stock row copies "TICKER edge:X p50:Y"
- **Analog stats panel** — 2026-05-07: stats cards in #analog showing count, date range, match count
- **Winner/loser badges** — 2026-05-07: 🏆 on top 3 sectors, ⚠️ on bottom 3 in #sectors
- **Timestamp in topbar** — 2026-05-07: generated date shown; yellow "● stale" warning if >2 days old
- **Jargon glossary** — 2026-05-07: collapsible section at bottom of #methodology with 7 definitions
- **Regime streak counter** — 2026-05-07: consecutive days in current regime shown in banner and #regime
- **Print stylesheet** — 2026-05-07: @media print block with white bg, black text, hidden nav buttons
