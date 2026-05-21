"""
portfolio_manager.py — three paper-trading portfolios seeded with $100k each.

Strategy differences (everything else identical):
  max_edge  — buys stocks ranked by highest edge (conditional median - baseline)
  bull_case — buys stocks ranked by highest p90  (best upside scenario)
  defensive — buys stocks ranked by highest p10  (best downside floor)

Shared rules:
  - Deploy 15% of total value every 5 trading days until cash < 5% of total
  - 5 positions per weekly tranche, equal-weight (~3% each)
  - Max 30 positions, max 25% in any one sector
  - Quarterly turnover (~63 days): sell 10% of holdings not in current signals
  - Prices from the wide-format yfinance DataFrame already in memory
"""
import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"

INITIAL_CASH        = 100_000.0
DEPLOY_FRAC         = 0.15        # 15% of total value per weekly tranche
DEPLOY_INTERVAL     = 5           # trading days between deployment runs
POSITIONS_PER_BATCH = 5           # new positions per tranche
MAX_POSITIONS       = 30
MAX_SECTOR_WEIGHT   = 0.25        # 25% cap per sector
MIN_POSITION_VALUE  = 500.0       # minimum position size
FULLY_DEPLOYED      = 0.05        # stop buying when cash < 5% of total
TURNOVER_INTERVAL   = 63          # trading days between turnover events
TURNOVER_RATE       = 0.10        # fraction of portfolio to replace each quarter
MAX_TRANSACTIONS    = 300         # keep last N transactions per portfolio

STRATEGIES = {
    "max_edge":  {"name": "Max Edge",   "sort_col": "edge", "label": "Ranks by conditional edge (median)"},
    "bull_case": {"name": "Bull Case",  "sort_col": "p90",  "label": "Ranks by p90 — best upside scenario"},
    "defensive": {"name": "Defensive",  "sort_col": "p10",  "label": "Ranks by p10 — best downside floor"},
}


def _empty_portfolio(strategy_key: str, inception_date: str) -> dict:
    meta = STRATEGIES[strategy_key]
    return {
        "strategy":      strategy_key,
        "name":          meta["name"],
        "label":         meta["label"],
        "sort_col":      meta["sort_col"],
        "inception_date": inception_date,
        "initial_cash":  INITIAL_CASH,
        "cash":          INITIAL_CASH,
        "holdings":      {},
        "history":       [],
        "transactions":  [],
        "last_buy_date": None,
        "last_turnover_date": None,
    }


def _get_price(ticker: str, prices: pd.DataFrame, run_dt: pd.Timestamp):
    if ticker not in prices.columns:
        return None
    series = prices[ticker].dropna()
    available = series[series.index <= run_dt]
    if available.empty:
        return None
    return float(available.iloc[-1])


def _mark_holdings(port: dict, prices: pd.DataFrame, run_dt: pd.Timestamp) -> float:
    """Update current_price/current_value on all holdings. Returns total invested."""
    dead = []
    total_invested = 0.0
    for ticker, pos in port["holdings"].items():
        price = _get_price(ticker, prices, run_dt)
        if price is None:
            dead.append(ticker)
            continue
        pos["current_price"] = round(price, 4)
        pos["current_value"] = round(pos["shares"] * price, 2)
        pos["pnl_pct"]       = round((price / pos["entry_price"] - 1) * 100, 2)
        total_invested      += pos["current_value"]

    for ticker in dead:
        pos = port["holdings"].pop(ticker)
        proceeds = pos.get("current_value", 0.0)
        port["cash"] += proceeds
        port["transactions"].append({
            "date": run_dt.strftime("%Y-%m-%d"),
            "action": "sell", "reason": "delisted",
            "ticker": ticker,
            "shares": pos["shares"],
            "price": pos.get("current_price", pos["entry_price"]),
            "value": proceeds,
        })

    return total_invested


def _do_turnover(port: dict, market_signals: pd.DataFrame,
                 run_date: str, run_dt: pd.Timestamp, total_value: float) -> None:
    if market_signals.empty:
        return
    current_tickers = set(market_signals["ticker"].tolist())
    candidates = [t for t in port["holdings"] if t not in current_tickers]
    n_sell = max(1, round(len(port["holdings"]) * TURNOVER_RATE))
    to_sell = candidates[:n_sell]

    for ticker in to_sell:
        pos = port["holdings"].pop(ticker)
        price    = pos.get("current_price", pos["entry_price"])
        proceeds = round(pos["shares"] * price, 2)
        port["cash"] += proceeds
        port["transactions"].append({
            "date": run_date,
            "action": "sell", "reason": "turnover",
            "ticker": ticker,
            "shares": pos["shares"],
            "price": round(price, 4),
            "value": proceeds,
            "pnl_pct": pos.get("pnl_pct", 0.0),
        })

    port["last_turnover_date"] = run_date


def _do_buy(port: dict, market_signals: pd.DataFrame,
            prices: pd.DataFrame, run_date: str, run_dt: pd.Timestamp,
            total_value: float) -> None:
    if market_signals.empty:
        return
    sort_col = port["sort_col"]
    if sort_col not in market_signals.columns:
        sort_col = "edge"

    held     = set(port["holdings"].keys())
    cash     = port["cash"]
    tranche  = min(cash, total_value * DEPLOY_FRAC)

    # Rank candidates by this portfolio's strategy metric
    candidates = (
        market_signals[~market_signals["ticker"].isin(held)]
        .dropna(subset=[sort_col])
        .sort_values(sort_col, ascending=False)
    )

    selected = []
    for _, row in candidates.iterrows():
        if len(selected) >= POSITIONS_PER_BATCH:
            break
        if len(port["holdings"]) + len(selected) >= MAX_POSITIONS:
            break

        sector = str(row.get("sector", "Unknown"))
        sector_value = sum(
            p.get("current_value", p["shares"] * p["entry_price"])
            for p in port["holdings"].values()
            if p.get("sector") == sector
        )
        if sector_value > total_value * MAX_SECTOR_WEIGHT:
            continue

        price = _get_price(str(row["ticker"]), prices, run_dt)
        if price is None or price == 0:
            continue

        selected.append((row, price))

    if not selected:
        return

    per_pos = tranche / len(selected)
    if per_pos < MIN_POSITION_VALUE:
        return

    for row, price in selected:
        ticker = str(row["ticker"])
        value  = min(per_pos, port["cash"])
        if value < MIN_POSITION_VALUE:
            break
        shares = value / price
        port["cash"] -= value
        port["holdings"][ticker] = {
            "shares":        round(shares, 4),
            "entry_price":   round(price, 4),
            "entry_date":    run_date,
            "entry_edge":    round(float(row.get("edge", 0)), 4),
            "entry_p90":     round(float(row.get("p90", 0)), 4) if "p90" in row.index else None,
            "entry_p10":     round(float(row.get("p10", 0)), 4) if "p10" in row.index else None,
            "sector":        str(row.get("sector", "Unknown")),
            "horizon":       str(row.get("horizon", "20d")),
            "sort_col":      sort_col,
            "sort_value":    round(float(row.get(sort_col, 0)), 4),
            "current_price": round(price, 4),
            "current_value": round(shares * price, 2),
            "pnl_pct":       0.0,
        }
        port["transactions"].append({
            "date":      run_date,
            "action":    "buy",
            "ticker":    ticker,
            "shares":    round(shares, 4),
            "price":     round(price, 4),
            "value":     round(value, 2),
            "sort_col":  sort_col,
            "sort_value": round(float(row.get(sort_col, 0)), 4),
        })

    port["last_buy_date"] = run_date


def update_portfolios(market_signals: pd.DataFrame, prices: pd.DataFrame,
                      run_date: str = None) -> None:
    """
    Load (or create) portfolio.json, update all three portfolios for today,
    and write back. Called from ci_scan.main() after update_signal_memory().
    Pass run_date to override the date (used during backfill replay).
    """
    port_path = DATA_DIR / "portfolio.json"
    run_dt    = pd.Timestamp(run_date) if run_date else prices.index[-1]
    run_date  = run_dt.strftime("%Y-%m-%d")

    print(f"\nUpdating portfolios for {run_date} ...", flush=True)

    if port_path.exists():
        with open(port_path, "r", encoding="utf-8") as f:
            state = json.load(f)
    else:
        state = {}

    # Ensure all three strategies exist
    for key in STRATEGIES:
        if key not in state:
            state[key] = _empty_portfolio(key, run_date)

    for key, port in state.items():
        # Skip if already updated today
        if port["history"] and port["history"][-1]["date"] == run_date:
            print(f"  {port['name']}: already updated today", flush=True)
            continue

        # 1. Mark current prices
        total_invested = _mark_holdings(port, prices, run_dt)
        total_value    = port["cash"] + total_invested

        # 2. Quarterly turnover
        last_to = port.get("last_turnover_date")
        days_since_to = (
            (run_dt - pd.Timestamp(last_to)).days if last_to else TURNOVER_INTERVAL + 1
        )
        if days_since_to >= TURNOVER_INTERVAL and port["holdings"]:
            _do_turnover(port, market_signals, run_date, run_dt, total_value)
            total_invested = _mark_holdings(port, prices, run_dt)
            total_value    = port["cash"] + total_invested

        # 3. Weekly deployment
        last_buy  = port.get("last_buy_date")
        days_since_buy = (
            (run_dt - pd.Timestamp(last_buy)).days if last_buy else DEPLOY_INTERVAL + 1
        )
        cash_ratio     = port["cash"] / total_value if total_value > 0 else 1.0
        if days_since_buy >= DEPLOY_INTERVAL and cash_ratio > FULLY_DEPLOYED:
            _do_buy(port, market_signals, prices, run_date, run_dt, total_value)
            total_invested = _mark_holdings(port, prices, run_dt)
            total_value    = port["cash"] + total_invested

        # 4. Record daily snapshot
        port["history"].append({
            "date":         run_date,
            "total_value":  round(total_value, 2),
            "cash":         round(port["cash"], 2),
            "invested":     round(total_invested, 2),
            "n_positions":  len(port["holdings"]),
            "return_pct":   round((total_value / port["initial_cash"] - 1) * 100, 4),
        })

        # Trim transactions
        port["transactions"] = port["transactions"][-MAX_TRANSACTIONS:]

        n = len(port["holdings"])
        ret = port["history"][-1]["return_pct"]
        print(f"  {port['name']}: ${total_value:,.0f} | {n} positions | "
              f"{ret:+.2f}% return", flush=True)

    with open(port_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print(f"  Saved portfolio.json", flush=True)
