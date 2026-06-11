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
SIGNAL_DECAY_FACTOR = 0.0         # min held-fraction-of-horizon before a
                                  # disappeared signal can trigger a sell.
                                  # 0.0 = exit as soon as the signal decays
                                  # off the qualifying list (whichever fires
                                  # first: signal-decay OR horizon). The
                                  # old 0.5 floor made the portfolios
                                  # effectively buy-and-hold until horizon
                                  # for half their lifetime, which didn't
                                  # let them react to regime changes.

STRATEGIES = {
    "max_edge":  {"name": "Max Edge",   "sort_col": "edge", "label": "Ranks by conditional edge (median)"},
    "bull_case": {"name": "Bull Case",  "sort_col": "p90",  "label": "Ranks by p90 — best upside scenario"},
    "defensive": {"name": "Defensive",  "sort_col": "p10",  "label": "Ranks by p10 — best downside floor"},
}

# Which macro-risk axes (from data/cross_asset.json) hit which thematic sector.
# When a listed risk is elevated (score > 0.5), the sector is demoted in ranking.
# Empty list = sector is defensive/neutral and unaffected by regime.
SECTOR_RISK_SENSITIVITY = {
    "Biotech":                ["Volatility Regime", "Rate Re-pricing"],
    "Communication Services": ["Rate Re-pricing"],
    "Consumer Discretionary": ["Growth Slowdown", "Credit Stress"],
    "Crypto":                 ["Volatility Regime", "Complacency Risk", "Credit Stress"],
    "Defense":                [],
    "Energy":                 ["Growth Slowdown", "Dollar Headwind"],
    "Energy Transition":      ["Growth Slowdown", "Rate Re-pricing"],
    "Financials":             ["Credit Stress", "Rate Re-pricing", "Growth Slowdown"],
    "Industrials":            ["Growth Slowdown", "Dollar Headwind"],
    "Materials":              ["Growth Slowdown", "Dollar Headwind"],
    "Semiconductors":         ["Growth Slowdown", "Volatility Regime", "Dollar Headwind"],
    "Technology":             ["Rate Re-pricing", "Dollar Headwind", "Complacency Risk"],
    "Utilities":              ["Rate Re-pricing"],
    "Consumer Staples":       [],
    "Healthcare":             [],
    "Unknown":                [],
}
# Per elevated risk-point above 0.5, add this to the sector's rank-shift penalty.
# Worst case (3 axes all at 1.0) → penalty = 3 * 0.5 * 0.25 = 0.375 → capped at 0.4.
REGIME_PENALTY_PER_POINT = 0.25
REGIME_PENALTY_CAP       = 0.40


def _load_regime_penalties() -> dict:
    """Return {sector: rank_shift_fraction in [0, 0.4]} from cross_asset.json.
    Empty dict if file missing or unreadable — picks fall back to pre-regime
    behavior so this is safe to remove the file at any time."""
    path = DATA_DIR / "cross_asset.json"
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            ca = json.load(f)
    except Exception:
        return {}
    scores = {r["name"]: float(r.get("score", 0.0)) for r in ca.get("risks", [])}
    out = {}
    for sector, sensitive_to in SECTOR_RISK_SENSITIVITY.items():
        penalty = 0.0
        for risk_name in sensitive_to:
            s = scores.get(risk_name, 0.0)
            if s > 0.5:
                penalty += (s - 0.5) * REGIME_PENALTY_PER_POINT
        out[sector] = min(REGIME_PENALTY_CAP, penalty)
    return out


def _apply_regime_tilt(candidates: pd.DataFrame, penalties: dict) -> pd.DataFrame:
    """Rank-shift candidates by sector regime penalty. Input must already be
    sorted by the portfolio's sort_col descending and reset_index'd. Returns
    a re-sorted frame with two debug columns (_regime_penalty, _adjusted_rank)
    so trade logs can audit why a pick made the cut."""
    if not penalties or candidates.empty:
        candidates = candidates.copy()
        candidates["_regime_penalty"] = 0.0
        candidates["_adjusted_rank"]  = range(len(candidates))
        return candidates
    n = len(candidates)
    out = candidates.copy()
    out["_regime_penalty"] = out["sector"].fillna("Unknown").map(penalties).fillna(0.0)
    out["_orig_rank"]      = range(n)
    out["_adjusted_rank"]  = out["_orig_rank"] + out["_regime_penalty"] * n
    return out.sort_values("_adjusted_rank", ascending=True, kind="mergesort").reset_index(drop=True)


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


_UNIV_PATH = Path(__file__).parent / "universe_ci.csv"


def _load_universe_lookup() -> tuple[dict, dict]:
    """Build (name_map, sector_map) from scan/universe_ci.csv. Cached at
    module import — the file is small (~1750 rows) and only changes when
    we explicitly edit the universe."""
    name_map, sector_map = {}, {}
    if not _UNIV_PATH.exists():
        return name_map, sector_map
    try:
        df = pd.read_csv(_UNIV_PATH)
    except Exception:
        return name_map, sector_map
    if "ticker" not in df.columns:
        return name_map, sector_map
    if "name" in df.columns:
        name_map = dict(zip(
            df["ticker"].astype(str),
            df["name"].fillna("").astype(str),
        ))
    if "sector" in df.columns:
        sector_map = dict(zip(
            df["ticker"].astype(str),
            df["sector"].fillna("").astype(str),
        ))
    return name_map, sector_map


_UNIV_NAMES, _UNIV_SECTORS = _load_universe_lookup()


def _catchup_missed_days(state: dict, prices: pd.DataFrame, run_dt: pd.Timestamp,
                          market_signals: "pd.DataFrame | None") -> None:
    """For each portfolio, if there's a gap of business days between the
    last history entry and today, mark-to-market and process horizon exits
    for each missed day. Skips holidays (no SPY trade). Appends a snapshot
    per missed day so the dashboard's performance chart doesn't interpolate
    across the gap.

    Conservative by design: missed-day horizon exits force_sell=True (no
    look-ahead renewal). Buys and signal-decay exits are NOT processed for
    missed days — they need that day's signal list, which we don't have."""
    # SPY trading days = real market days. Use this to skip holidays.
    open_days: set | None = None
    if "SPY" in prices.columns:
        s = prices["SPY"].dropna()
        if not s.empty:
            open_days = set(pd.DatetimeIndex(s.index).normalize())

    for key, port in state.items():
        if not port.get("history"):
            continue
        try:
            last_dt = pd.Timestamp(port["history"][-1]["date"]).normalize()
        except Exception:
            continue
        start = last_dt + pd.Timedelta(days=1)
        end   = run_dt - pd.Timedelta(days=1)
        if start > end:
            continue
        missed_bdays = pd.bdate_range(start=start, end=end)
        if open_days is not None:
            missed = [d for d in missed_bdays if d.normalize() in open_days]
        else:
            missed = list(missed_bdays)
        if not missed:
            continue
        print(f"  {port['name']}: catching up {len(missed)} missed day(s) "
              f"({missed[0].date()} -> {missed[-1].date()})", flush=True)
        for day in missed:
            day_str = day.strftime("%Y-%m-%d")
            total_invested = _mark_holdings(port, prices, day, market_signals)
            n_sold, _ = _do_horizon_exits(port, market_signals, day_str, day,
                                            force_sell=True)
            if n_sold:
                total_invested = _mark_holdings(port, prices, day, market_signals)
            total_value = port["cash"] + total_invested
            port["history"].append({
                "date":         day_str,
                "total_value":  round(total_value, 2),
                "cash":         round(port["cash"], 2),
                "invested":     round(total_invested, 2),
                "n_positions":  len(port["holdings"]),
                "return_pct":   round((total_value / port.get("initial_cash", INITIAL_CASH) - 1) * 100, 4),
                "note":         "catchup",
            })


def _backfill_holding_metadata(port: dict, market_signals: pd.DataFrame | None) -> int:
    """Fill in name + sector on any holding that doesn't have them yet.

    Source priority:
      1. market_signals (today's qualifying signals — freshest)
      2. universe_ci.csv (broad ticker → name/sector reference)

    Holdings that have decayed off the signal list (ETFs, names whose
    edge dropped below 5%) still get healed from universe_ci.csv. This
    runs on EVERY daily build, before the same-day early-exit check, so
    older portfolio.json entries (saved before name was captured at buy
    time) recover even if no trades happen today."""
    sig_names: dict[str, str] = {}
    sig_sectors: dict[str, str] = {}
    if market_signals is not None and not market_signals.empty:
        if "name" in market_signals.columns:
            sig_names = dict(zip(
                market_signals["ticker"].astype(str),
                market_signals["name"].fillna("").astype(str),
            ))
        if "sector" in market_signals.columns:
            sig_sectors = dict(zip(
                market_signals["ticker"].astype(str),
                market_signals["sector"].fillna("").astype(str),
            ))

    patched = 0
    for ticker, pos in port["holdings"].items():
        tk = str(ticker)
        # Universe is the curated source of truth — overwrite the cached
        # name if it differs (heals legacy entries like "Fidelity Ethereum
        # Fund Fidelity Ethereum Fund" where the universe was previously
        # double-stamped).
        nm_new = sig_names.get(tk) or _UNIV_NAMES.get(tk)
        if nm_new and pos.get("name") != nm_new:
            pos["name"] = nm_new
            patched += 1
        if not pos.get("sector") or pos.get("sector") == "Unknown":
            sec = sig_sectors.get(tk) or _UNIV_SECTORS.get(tk)
            if sec and sec != "Unknown":
                pos["sector"] = sec
                patched += 1
    return patched


def _mark_holdings(port: dict, prices: pd.DataFrame, run_dt: pd.Timestamp,
                    market_signals: pd.DataFrame | None = None) -> float:
    """Update current_price/current_value on all holdings. Backfill name +
    sector here too, in case a holding was added by a same-day re-run.
    Returns total invested."""
    _backfill_holding_metadata(port, market_signals)

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
    signals ranked by sort_col, with regime tilt applied so renewals match
    the same selection logic as new buys."""
    if market_signals.empty or sort_col not in market_signals.columns:
        return set()
    ranked = (
        market_signals.dropna(subset=[sort_col])
        .sort_values(sort_col, ascending=False)
        .drop_duplicates(subset=["ticker"], keep="first")
        .reset_index(drop=True)
    )
    if ranked.empty:
        return set()
    penalties = _load_regime_penalties()
    ranked = _apply_regime_tilt(ranked, penalties)
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
                      run_date: str, run_dt: pd.Timestamp,
                      force_sell: bool = False) -> tuple[int, int]:
    """At horizon-elapsed time for each holding, either sell or renew the
    entry date if the ticker is still in the top quartile of current signals
    by this portfolio's sort metric. Returns (n_sold, n_renewed).

    force_sell=True bypasses the renewal check entirely and sells every
    horizon-eligible position. Used by the catch-up pass for missed days,
    where we don't have signal lists from those days and don't want to
    look ahead at today's signals to make past renewal decisions."""
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
        if not force_sell and ticker in top_quartile:
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
    # Dedupe by ticker first — market_signals has one row per ticker × horizon
    # (5d/20d/60d/120d), so the same name can appear up to 4 times. Without
    # dedupe the loop could buy the same ticker on two different horizon rows
    # and overwrite the holdings entry (wasting cash). Keep the best-ranked
    # row for each ticker by this portfolio's sort metric.
    candidates = (
        market_signals[~market_signals["ticker"].isin(held)]
        .dropna(subset=[sort_col])
        .sort_values(sort_col, ascending=False)
        .drop_duplicates(subset=["ticker"], keep="first")
        .reset_index(drop=True)
    )
    candidates = _apply_regime_tilt(candidates, _load_regime_penalties())

    target_position_size = total_value / MAX_POSITIONS
    # Belt-and-suspenders: track tickers bought during THIS loop so even if
    # dedupe ever misses one, we still won't double-buy.
    bought_tickers: set[str] = set()

    available_slots = MAX_POSITIONS - len(port["holdings"])
    if available_slots <= 0:
        return 0

    bought = 0
    for _, row in candidates.iterrows():
        if bought >= available_slots:
            break
        if port["cash"] < MIN_POSITION_VALUE:
            break
        ticker_candidate = str(row["ticker"])
        if ticker_candidate in bought_tickers or ticker_candidate in port["holdings"]:
            continue

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
        ticker = ticker_candidate
        bought_tickers.add(ticker)
        regime_penalty = float(row.get("_regime_penalty", 0.0))
        port["holdings"][ticker] = {
            "shares":         round(shares, 4),
            "entry_price":    round(price, 4),
            "entry_date":     run_date,
            "entry_edge":     round(float(row.get("edge", 0)), 4),
            "entry_p90":      round(float(row.get("p90", 0)), 4) if "p90" in row.index else None,
            "entry_p10":      round(float(row.get("p10", 0)), 4) if "p10" in row.index else None,
            "name":           str(row.get("name", "") or ""),
            "sector":         str(row.get("sector", "Unknown")),
            "horizon":        str(row.get("horizon", "20d")),
            "sort_col":       sort_col,
            "sort_value":     round(float(row.get(sort_col, 0)), 4),
            "regime_penalty": round(regime_penalty, 3),
            "current_price":  round(price, 4),
            "current_value":  round(shares * price, 2),
            "pnl_pct":        0.0,
        }
        port["transactions"].append({
            "date":           run_date,
            "action":         "buy",
            # Tag every buy with WHY it qualified — the dashboard's Trade Log
            # Reason column was blank for buys because nothing populated it.
            "reason":         f"top_{sort_col}",
            "ticker":         ticker,
            "shares":         round(shares, 4),
            "price":          round(price, 4),
            "value":          round(value, 2),
            "sort_col":       sort_col,
            "sort_value":     round(float(row.get(sort_col, 0)), 4),
            "horizon":        str(row.get("horizon", "20d")),
            "regime_penalty": round(regime_penalty, 3),
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

    # First pass: backfill missing name + sector on all holdings, regardless
    # of whether the portfolio will be re-processed for trades today. This
    # heals older portfolio.json entries that were saved before name was
    # captured at buy time.
    total_patched = 0
    for port in state.values():
        total_patched += _backfill_holding_metadata(port, market_signals)
    if total_patched:
        print(f"  Backfilled {total_patched} missing name/sector field(s)", flush=True)

    # Backfill reason + horizon on legacy buy transactions (older entries
    # were saved before these fields were tagged at buy time; the dashboard
    # showed blank Reason and couldn't render the horizon chip in the log).
    tx_patched = 0
    for port in state.values():
        # ticker -> horizon from currently-held positions (the only source we
        # have for closed positions is the matching sell reason like
        # horizon_exit_20d, which we don't bother parsing here).
        held_horizons = {
            tk: pos.get("horizon")
            for tk, pos in port.get("holdings", {}).items()
            if pos.get("horizon")
        }
        for tx in port.get("transactions", []):
            if tx.get("action") != "buy":
                continue
            if not (tx.get("reason") or "").strip():
                sc = tx.get("sort_col")
                if sc:
                    tx["reason"] = f"top_{sc}"
                    tx_patched += 1
            if not tx.get("horizon"):
                hz = held_horizons.get(tx.get("ticker"))
                if hz:
                    tx["horizon"] = hz
                    tx_patched += 1
    if tx_patched:
        print(f"  Backfilled reason/horizon on {tx_patched} legacy transaction(s)", flush=True)

    # Catch-up pass: when the daily cron skips one or more business days,
    # process horizon exits for each missed day so positions don't carry
    # past their intended exit dates. Signal-decay exits and new buys are
    # NOT run for missed days — we don't have signal lists from those
    # dates, and we won't look ahead at today's signals to make past
    # decisions. The catch-up is conservative: it always SELLS at horizon
    # expiry rather than renewing. Cash freed gets redeployed in today's
    # main pass.
    _catchup_missed_days(state, prices, run_dt, market_signals)

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
        total_invested = _mark_holdings(port, prices, run_dt, market_signals)
        total_value    = port["cash"] + total_invested

        # 2a. Signal-decay exits — sell names that dropped out of signals
        #     after being held more than half their horizon
        n_decayed = _do_signal_decay_exits(port, market_signals, run_date, run_dt)
        if n_decayed:
            total_invested = _mark_holdings(port, prices, run_dt, market_signals)
            total_value    = port["cash"] + total_invested

        # 2b. Horizon-based exits with stay-long-if-still-strong renewal
        n_sold, n_renewed = _do_horizon_exits(port, market_signals, run_date, run_dt)
        if n_sold:
            total_invested = _mark_holdings(port, prices, run_dt, market_signals)
            total_value    = port["cash"] + total_invested

        # 3. Continuous buying — deploy any free cash
        n_bought = _do_continuous_buy(port, market_signals, prices, run_date, run_dt, total_value)
        if n_bought:
            total_invested = _mark_holdings(port, prices, run_dt, market_signals)
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
