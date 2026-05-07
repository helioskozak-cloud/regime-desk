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
- **Tail risk emphasis** — in the distribution bars on #stocks, add a separate callout for p10 labeled "Adverse case" so advisors see the downside scenario first, not last.
- **Annualized edge label** — next to the raw 20d edge, show an annualized equivalent `(edge / h_days * 252)` in muted text; translates to language advisors already use in performance reporting.
- **Signal confidence badge** — derive a quality score from `hit_rate × log(n_obs)` and display it as Low / Medium / High next to each stock; helps advisors quickly filter out low-sample signals.
- **Sector allocation delta** — a card in #sectors that shows each sector's signal vs a standard 60/40 equity weight (e.g. Tech ~28%, Financials ~13%); framed as "overweight / underweight / neutral" relative to a benchmark allocation.
- **Regime comparison table** — in #analog, add a table showing the top 5 most similar historical dates with their regime label, the subsequent SPY 20d return, and whether equities were broadly up or down; gives advisors concrete historical precedents to cite.
- **Compliance disclaimer footer** — a configurable footer (text stored in SNAPSHOT.config.firm_name and SNAPSHOT.config.disclaimer) that appears on every view; defaults to generic language but can be customized per firm. Important for RIAs who share the dashboard with clients.
- **Export signals to CSV** — a "Download CSV" button on #stocks that uses a data-URI to trigger a client-side CSV download of the current filtered/sorted signals table; eliminates copy-paste into spreadsheets.
- **Risk-first narrative reorder** — reorder #narrative so the "Risk / Reversal" card appears before the "Constructive Read" card; reflects fiduciary duty framing where downside scenario is disclosed first.
- **Factor tilt labels** — tag each sector in #sectors with its dominant factor exposure (Growth / Value / Quality / Momentum / Defensive) based on a static lookup; helps advisors think about how a regime tilt interacts with their existing factor exposure.

## Done

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
