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
import json
import datetime
import time
from pathlib import Path

import pandas as pd
import yfinance as yf

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "etf_holdings.json"
SECTOR_MAP = ROOT / "data" / "sector_map.json"
CHUNK = 75
TIME_CAP_MIN = 12
RECHECK_NO_DATA_DAYS = 30


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
    themes = json.loads(SECTOR_MAP.read_text(encoding="utf-8"))
    universe = sorted({str(t).upper() for t in themes})
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
