"""
portfolio_manager.py — three paper-trading portfolios seeded with $100k each.

Strategy differences (everything else identical):
  max_edge  — buys stocks ranked by highest edge (conditional median - baseline)
  bull_case — buys stocks ranked by highest p90  (best upside scenario)
  defensive — buys stocks ranked by highest p10  (best downside floor)

v2 rules (active 2026-06-01 onwards):
  - Horizon-based exits: sell each position when its signal's forecast
    horizon has elapsed. A 5d signal exits ~7 calendar days after entry;
    a 120d signal exits ~170 days after. Uses a 1.4× business→calendar
    fudge factor.
  - Stay-long-if-still-strong: at horizon-exit time, if the ticker is
    still in the top quartile of current signals by the portfolio's
    sort metric (edge / p90 / p10), the entry_date is reset to today
    instead of selling — the renewal is logged in holding metadata but
    not in the trade log.
  - Signal-decay exits: sell once a position has been held > 0.5 ×
    horizon AND has dropped out of the current signal list entirely.
    This is sniffing-out edge decay before the horizon expires.
  - Continuous buying: deploy any free cash on every run, no weekly
    tranche timer. Cash freed by an exit is redeployed within the same
    daily build.
  - Equal-weight target (~3.33% per slot at 30 positions).
  - Max 30 positions, max 25% in any one sector.

v1 archive (2026-02-23 → 2026-06-01) is preserved in data/portfolio_v1.json
and rendered separately in the dashboard. The v1 rules used a 30/63-day
calendar turnover and a 5-day buy tranche.
"""
import json
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).parent.parent / "data"

INITIAL_CASH        = 100_000.0
MAX_POSITIONS       = 30
MAX_SECTOR_WEIGHT   = 0.25        # 25% cap per sector
MIN_POSITION_VALUE  = 500.0       # minimum position size
MAX_TRANSACTIONS    = 500         # keep last N transactions per portfolio

# Horizon-exit threshold: how many calendar days = one trading-day horizon.
# 5 trading days ≈ 7 calendar days (1.4× factor).
HORIZON_CAL_FACTOR  = 1.4
HORIZON_DAYS        = {"5d": 5, "20d": 20, "60d": 60, "120d": 120}
RENEW_TOP_FRACTION  = 0.25        # at horizon, renew hold if ticker is still
                                  # in this fraction of current ranked signals
SIGNAL_DECAY_FACTOR = 0.5         # min held-fraction-of-horizon before a
                                  # disappeared signal can trigger a sell

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
        "version":       "v2",
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


def _top_quartile_set(market_signals: pd.DataFrame, sort_col: str) -> set:
    """Return the set of tickers in the top RENEW_TOP_FRACTION of current
    signals ranked by sort_col."""
    if market_signals.empty or sort_col not in market_signals.columns:
        return set()
    ranked = market_signals.dropna(subset=[sort_col]).sort_values(sort_col, ascending=False)
    if ranked.empty:
        return set()
    q_size = max(1, int(len(ranked) * RENEW_TOP_FRACTION))
    return set(ranked.head(q_size)["ticker"].astype(str).tolist())


def _do_signal_decay_exits(port: dict, market_signals: pd.DataFrame,
                            run_date: str, run_dt: pd.Timestamp) -> int:
    """Sell positions that have (a) dropped out of the current signal list
    entirely and (b) have been held for at least SIGNAL_DECAY_FACTOR of
    their forecast horizon. Sniffs out edge decay before the horizon ends."""
    if market_signals.empty:
        return 0
    current_tickers = set(market_signals["ticker"].astype(str).tolist())
    to_sell = []
    for ticker, pos in list(port["holdings"].items()):
        if ticker in current_tickers:
            continue  # still in signals — let it ride
        horizon = pos.get("horizon", "20d")
        h_days = HORIZON_DAYS.get(horizon, 20)
        entry_date_str = pos.get("entry_date")
        if not entry_date_str:
            continue
        entry_dt = pd.Timestamp(entry_date_str)
        days_held = (run_dt - entry_dt).days
        # Held long enough that "no longer a signal" is meaningful (vs. early noise)
        threshold = int(h_days * SIGNAL_DECAY_FACTOR * HORIZON_CAL_FACTOR)
        if days_held >= threshold:
            to_sell.append((ticker, days_held, horizon))

    for ticker, days_held, horizon in to_sell:
        pos = port["holdings"].pop(ticker)
        price = pos.get("current_price", pos["entry_price"])
        proceeds = round(pos["shares"] * price, 2)
        port["cash"] += proceeds
        port["transactions"].append({
            "date":      run_date,
            "action":    "sell",
            "reason":    f"signal_decayed_{horizon}",
            "ticker":    ticker,
            "shares":    pos["shares"],
            "price":     round(price, 4),
            "value":     proceeds,
            "pnl_pct":   pos.get("pnl_pct", 0.0),
            "days_held": days_held,
            "horizon":   horizon,
        })
    return len(to_sell)


def _do_horizon_exits(port: dict, market_signals: pd.DataFrame,
                      run_date: str, run_dt: pd.Timestamp) -> tuple[int, int]:
    """At horizon-elapsed time for each holding, either sell or renew the
    entry date if the ticker is still in the top quartile of current signals
    by this portfolio's sort metric. Returns (n_sold, n_renewed)."""
    sort_col = port.get("sort_col", "edge")
    top_quartile = _top_quartile_set(market_signals, sort_col)
    if not top_quartile:
        top_quartile = _top_quartile_set(market_signals, "edge")  # fallback

    to_resolve = []
    for ticker, pos in port["holdings"].items():
        horizon = pos.get("horizon", "20d")
        h_days = HORIZON_DAYS.get(horizon, 20)
        entry_date_str = pos.get("entry_date")
        if not entry_date_str:
            continue
        entry_dt = pd.Timestamp(entry_date_str)
        days_held = (run_dt - entry_dt).days
        threshold = int(h_days * HORIZON_CAL_FACTOR)
        if days_held >= threshold:
            to_resolve.append((ticker, days_held, horizon))

    n_sold = 0
    n_renewed = 0
    for ticker, days_held, horizon in to_resolve:
        pos = port["holdings"][ticker]
        if ticker in top_quartile:
            # Renew: preserve original_entry_date once, log renewal in metadata
            if "original_entry_date" not in pos:
                pos["original_entry_date"] = pos.get("entry_date")
            renewed_at = pos.get("renewed_at", [])
            renewed_at.append(run_date)
            pos["renewed_at"] = renewed_at
            pos["entry_date"] = run_date
            n_renewed += 1
            continue
        # Otherwise sell
        port["holdings"].pop(ticker)
        price = pos.get("current_price", pos["entry_price"])
        proceeds = round(pos["shares"] * price, 2)
        port["cash"] += proceeds
        port["transactions"].append({
            "date":      run_date,
            "action":    "sell",
            "reason":    f"horizon_exit_{horizon}",
            "ticker":    ticker,
            "shares":    pos["shares"],
            "price":     round(price, 4),
            "value":     proceeds,
            "pnl_pct":   pos.get("pnl_pct", 0.0),
            "days_held": days_held,
            "horizon":   horizon,
        })
        n_sold += 1

    return n_sold, n_renewed


def _do_continuous_buy(port: dict, market_signals: pd.DataFrame,
                        prices: pd.DataFrame, run_date: str, run_dt: pd.Timestamp,
                        total_value: float) -> int:
    """Buy candidate stocks until cash drops below threshold or position cap
    is hit. Equal-weight target = total_value / MAX_POSITIONS."""
    if market_signals.empty:
        return 0
    sort_col = port["sort_col"]
    if sort_col not in market_signals.columns:
        sort_col = "edge"

    held = set(port["holdings"].keys())
    candidates = (
        market_signals[~market_signals["ticker"].isin(held)]
        .dropna(subset=[sort_col])
        .sort_values(sort_col, ascending=False)
    )

    target_position_size = total_value / MAX_POSITIONS

    available_slots = MAX_POSITIONS - len(port["holdings"])
    if available_slots <= 0:
        return 0

    bought = 0
    for _, row in candidates.iterrows():
        if bought >= available_slots:
            break
        if port["cash"] < MIN_POSITION_VALUE:
            break

        sector = str(row.get("sector", "Unknown"))
        sector_value = sum(
            p.get("current_value", p["shares"] * p["entry_price"])
            for p in port["holdings"].values()
            if p.get("sector") == sector
        )
        if sector_value + target_position_size > total_value * MAX_SECTOR_WEIGHT:
            continue

        price = _get_price(str(row["ticker"]), prices, run_dt)
        if price is None or price == 0:
            continue

        # Use the smaller of target size, available cash; never below the floor
        value = min(target_position_size, port["cash"])
        if value < MIN_POSITION_VALUE:
            break

        shares = value / price
        port["cash"] -= value
        ticker = str(row["ticker"])
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
        bought += 1

    if bought:
        port["last_buy_date"] = run_date
    return bought


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
        # Same-day re-run: only reprocess if there's pending work
        if port["history"] and port["history"][-1]["date"] == run_date:
            # Check if any horizon exits or buys are pending given current state
            has_pending_exit = any(
                (run_dt - pd.Timestamp(pos.get("entry_date", run_date))).days
                >= int(HORIZON_DAYS.get(pos.get("horizon", "20d"), 20) * HORIZON_CAL_FACTOR)
                for pos in port["holdings"].values()
            )
            today_snap = port["history"][-1]
            has_room_to_buy = (
                today_snap.get("cash", 0) >= MIN_POSITION_VALUE
                and len(port["holdings"]) < MAX_POSITIONS
            )
            if not (has_pending_exit or has_room_to_buy):
                print(f"  {port['name']}: already updated today, no pending trades", flush=True)
                continue
            # Pop today's snapshot — it will be re-appended with the new state
            port["history"].pop()

        # 1. Mark current prices
        total_invested = _mark_holdings(port, prices, run_dt)
        total_value    = port["cash"] + total_invested

        # 2a. Signal-decay exits — sell names that dropped out of signals
        #     after being held more than half their horizon
        n_decayed = _do_signal_decay_exits(port, market_signals, run_date, run_dt)
        if n_decayed:
            total_invested = _mark_holdings(port, prices, run_dt)
            total_value    = port["cash"] + total_invested

        # 2b. Horizon-based exits with stay-long-if-still-strong renewal
        n_sold, n_renewed = _do_horizon_exits(port, market_signals, run_date, run_dt)
        if n_sold:
            total_invested = _mark_holdings(port, prices, run_dt)
            total_value    = port["cash"] + total_invested

        # 3. Continuous buying — deploy any free cash
        n_bought = _do_continuous_buy(port, market_signals, prices, run_date, run_dt, total_value)
        if n_bought:
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

        port["transactions"] = port["transactions"][-MAX_TRANSACTIONS:]

        n = len(port["holdings"])
        ret = port["history"][-1]["return_pct"]
        bits = []
        if n_bought:  bits.append(f"+{n_bought}b")
        if n_sold:    bits.append(f"-{n_sold}s")
        if n_decayed: bits.append(f"-{n_decayed}d")
        if n_renewed: bits.append(f"~{n_renewed}r")
        activity = f" | {' '.join(bits)} today" if bits else ""
        print(f"  {port['name']}: ${total_value:,.0f} | {n} positions | "
              f"{ret:+.2f}% return{activity}", flush=True)

    with open(port_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    print(f"  Saved portfolio.json", flush=True)
