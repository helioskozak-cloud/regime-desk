# Wishlist

Items for the daily improvement agent to implement — one per run. Move to Done when applied.

## Pending

- **Horizon selector filter** — a toggle on #stocks and #sectors to filter by horizon (5d / 20d / 60d / 120d); RIAs typically care about 60d+ for quarterly framing; default remains 20d.
- **Watchlist overlay** — a text input in the topbar (or #stocks view) where an advisor pastes comma-separated tickers; JS filters the stocks table to show only those positions, highlighting which have positive or negative analog edge. Persists to localStorage.
- **Regime comparison table** — in #analog, add a table showing the top 5 most similar historical dates with their regime label, the subsequent SPY 20d return, and whether equities were broadly up or down; gives advisors concrete historical precedents to cite. (Requires backend: snapshot_builder must compute forward SPY returns per analog date.)

## Done

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
