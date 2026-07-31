# Home re-org — spec

Written 2026-07-31 from Helios' feedback on desk1–desk6. Not started.

> "the top three bars are all too stretched for how much info they convey, same
> thing for the 20 day spy. The cross-asset signals and risk axes&invalidation
> look good on their own but share no common theme. Also, if we're going to call
> something a risk axis it probably makes sense to show some detail on that axis
> beyond (but still including) a single percentage"

Direction, his words: **"compression of the visual aspects or improvement of
data coverage to utilize blank space."** Either is acceptable. Both are better
than what is there.

This is a RE-ORG, not a restyle. A spacing pass ran on 2026-07-31 and he said it
"looks almost exactly the same" — correctly, because the problem is what is on
the page and how many times, not how far apart it sits.

## 1. The same numbers are on screen three times

Measured from desk1/desk2. Seven readings — regime + streak, SPY 5d, SPY 20d,
20d vol, 60d drawdown, breadth, persistence, reversal risk — appear in:

- the **stats strip** (bar 2), as sparkline tiles
- the **REGIME ANALYSIS card**, ~200px below, as large tiles with bars
- **CROSS-ASSET SIGNALS**, for the SPY 5d/20d rows, with context prose

The strip and the card are the same eight readings twice, and the strip renders
on **every tab** — including Bubble and News, where it means nothing.

Note one real inconsistency while you are in here: the strip reads `VOL 20D
0.8%` while the card reads `20D VOL (ANN.) 13%`. Raw versus annualised, same
label family, no indication which is which.

Pick ONE home for these. The card is more readable; the strip is more compact
and survives scrolling. Do not keep both.

## 2. Three stacked bars before any content

Topbar, stats strip, then a "SINCE YESTERDAY" strip carrying four deltas. Three
full-width rows, roughly 150px, before the first real panel. The third is four
numbers.

## 3. Risk axes are not axes — and the fix is already in the repo

`AGGREGATE RISK SCORE` shows seven axes as a percentage and a bar. Below it,
`RISK AXES & INVALIDATION LEVELS` says "Each risk axis has an associated
invalidation condition — the signal that would indicate the risk has
materialized."

**These are the same seven axes, split across the page.** The detail Helios is
asking for already exists; it is just not next to the number.

Merge them. Each axis should show its reading, where that reading sits on its
range, and the invalidation condition that would say the risk has arrived.

**The Bubble tab is the model — copy it.** Its five markers already do exactly
this:

> `2.4% of members doubled so far this year (trigger ≥4%; 1999 printed 5.8%)`

Reading, threshold, historical reference, and a status chip. That is an axis. A
bare `83%` is a scalar with an ambitious name.

## 4. ECON is showing an error over data that exists

The panel reads "Macro data not yet available — scan/econ_scan.py hasn't written
data/econ.json yet." But the 2026-07-31 build logged `[snapshot] Loaded econ: 6
series`, and `econ_scan.py` runs daily in `Daily evolve`.

So a full-width panel is spending its space on a false negative. Find out
whether the snapshot key and the renderer's key disagree. **Fix the plumbing, do
not delete the panel** — six macro series is exactly the "data coverage to
utilise blank space" he asked for.

## 5. Charts do not earn their width

`SPY TRAJECTORY — LAST 20 SESSIONS` is two sparse line charts across 1760px, and
he named the 20-day SPY specifically. Either compress them, or use the width for
something denser.

## Constraints

- `docs/index.html` is generated and rewritten several times a day by the daily
  build. Work on a branch and expect to rebase.
- **A validation failure is silent** — `build.py` rolls back, stages nothing, and
  the run still goes green. That froze this dashboard for a full day on
  2026-07-30. Run the validator and read the output.
- `build/validator.py` has `REQUIRED_VIEWS`, which errors if an `id="v-<name>"`
  disappears. Removing a view means updating that list in the same commit.
- The News tab was rebuilt natively on 07-31 and is the newest layout in the
  page. Where other tabs disagree with it, it is usually the better reference.
- Palette and typography are settled and NOT in scope.
- `tests/news_dom.test.js` must still pass — it exercises shared page scaffolding.

## Acceptance

1. No reading appears twice on the same screen without a stated reason.
2. Each risk axis shows its reading AND its invalidation condition together.
3. ECON either renders six series or explains a real failure.
4. Less vertical space before the first substantive panel than today.
5. No horizontal scrollbar at 1366 / 1920 / 2560.
6. Validator passes; `news_dom.test.js` passes.
