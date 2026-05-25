"""
Backfill signal_log.csv with historical scan results, resolve outcomes,
and replay all three paper portfolios through the same history.

Downloads 3y of prices once, replays the analog scan for each trading day
in the past BACKFILL_DAYS days. Idempotent: skips dates already in the log
that have p90/p10 populated. On a fresh rerun after schema change, re-scans
dates whose p90 is missing.

Usage:
    python backfill_signal_log.py            # default 90 days
    python backfill_signal_log.py --days 120
    python backfill_signal_log.py --force    # clear log and start over
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT / "scan"))

from ci_scan import (
    DATA_DIR, UNIV_FILE,
    MIN_EDGE, STABILITY_VOL_LIMIT, MIN_PRICE, PRICE_HISTORY_FRAC,
    SIMILAR_DAY_COUNT, EXCLUDE_RECENT_DAYS, MIN_OBSERVATIONS, HORIZONS,
    download_prices, compute_features, update_signal_memory, _is_leveraged,
)
from portfolio_manager import update_portfolios

BACKFILL_DAYS = 90
FORCE = "--force" in sys.argv
if "--days" in sys.argv:
    i = sys.argv.index("--days")
    BACKFILL_DAYS = int(sys.argv[i + 1])

FEATURES = ["return_5", "return_20", "volatility", "drawdown"]


def main():
    DATA_DIR.mkdir(exist_ok=True)

    if FORCE:
        for f in ("signal_log.csv", "signal_outcomes.csv", "stock_scores.csv", "portfolio.json"):
            p = DATA_DIR / f
            if p.exists():
                p.unlink()
                print(f"  Cleared {f}", flush=True)

    print("Loading universe ...", flush=True)
    sectors_df = pd.read_csv(UNIV_FILE)
    sectors_df["ticker"] = sectors_df["ticker"].str.upper().str.strip()
    before = len(sectors_df)
    sectors_df = sectors_df[~sectors_df["name"].apply(_is_leveraged)].reset_index(drop=True)
    print(f"  Excluded {before - len(sectors_df)} leveraged/inverse tickers", flush=True)
    tickers = sectors_df["ticker"].tolist()
    if "SPY" not in tickers:
        tickers.insert(0, "SPY")

    print(f"Downloading prices for {len(tickers)} tickers (3y) ...", flush=True)
    prices = download_prices(tickers)
    print(f"Downloaded {len(prices.columns)} tickers, {len(prices)} trading days", flush=True)

    print("Computing features ...", flush=True)
    df = compute_features(prices)
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])
    print(f"Features shape: {df.shape}", flush=True)

    print("Precomputing forward returns ...", flush=True)
    for label, days in HORIZONS.items():
        df[f"future_return_{label}"] = (
            df.groupby("ticker")["close"].shift(-days) / df["close"] - 1
        )

    print("Precomputing baselines ...", flush=True)
    baselines = {}
    for label in HORIZONS:
        col = f"future_return_{label}"
        baselines[label] = df.dropna(subset=[col]).groupby("ticker")[col].median()

    vol_by_ticker  = df.groupby("ticker")["volatility"].median()
    stable_tickers = set(vol_by_ticker[vol_by_ticker < STABILITY_VOL_LIMIT].index)

    # Price stability precomputation (LPL compliance — uses full downloaded history)
    current_prices   = df.groupby("ticker")["close"].last()
    frac_above_price = df.groupby("ticker")["close"].apply(lambda s: (s > MIN_PRICE).mean())
    price_ok_global  = set(
        current_prices[
            (current_prices > MIN_PRICE) &
            (frac_above_price.reindex(current_prices.index, fill_value=0) >= PRICE_HISTORY_FRAC)
        ].index
    )
    eligible_tickers = stable_tickers & price_ok_global
    print(f"  Eligible tickers after vol+price filter: {len(eligible_tickers)} "
          f"(removed {len(stable_tickers) - len(eligible_tickers)} below-$5)", flush=True)

    # Wide-format close prices for per-date current price check
    price_pivot = df.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")

    spy_df       = df[df["ticker"] == "SPY"].copy().sort_values("date")
    feature_mean = spy_df[FEATURES].mean()
    feature_std  = spy_df[FEATURES].std().replace(0, 1)
    spy_norm     = (spy_df[FEATURES] - feature_mean) / feature_std
    spy_norm.index = spy_df["date"].values

    spy_dates      = spy_df["date"].values
    cutoff         = spy_dates[-1] - np.timedelta64(BACKFILL_DAYS, "D")
    backfill_dates = [d for d in spy_dates if d >= cutoff][:-1]  # exclude today
    print(f"\nBackfilling {len(backfill_dates)} dates "
          f"({pd.Timestamp(backfill_dates[0]).date()} to "
          f"{pd.Timestamp(backfill_dates[-1]).date()}) ...", flush=True)

    log_path     = DATA_DIR / "signal_log.csv"
    existing_log = pd.read_csv(log_path) if log_path.exists() else pd.DataFrame()

    # Determine which dates need (re)scanning — missing or lacking p90
    existing_dates_with_p90 = set()
    if not existing_log.empty and "p90" in existing_log.columns:
        has_p90 = existing_log.dropna(subset=["p90"])
        existing_dates_with_p90 = set(has_p90["run_date"].unique())

    new_rows = []

    for i, target_date in enumerate(backfill_dates):
        run_date_str = pd.Timestamp(target_date).strftime("%Y-%m-%d")

        if run_date_str in existing_dates_with_p90:
            continue  # already complete

        spy_up_to = spy_df[spy_df["date"] <= target_date]
        if len(spy_up_to) < 150:
            continue

        today_row  = spy_up_to.iloc[-1]
        today_norm = (today_row[FEATURES].values.astype(float) - feature_mean.values) / feature_std.values

        spy_norm_up        = spy_norm[spy_norm.index <= target_date].copy()
        dists              = np.linalg.norm(spy_norm_up.values - today_norm, axis=1)
        spy_norm_up["distance"] = dists

        historical_norm = (
            spy_norm_up.iloc[:-EXCLUDE_RECENT_DAYS]
            if len(spy_norm_up) > EXCLUDE_RECENT_DAYS
            else spy_norm_up
        )
        similar_dates = set(historical_norm.nsmallest(SIMILAR_DAY_COUNT, "distance").index)

        # Per-date current price check (price must be > $5 on target_date)
        rows_up_to = price_pivot.loc[price_pivot.index <= target_date]
        if not rows_up_to.empty:
            date_prices     = rows_up_to.iloc[-1]
            price_on_date_ok = set(date_prices[date_prices > MIN_PRICE].index)
        else:
            price_on_date_ok = set()
        eligible = eligible_tickers & price_on_date_ok

        filtered = df[df["date"].isin(similar_dates)].copy()
        filtered = filtered[filtered["ticker"].isin(eligible)]

        date_signals = []

        for label in HORIZONS:
            col    = f"future_return_{label}"
            hf     = filtered.dropna(subset=[col])
            counts = hf.groupby("ticker")[col].count()
            valid  = counts[counts >= MIN_OBSERVATIONS].index
            hf     = hf[hf["ticker"].isin(valid)]

            if hf.empty:
                continue

            conditional = hf.groupby("ticker")[col].median()
            baseline    = baselines[label]
            edge        = (conditional - baseline).dropna()
            edge        = edge[edge >= MIN_EDGE]

            if edge.empty:
                continue

            cutoff_val = edge.quantile(0.95)
            strong_idx = edge[edge >= cutoff_val].index

            # Distribution stats for strong tickers
            grp    = hf[hf["ticker"].isin(strong_idx)].groupby("ticker")[col]
            p10    = grp.quantile(0.10)
            p90    = grp.quantile(0.90)

            for ticker in strong_idx:
                date_signals.append({
                    "run_date":       run_date_str,
                    "ticker":         ticker,
                    "horizon":        label,
                    "predicted_edge": round(float(edge[ticker]), 6),
                    "sector":         sectors_df.set_index("ticker")["sector"].get(ticker, "Unknown"),
                    "p10":            round(float(p10.get(ticker, 0)), 6),
                    "p90":            round(float(p90.get(ticker, 0)), 6),
                })

        new_rows.extend(date_signals)

        if (i + 1) % 10 == 0 or i == len(backfill_dates) - 1:
            print(f"  {i+1}/{len(backfill_dates)} dates done — "
                  f"{run_date_str}: {len(date_signals)} signals", flush=True)

    # Merge new rows with existing (drop old rows for re-scanned dates, keep rest)
    if new_rows:
        new_df      = pd.DataFrame(new_rows)
        re_scanned  = set(new_df["run_date"].unique())
        if not existing_log.empty:
            kept = existing_log[~existing_log["run_date"].isin(re_scanned)]
            signal_log = pd.concat([kept, new_df], ignore_index=True)
        else:
            signal_log = new_df
        signal_log = signal_log.drop_duplicates(subset=["run_date", "ticker", "horizon"])
        signal_log = signal_log.sort_values("run_date").reset_index(drop=True)
        signal_log.to_csv(log_path, index=False)
        print(f"\nSignal log: {len(signal_log)} total rows "
              f"({len(new_rows)} added/updated)", flush=True)
    else:
        print("\nSignal log: all dates already complete.", flush=True)
        signal_log = existing_log

    print("\nResolving outcomes and computing scores ...", flush=True)
    update_signal_memory(market_signals=pd.DataFrame(), prices=prices)

    # ── Portfolio replay ────────────────────────────────────────────────────────
    print("\nReplaying paper portfolios ...", flush=True)

    # Start fresh — chronological replay requires clean state
    port_path = DATA_DIR / "portfolio.json"
    if port_path.exists():
        port_path.unlink()

    dates = sorted(signal_log["run_date"].unique())
    for i, run_date in enumerate(dates):
        day_sigs = signal_log[signal_log["run_date"] == run_date].copy()
        # Rename for portfolio_manager compatibility
        day_sigs = day_sigs.rename(columns={"predicted_edge": "edge"})
        update_portfolios(day_sigs, prices, run_date=run_date)

        if (i + 1) % 10 == 0 or i == len(dates) - 1:
            print(f"  Portfolio replay: {i+1}/{len(dates)} — {run_date}", flush=True)

    print("\nBackfill complete.", flush=True)


if __name__ == "__main__":
    main()
