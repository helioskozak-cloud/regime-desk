"""
etf_holdings_scan.py — rolling ETF/fund look-through scan (standalone, read-side).

Each run checks a chunk (~75) of the universe for fund top-holdings via
yfinance funds_data, prioritizing never-checked tickers then the stalest.
Equities get classified out on first touch and never rechecked; funds are
refreshed on rotation (~2-3 weeks around the universe at 75/night). Yahoo
publishes TOP 10 holdings only — that's the data's ceiling, not a choice.

Writes data/etf_holdings.json:
  {meta, funds: {T: {as_of, name?, holdings: [{t, name, w}]}},
   non_funds: {T: date}, no_data: {T: date}}
"""
import csv
import json
import datetime
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "etf_holdings.json"
SECTOR_MAP = ROOT / "data" / "sector_map.json"
# THE UNIVERSE IS universe_ci.csv, NOT sector_map.json.
#
# This scan used to walk sector_map.json, which is not a universe — it is a
# hand-maintained ticker -> THEME labelling that happens to cover part of one.
# 375 of the 1,755 tickers in universe_ci.csv have no theme, and 370 of those
# have a blank sector: they are the ETFs. Nobody assigns a "theme" to QQQ,
# because the S&P 500 is not one.
#
# So this scan spent weeks classifying 1,301 individual stocks as "not a fund"
# while never once looking at QQQ, SPY, IVV, ITOT, VOO or VTI — the exact
# tickers a fund look-through exists to see inside. It was walking the one list
# built by excluding the things it is for.
UNIVERSE_CSV = ROOT / "scan" / "universe_ci.csv"
CHUNK = 75
TIME_CAP_MIN = 12
RECHECK_NO_DATA_DAYS = 30


def load_universe() -> set[str]:
    """Every ticker regime-desk screens. Falls back to the theme map only if the
    CSV is unreadable — a smaller universe is better than no run, but the
    fallback is the old bug, so it says so out loud."""
    try:
        with UNIVERSE_CSV.open(encoding="utf-8", newline="") as fh:
            rows = list(csv.DictReader(fh))
        tickers = {str(r["ticker"]).upper().strip() for r in rows if r.get("ticker")}
        if tickers:
            return tickers
    except Exception as exc:
        print(f"[etf] WARNING: could not read {UNIVERSE_CSV.name} ({exc}); "
              f"falling back to sector_map.json, which omits ~375 ETFs", flush=True)
    return {str(t).upper() for t in json.loads(SECTOR_MAP.read_text(encoding="utf-8"))}


def load_state() -> dict:
    if OUT.exists():
        try:
            return json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"meta": {}, "funds": {}, "non_funds": {}, "no_data": {}}


def pick_chunk(state: dict, universe: list[str]) -> list[str]:
    today = datetime.date.today()
    fresh_cut = (today - datetime.timedelta(days=RECHECK_NO_DATA_DAYS)).isoformat()
    never, stale = [], []
    for t in universe:
        if t in state["non_funds"]:
            continue
        if t in state["no_data"] and state["no_data"][t] > fresh_cut:
            continue
        if t in state["funds"]:
            stale.append((state["funds"][t].get("as_of", ""), t))
        else:
            never.append(t)
    stale.sort()
    return (never + [t for _, t in stale])[:CHUNK]


def main() -> None:
    state = load_state()
    universe = sorted(load_universe())
    todo = pick_chunk(state, universe)
    today = datetime.date.today().isoformat()
    deadline = time.monotonic() + TIME_CAP_MIN * 60
    n_fund = n_eq = n_nodata = n_err = 0

    for t in todo:
        if time.monotonic() > deadline:
            print(f"[etf] time cap hit after {n_fund+n_eq+n_nodata+n_err} tickers", flush=True)
            break
        try:
            th = yf.Ticker(t).funds_data.top_holdings
            if th is None or not len(th):
                state["no_data"][t] = today
                n_nodata += 1
                continue
            holdings = [
                {"t": str(idx).upper(),
                 "name": str(row.get("Name", ""))[:60],
                 "w": round(float(row.get("Holding Percent", 0)), 5)}
                for idx, row in th.iterrows()
            ]
            state["funds"][t] = {"as_of": today, "holdings": holdings}
            state["no_data"].pop(t, None)
            n_fund += 1
        except Exception as exc:
            msg = str(exc).lower()
            if ("no fund data" in msg or "quote type" in msg
                    or "not a fund" in msg or "equity" in msg):
                state["non_funds"][t] = today
                n_eq += 1
            else:
                n_err += 1  # transient — retry on a future rotation
        time.sleep(0.4)  # gentle on the endpoint

    state["meta"] = {
        "updated": today,
        "universe": len(universe),
        "funds_covered": len(state["funds"]),
        "classified_equity": len(state["non_funds"]),
        "note": "Yahoo publishes top-10 holdings only; weights are fractions of the fund.",
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(state), encoding="utf-8")
    print(f"[etf] chunk done: +{n_fund} funds, {n_eq} classified equity, "
          f"{n_nodata} no-data, {n_err} transient errors. "
          f"Total funds covered: {len(state['funds'])}/{len(universe)} universe "
          f"({len(state['non_funds'])} known equities skipped)", flush=True)


if __name__ == "__main__":
    main()
