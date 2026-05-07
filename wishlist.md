# Wishlist

Items for the daily improvement agent to implement — one per run. Move to Done when applied.

## Pending

- **Sparklines on home KPIs** — draw a tiny SVG spark line next to each SPY metric showing the last 20 values (use inline path data from SNAPSHOT)
- **Dark/light mode toggle** — add a button in the topbar that toggles a `.light` class on `<body>` and persists to localStorage
- **Keyboard shortcuts modal** — press `?` to show a modal listing all hash-nav shortcuts (1–9, 0 for methodology)
- **Column sort on stocks table** — clicking a column header in #stocks re-sorts the table client-side
- **Copy-to-clipboard button** — a small button on each stock row that copies `TICKER edge p50` as plain text
- **Analog stats panel** — show the count and date range of analog matches in a summary card in #analog
- **Aggregate risk score** — compute a 0–100 composite from the 7 risk scores and display it prominently in #risks
- **Winner/loser badges** — highlight the top 3 and bottom 3 sectors in #sectors with a small trophy / warning icon
- **Timestamp in topbar** — show the build timestamp and a "stale" warning if generated date is more than 2 days ago
- **Jargon glossary** — add a collapsible glossary section to #methodology defining edge, analog, hit rate, breadth, persistence
- **Regime streak counter** — track how many consecutive days the current regime label has held; show in #regime
- **Print stylesheet** — add a `@media print` block that forces white background, black text, hides topbar nav

## RIA / Advisor-focused — Done in #advisor view

- **Advisor view (#advisor)** — 2026-05-07: full advisor page with SVG charts, signal table, watchlist, export, disclosure
- **SPY momentum line chart** — rolling 20d return and annualized vol over last 20 sessions
- **Sector edge bar chart** — horizontal SVG with factor tilt labels and winner/loser badges
- **Risk axes chart** — horizontal bar chart for all 7 risk axes colored by severity
- **Annualized edge** — shown alongside raw edge in advisor signal table
- **Signal confidence badge** — Low/Med/High from hit_rate × log(n_obs)
- **Factor tilt labels** — Growth/Value/Quality/Cyclical/Defensive/Income/Speculative per sector
- **Watchlist filter** — type tickers to filter signal table to client holdings; persists to localStorage
- **Export CSV** — data-URI download of signal table
- **Compliance disclosure** — full disclaimer footer on advisor view; configurable via SNAPSHOT.config

## RIA / Advisor-focused — Still pending

- **Meeting prep view (#meeting)** — a new 11th view that is a single-page client-meeting summary: regime headline, top 3 sectors with plain-English rationale, composite risk level, and a "what to watch" list. Designed to print on one page or paste into a client letter.
- **Watchlist overlay** — a text input in the topbar (or #stocks view) where an advisor pastes comma-separated tickers; JS filters the stocks table to show only those positions, highlighting which have positive or negative analog edge. Persists to localStorage.
- **Horizon selector filter** — a toggle on #stocks and #sectors to filter by horizon (5d / 20d / 60d / 120d); RIAs typically care about 60d+ for quarterly framing; default remains 20d.
- **Meeting prep view (#meeting)** — a new 11th view that is a single-page client-meeting summary: regime headline, top 3 sectors with plain-English rationale, composite risk level, and a "what to watch" list. Designed to print on one page or paste into a client letter.
- **Watchlist overlay** — a text input in the topbar (or #stocks view) where an advisor pastes comma-separated tickers; JS filters the stocks table to show only those positions, highlighting which have positive or negative analog edge. Persists to localStorage.
- **Horizon selector filter** — a toggle on #stocks and #sectors to filter by horizon (5d / 20d / 60d / 120d); RIAs typically care about 60d+ for quarterly framing; default remains 20d.
- **Regime comparison table** — in #analog, add a table showing the top 5 most similar historical dates with their regime label, the subsequent SPY 20d return, and whether equities were broadly up or down; gives advisors concrete historical precedents to cite.

## Done

- **Risk-first narrative reorder** — 2026-05-07: Risk/Reversal card now appears before Constructive Read in #narrative; fiduciary framing
- **Tail risk emphasis** — 2026-05-07: "Adverse: p10%" callout below each distribution bar in #stocks; color-coded red/green
- **Sector allocation delta** — 2026-05-07: second card in #sectors showing SPX benchmark weight and Overweight/Underweight/Neutral tilt per sector
- **Annualized edge label** — 2026-05-07: in #stocks table, ann. edge shown in muted text next to raw edge
- **Signal confidence badge** — 2026-05-07: Low/Med/High badge in #advisor signal table from hit_rate × log(n_obs)
- **Factor tilt labels** — 2026-05-07: Growth/Value/Quality/Cyclical/Defensive/Income/Speculative labels in #advisor signal table
- **Compliance disclaimer footer** — 2026-05-07: full disclosure card in #advisor; uses SNAPSHOT.config.disclaimer and firm_name if present
- **Export signals to CSV** — 2026-05-07: data-URI CSV download in #advisor
- **Aggregate risk score composite display** — 2026-05-07: computed 0–100 composite from 7 risk scores, displayed in #risks view
- **Sparklines on home KPIs** — 2026-05-07: SVG polylines on SPY 5d/20d/vol/drawdown in regime banner; driven by spy.history in SNAPSHOT
- **Dark/light mode toggle** — 2026-05-07: ☀/🌙 button in topbar, persists to localStorage, full CSS overrides
- **Keyboard shortcuts modal** — 2026-05-07: press ? for modal with 1–9/0 nav shortcuts and d for theme toggle
- **Column sort on stocks table** — 2026-05-07: click any column header in #stocks to sort; direction toggles on repeat click
- **Copy-to-clipboard button** — 2026-05-07: 📋 button per stock row copies "TICKER edge:X p50:Y"
- **Analog stats panel** — 2026-05-07: stats cards in #analog showing count, date range, and match count
- **Winner/loser badges** — 2026-05-07: 🏆 on top 3 sectors, ⚠️ on bottom 3 in #sectors
- **Timestamp in topbar** — 2026-05-07: generated date shown; yellow "● stale" warning if >2 days old
- **Jargon glossary** — 2026-05-07: collapsible <details> section at bottom of #methodology with 7 definitions
- **Regime streak counter** — 2026-05-07: consecutive days in current regime shown in banner and #regime table; computed from spy_history
- **Print stylesheet** — 2026-05-07: @media print block with white bg, black text, hidden nav buttons
