"""
ticker_lookup.py — compute regime signals for watchlist tickers not captured by the main scan.

Reads:  data/watchlist.txt  (one ticker per line; lines starting with # are comments)
Writes: data/ticker_cache.json

The main scan applies aggressive filters (MIN_EDGE, top-5% cutoff, baseline > 0) that
exclude many valid tickers. This script runs the same analog-matching logic but without
those filters, so any ticker in the database can be looked up.
"""
import json
import math
import sqlite3
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
WATCHLIST_PATH = DATA / "watchlist.txt"
CACHE_PATH = DATA / "ticker_cache.json"

_DB_CANDIDATES = [
    DATA / "market_data.db",
    Path("C:/Portfolizer/market_data.db"),
    ROOT.parent / "market_data.db",
]

SIMILAR_DAY_COUNT = 30
EXCLUDE_RECENT_DAYS = 30
MIN_OBSERVATIONS = 5
HORIZONS = {"5d": 5, "20d": 20, "60d": 60, "120d": 120}


def _find_db():
    for p in _DB_CANDIDATES:
        if p.exists():
            return p
    return None


def load_watchlist():
    if not WATCHLIST_PATH.exists():
        return []
    tickers = []
    for line in WATCHLIST_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            tickers.append(line.upper())
    return list(dict.fromkeys(tickers))


def compute_analog_dates(conn):
    spy = pd.read_sql(
        "SELECT date, return_5, return_20, volatility, drawdown "
        "FROM features WHERE ticker='SPY' ORDER BY date",
        conn, parse_dates=["date"]
    )
    if len(spy) < 150:
        raise ValueError("Not enough SPY data to compute analog dates")
    today = spy.iloc[-1]
    vec = np.array([today["return_5"], today["return_20"],
                    today["volatility"], today["drawdown"]])
    hist = spy.iloc[:-EXCLUDE_RECENT_DAYS].copy()
    hist["dist"] = hist.apply(
        lambda r: float(np.linalg.norm(
            np.array([r["return_5"], r["return_20"],
                      r["volatility"], r["drawdown"]]) - vec
        )), axis=1
    )
    similar = hist.nsmallest(SIMILAR_DAY_COUNT, "dist")
    return set(similar["date"].dt.strftime("%Y-%m-%d"))


def load_sector_map(conn):
    try:
        rows = pd.read_sql("SELECT ticker, sector FROM sector_cache", conn)
        return dict(zip(rows["ticker"].str.upper(), rows["sector"]))
    except Exception:
        return {}


def compute_ticker(conn, ticker, analog_dates, sector_map):
    """Compute edge + distribution for a single ticker across all horizons.

    Unlike the main scan, no MIN_EDGE or percentile cutoff is applied.
    Returns None if there is insufficient price history.
    """
    prices = pd.read_sql(
        "SELECT p.date, p.close, f.volatility "
        "FROM prices p JOIN features f ON p.ticker=f.ticker AND p.date=f.date "
        "WHERE p.ticker=? ORDER BY p.date",
        conn, params=(ticker,), parse_dates=["date"]
    )
    if len(prices) < 60:
        return None

    prices = prices.drop_duplicates(subset=["date"]).reset_index(drop=True)
    prices["ds"] = prices["date"].dt.strftime("%Y-%m-%d")
    med_vol = float(prices["volatility"].median())
    sector = sector_map.get(ticker, "Unknown")

    best = None
    best_nobs = -1

    for label, days in HORIZONS.items():
        future = prices["close"].shift(-days) / prices["close"] - 1
        valid = prices.assign(fr=future).dropna(subset=["fr"])
        if len(valid) < 20:
            continue

        baseline = float(valid["fr"].median())
        analog_rows = valid[valid["ds"].isin(analog_dates)]
        n = len(analog_rows)
        if n < MIN_OBSERVATIONS:
            continue

        vals = analog_rows["fr"].values
        cond = float(np.median(vals))
        edge = round(cond - baseline, 4)
        pcts = np.percentile(vals, [10, 25, 50, 75, 90])
        hit = round(float((vals > 0).mean()), 3)
        span = float(pcts[4] - pcts[0])
        vol_proxy = round(span / (2.56 * math.sqrt(max(1, days))), 4)
        vol_proxy = max(0.005, min(0.12, vol_proxy))

        if n > best_nobs:
            best_nobs = n
            best = {
                "ticker": ticker,
                "name": ticker,
                "sector": sector,
                "edge": edge,
                "horizon": label,
                "n_obs": n,
                "p10": round(float(pcts[0]), 4),
                "p25": round(float(pcts[1]), 4),
                "p50": round(float(pcts[2]), 4),
                "p75": round(float(pcts[3]), 4),
                "p90": round(float(pcts[4]), 4),
                "hit_rate": hit,
                "vol": round(med_vol, 4),
                "below_threshold": edge < 0.05,
                "from_watchlist": True,
            }

    return best


def main():
    tickers = load_watchlist()
    if not tickers:
        print("[ticker_lookup] watchlist.txt is empty or missing — nothing to compute")
        return

    db_path = _find_db()
    if not db_path:
        print("[ticker_lookup] market_data.db not found — checked: " +
              ", ".join(str(p) for p in _DB_CANDIDATES))
        return

    print(f"[ticker_lookup] DB: {db_path}")
    print(f"[ticker_lookup] Computing signals for: {', '.join(tickers)}")

    conn = sqlite3.connect(db_path)
    try:
        analog_dates = compute_analog_dates(conn)
        sector_map = load_sector_map(conn)
        print(f"[ticker_lookup] {len(analog_dates)} analog dates, "
              f"{len(sector_map)} sectors loaded")

        results = {}
        for tk in tickers:
            try:
                sig = compute_ticker(conn, tk, analog_dates, sector_map)
                if sig:
                    results[tk] = sig
                    flag = " [below threshold]" if sig["below_threshold"] else ""
                    print(f"[ticker_lookup] {tk}: edge={sig['edge']:+.1%} "
                          f"({sig['horizon']}, n={sig['n_obs']}){flag}")
                else:
                    print(f"[ticker_lookup] {tk}: not enough analog observations")
            except Exception as exc:
                print(f"[ticker_lookup] {tk}: ERROR — {exc}")
    finally:
        conn.close()

    CACHE_PATH.write_text(
        json.dumps({"generated": str(date.today()), "tickers": results}, indent=2),
        encoding="utf-8"
    )
    print(f"[ticker_lookup] Wrote {len(results)} entries to ticker_cache.json")


if __name__ == "__main__":
    main()
