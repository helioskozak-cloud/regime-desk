# Regime Desk

A self-evolving market regime dashboard hosted on GitHub Pages.

## Structure

```
docs/index.html          — single self-contained dashboard (no CDN, no fetch)
build/build.py           — daily orchestrator: refresh → improve → validate → promote
build/snapshot_builder.py — converts data/ files to window.SNAPSHOT JS block
build/improver.py        — calls Claude API to apply one patch per run
build/validator.py       — static smoke-tests before promotion
scan/ci_scan.py          — downloads prices from yfinance, runs analog scan, writes data/
.github/workflows/daily.yml — cron at 11:00 UTC daily + workflow_dispatch
wishlist.md              — improvement ideas for the agent to pick from
changelog.json           — history of all builds
history/                 — archived HTML snapshots (rollback from here)
data/                    — written by ci_scan.py (not committed, generated fresh each run)
```

## Daily flow

1. **11:00 UTC**: GitHub Actions triggers `daily.yml`
2. `scan/ci_scan.py` downloads prices and writes `data/market_signals.csv`, `data/theme_summary.csv`, `data/spy_state.json`, `data/cross_asset.json`
3. `build/build.py` reads `docs/index.html`, refreshes `window.SNAPSHOT` from `data/`
4. `build/improver.py` calls Claude to apply one focused improvement from `wishlist.md`
5. `build/validator.py` checks the result; rolls back if anything fails
6. The new HTML is committed and GitHub Pages redeploys automatically

## Wiring real data

The scan runs automatically in CI. No manual steps needed once the workflow is active.

## Nudging the agent

Edit `wishlist.md` and commit. The agent picks from the Pending section on the next run.

## Rolling back

Pick any file from `history/` and copy it to `docs/index.html`, then commit.

## Secrets required

- `ANTHROPIC_API_KEY` — set via `gh secret set ANTHROPIC_API_KEY`
