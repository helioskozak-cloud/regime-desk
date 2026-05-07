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

## Done

(Agent moves items here with the date applied)
