"""
CI scan — self-contained port of market_condition_scan.py for GitHub Actions.
Downloads price history from yfinance, computes features in-memory,
runs the same analog-matching + edge calculation, and writes:
  data/market_signals.csv
  data/theme_summary.csv
  data/spy_state.json
"""
import json
import os
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

ROOT      = Path(__file__).parent.parent
DATA_DIR  = ROOT / "data"
UNIV_FILE = Path(__file__).parent / "universe_ci.csv"

# ── Parameters (mirror market_condition_scan.py) ──────────────────────────────
MIN_EDGE           = 0.05
STABILITY_VOL_LIMIT = 0.05
SIMILAR_DAY_COUNT  = 30
EXCLUDE_RECENT_DAYS = 30
MIN_OBSERVATIONS   = 5
HORIZONS           = {"5d": 5, "20d": 20, "60d": 60, "120d": 120}
LOOKBACK_YEARS     = 3          # years of price history to download
BATCH_SIZE         = 200        # tickers per yfinance batch
RETRY_DELAY        = 5          # seconds between retries


def _download_batch(tickers: list[str], period: str) -> pd.DataFrame:
    """Download OHLCV for a batch; returns Close prices as DataFrame."""
    for attempt in range(3):
        try:
            raw = yf.download(
                tickers,
                period=period,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw.empty:
                return pd.DataFrame()
            # yfinance returns MultiIndex columns when len(tickers) > 1
            if isinstance(raw.columns, pd.MultiIndex):
                close = raw["Close"]
            else:
                close = raw[["Close"]].rename(columns={"Close": tickers[0]})
            return close
        except Exception as e:
            print(f"  Batch attempt {attempt+1} failed: {e}", flush=True)
            time.sleep(RETRY_DELAY)
    return pd.DataFrame()


def download_prices(tickers: list[str]) -> pd.DataFrame:
    """Download close prices for all tickers in batches. Returns wide DataFrame."""
    period = f"{LOOKBACK_YEARS}y"
    frames = []
    total = len(tickers)
    for i in range(0, total, BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        print(f"  Downloading {i+1}–{min(i+BATCH_SIZE, total)} / {total} ...", flush=True)
        chunk = _download_batch(batch, period)
        if not chunk.empty:
            frames.append(chunk)
    if not frames:
        raise RuntimeError("No price data downloaded")
    prices = pd.concat(frames, axis=1)
    prices = prices.loc[:, ~prices.columns.duplicated()]
    return prices


def compute_features(prices: pd.DataFrame) -> pd.DataFrame:
    """
    Compute rolling features matching the features table schema:
      return_5, return_20, volatility (20d realized), drawdown (60d)
    Returns long-format DataFrame: ticker, date, return_5, return_20, volatility, drawdown, close
    """
    rows = []
    for ticker in prices.columns:
        s = prices[ticker].dropna()
        if len(s) < 130:
            continue
        ret = s.pct_change()
        r5  = s.pct_change(5)
        r20 = s.pct_change(20)
        vol = ret.rolling(20).std()
        # 60-day drawdown: (price / rolling 60d max) - 1
        roll_max = s.rolling(60, min_periods=1).max()
        dd = s / roll_max - 1

        df_t = pd.DataFrame({
            "ticker":    ticker,
            "date":      s.index,
            "close":     s.values,
            "return_5":  r5.values,
            "return_20": r20.values,
            "volatility":vol.values,
            "drawdown":  dd.values,
        })
        rows.append(df_t.dropna())
    if not rows:
        raise RuntimeError("No features computed")
    return pd.concat(rows, ignore_index=True)


def run_scan(df: pd.DataFrame, sectors_df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Identical logic to market_condition_scan.py.
    df: long-format features + close
    sectors_df: ticker, sector, industry, name
    Returns (market_signals, theme_summary)
    """
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values(["ticker", "date"])

    spy = df[df["ticker"] == "SPY"].copy().sort_values("date")
    if len(spy) < 150:
        raise RuntimeError("Not enough SPY history")

    today = spy.iloc[-1]
    current_vector = today[["return_5", "return_20", "volatility", "drawdown"]].values.astype(float)
    print(f"\nSPY state: ret5={today.return_5:.4f} ret20={today.return_20:.4f} "
          f"vol={today.volatility:.4f} dd={today.drawdown:.4f}", flush=True)

    def distance(row):
        vec = row[["return_5", "return_20", "volatility", "drawdown"]].values.astype(float)
        return np.linalg.norm(vec - current_vector)

    # Z-score normalise each feature across SPY history so all four dimensions
    # contribute equally regardless of their raw scale.
    FEATURES = ["return_5", "return_20", "volatility", "drawdown"]
    feature_mean = spy[FEATURES].mean()
    feature_std  = spy[FEATURES].std().replace(0, 1)
    spy_norm     = (spy[FEATURES] - feature_mean) / feature_std
    current_norm = (pd.Series(dict(zip(FEATURES, current_vector))) - feature_mean) / feature_std

    spy["distance"] = np.linalg.norm(
        spy_norm.values - current_norm.values, axis=1
    )
    historical = spy.iloc[:-EXCLUDE_RECENT_DAYS]
    similar_days = historical.nsmallest(SIMILAR_DAY_COUNT, "distance")
    similar_dates = set(similar_days["date"])
    print(f"Found {len(similar_dates)} analog dates", flush=True)

    # Forward returns
    for label, days in HORIZONS.items():
        df[f"future_return_{label}"] = (
            df.groupby("ticker")["close"].shift(-days) / df["close"] - 1
        )

    # Volatility filter
    vol_by_ticker = df.groupby("ticker")["volatility"].median()
    stable_tickers = vol_by_ticker[vol_by_ticker < STABILITY_VOL_LIMIT].index
    filtered = df[df["date"].isin(similar_dates)].copy()
    filtered = filtered[filtered["ticker"].isin(stable_tickers)]

    all_signals = []
    all_themes  = []

    for label in HORIZONS:
        future_col = f"future_return_{label}"
        hf = filtered.dropna(subset=[future_col]).copy()
        counts = hf.groupby("ticker")[future_col].count()
        valid  = counts[counts >= MIN_OBSERVATIONS].index
        hf = hf[hf["ticker"].isin(valid)]

        baseline    = df.dropna(subset=[future_col]).groupby("ticker")[future_col].median()
        conditional = hf.groupby("ticker")[future_col].median()
        edge        = (conditional - baseline).dropna()

        # Empirical distribution per ticker from the analog returns
        dist_records = []
        for tkr, grp in hf.groupby("ticker")[future_col]:
            g = grp.dropna()
            dist_records.append({
                "ticker":   tkr,
                "p10":      float(g.quantile(0.10)),
                "p25":      float(g.quantile(0.25)),
                "p50":      float(g.quantile(0.50)),
                "p75":      float(g.quantile(0.75)),
                "p90":      float(g.quantile(0.90)),
                "hit_rate": float((g > 0).mean()),
                "n_obs":    int(len(g)),
            })
        dist_stats = pd.DataFrame(dist_records)

        results = edge.sort_values(ascending=False).reset_index()
        results.columns = ["ticker", "edge"]
        results["horizon"] = label
        results = results.merge(dist_stats, on="ticker", how="left")

        if not results.empty:
            pct_cut = results["edge"].quantile(0.95)
            strong  = results[(results["edge"] >= pct_cut) & (results["edge"] >= MIN_EDGE)].copy()
        else:
            strong = pd.DataFrame(columns=["ticker", "edge", "horizon",
                                            "p10", "p25", "p50", "p75", "p90", "hit_rate", "n_obs"])

        strong = strong.merge(sectors_df[["ticker","sector","industry","name"]], on="ticker", how="left")
        strong["sector"] = strong["sector"].fillna("Unknown")
        all_signals.append(strong)

        if not strong.empty:
            theme = (
                strong.groupby("sector")
                .agg(count=("ticker","count"), avg_edge=("edge","mean"), max_edge=("edge","max"))
                .reset_index()
            )
            theme["horizon"] = label
            all_themes.append(theme)
        print(f"  {label}: {len(strong)} signals", flush=True)

    market_signals = pd.concat(all_signals, ignore_index=True) if all_signals else pd.DataFrame()
    theme_summary  = pd.concat(all_themes,  ignore_index=True) if all_themes  else pd.DataFrame()

    if not market_signals.empty:
        market_signals = market_signals.sort_values(["horizon","edge"], ascending=[True,False])
    if not theme_summary.empty:
        theme_summary = theme_summary.sort_values(["horizon","avg_edge"], ascending=[True,False])

    return market_signals, theme_summary


# ── Cross-asset tickers ───────────────────────────────────────────────────────
CROSS_ASSET = {
    "TLT":  ("10Y+ Treasuries",  "rates"),
    "HYG":  ("High-Yield Credit","credit"),
    "GLD":  ("Gold",             "safe_haven"),
    "UUP":  ("USD Index",        "dollar"),
    "USO":  ("Crude Oil",        "commodities"),
    "^VIX": ("VIX",              "volatility"),
    "SMH":  ("Semiconductors",   "risk_on"),
    "IWM":  ("Russell 2000",     "risk_on"),
    "CPER": ("Copper",           "growth"),
    "TIP":  ("TIPS / Breakevens","inflation"),
    "QQQ":  ("Nasdaq 100",       "growth"),
    "XLF":  ("Financials",       "risk_on"),
}


def _ret(s: pd.Series, n: int) -> float:
    s = s.dropna()
    if len(s) < n + 1:
        return 0.0
    return float(s.iloc[-1] / s.iloc[-1 - n] - 1)


def _signal_from_ret(ret: float, asset_type: str) -> str:
    """Map a return to bullish/bearish/neutral given the asset's directionality."""
    # For safe-haven / defensive assets, positive return = risk-off = bearish for equities
    defensive = {"rates", "safe_haven", "volatility"}
    if asset_type in defensive:
        if ret > 0.02:   return "bearish"
        if ret < -0.02:  return "bullish"
        return "neutral"
    if ret > 0.02:   return "bullish"
    if ret < -0.02:  return "bearish"
    return "neutral"


def compute_cross_asset(spy_state: dict) -> dict:
    """
    Download ~12 cross-asset tickers, compute recent returns,
    derive signal readings and 7 risk axes.
    Returns dict with 'signals' and 'risks' lists.
    """
    print("Downloading cross-asset tickers ...", flush=True)
    tickers = list(CROSS_ASSET.keys())
    prices_raw = _download_batch(tickers, "1y")
    if prices_raw.empty:
        return {"signals": [], "risks": []}

    signals = []

    # SPY signals from spy_state
    signals.append({
        "name": "SPY 5-Day Return",
        "asset": "SPY",
        "value": f"{spy_state['ret_5d']*100:+.1f}%",
        "signal": "bullish" if spy_state["ret_5d"] > 0.005 else ("bearish" if spy_state["ret_5d"] < -0.005 else "neutral"),
        "context": "Short-term price momentum"
    })
    signals.append({
        "name": "SPY 20-Day Return",
        "asset": "SPY",
        "value": f"{spy_state['ret_20d']*100:+.1f}%",
        "signal": "bullish" if spy_state["ret_20d"] > 0.02 else ("bearish" if spy_state["ret_20d"] < -0.02 else "neutral"),
        "context": "Medium-term trend strength"
    })

    asset_data = {}
    for ticker, (label, atype) in CROSS_ASSET.items():
        col = ticker if ticker in prices_raw.columns else None
        if col is None:
            continue
        s = prices_raw[col].dropna()
        if len(s) < 25:
            continue
        r5  = _ret(s, 5)
        r20 = _ret(s, 20)
        asset_data[ticker] = {"s": s, "r5": r5, "r20": r20, "label": label, "atype": atype}

        if ticker == "^VIX":
            vix_val = float(s.iloc[-1])
            sig = "elevated" if vix_val > 25 else ("moderate" if vix_val > 18 else "bullish")
            signals.append({
                "name": "VIX Level",
                "asset": "VIX",
                "value": f"{vix_val:.1f}",
                "signal": sig,
                "context": "Below 18 = calm; 18–25 = caution; above 25 = fear"
            })
        else:
            sig = _signal_from_ret(r20, atype)
            context_map = {
                "TLT":  f"20d ret {r20*100:+.1f}% — {'bond rally = risk-off' if r20>0.02 else ('sell-off = rising rates' if r20<-0.02 else 'range-bound rates')}",
                "HYG":  f"20d ret {r20*100:+.1f}% — {'spread compression' if r20>0.01 else ('spread widening = credit stress' if r20<-0.01 else 'stable credit')}",
                "GLD":  f"20d ret {r20*100:+.1f}% — {'safe-haven bid / real rates falling' if r20>0.02 else 'no safe-haven premium'}",
                "UUP":  f"20d ret {r20*100:+.1f}% — {'dollar strength headwind for EM/commodities' if r20>0.01 else ('dollar weakness = risk-on' if r20<-0.01 else 'dollar neutral')}",
                "USO":  f"20d ret {r20*100:+.1f}% — {'energy bid; watch inflation pass-through' if r20>0.03 else ('demand concerns' if r20<-0.03 else 'stable oil')}",
                "SMH":  f"20d ret {r20*100:+.1f}% — {'semis leading; AI demand intact' if r20>0.02 else ('semi weakness; growth concerns' if r20<-0.02 else 'semis in line')}",
                "IWM":  f"20d ret {r20*100:+.1f}% — {'small-cap breadth expanding' if r20>0.02 else ('small caps lagging; risk-off rotation' if r20<-0.02 else 'mixed breadth')}",
                "CPER": f"20d ret {r20*100:+.1f}% — {'copper bid = growth optimism' if r20>0.02 else ('copper weak = growth concerns' if r20<-0.02 else 'copper flat')}",
                "TIP":  f"20d ret {r20*100:+.1f}% — {'breakevens rising = inflation re-pricing' if r20>0.01 else 'inflation expectations contained'}",
                "QQQ":  f"20d ret {r20*100:+.1f}% — {'growth leadership intact' if r20>0.02 else ('growth selling; value rotation' if r20<-0.02 else 'growth neutral')}",
                "XLF":  f"20d ret {r20*100:+.1f}% — {'financials leading; curve steepening favourable' if r20>0.02 else 'financials lagging'}",
            }
            signals.append({
                "name": label,
                "asset": ticker,
                "value": f"{r20*100:+.1f}% (20d)",
                "signal": sig,
                "context": context_map.get(ticker, f"20d return {r20*100:+.1f}%")
            })

    # ── Risk axes derived from cross-asset readings ───────────────────────────
    vix_val   = float(asset_data["^VIX"]["s"].iloc[-1]) if "^VIX" in asset_data else 18.0
    tlt_r20   = asset_data["TLT"]["r20"]  if "TLT"  in asset_data else 0.0
    hyg_r20   = asset_data["HYG"]["r20"]  if "HYG"  in asset_data else 0.0
    uup_r20   = asset_data["UUP"]["r20"]  if "UUP"  in asset_data else 0.0
    gld_r20   = asset_data["GLD"]["r20"]  if "GLD"  in asset_data else 0.0
    cper_r20  = asset_data["CPER"]["r20"] if "CPER" in asset_data else 0.0
    tip_r20   = asset_data["TIP"]["r20"]  if "TIP"  in asset_data else 0.0
    spy_vol   = spy_state["vol_20d"]
    spy_r20   = spy_state["ret_20d"]

    def _level(score):
        if score >= 0.65: return "elevated"
        if score >= 0.45: return "moderate"
        return "low"

    # Volatility regime risk
    vol_score = min(1.0, max(0.0, (vix_val - 12) / 28))
    # Credit stress: HYG falling = stress rising
    credit_score = min(1.0, max(0.0, 0.5 - hyg_r20 * 10))
    # Rate re-pricing: TLT selling off = rates rising
    rate_score = min(1.0, max(0.0, 0.5 - tlt_r20 * 8))
    # Growth slowdown: copper + small caps weak
    iwm_r20 = asset_data["IWM"]["r20"] if "IWM" in asset_data else 0.0
    growth_score = min(1.0, max(0.0, 0.5 - (cper_r20 + iwm_r20) * 3))
    # Inflation re-pricing: TIP rising
    infl_score = min(1.0, max(0.0, 0.3 + tip_r20 * 8))
    # Dollar headwind: UUP rising
    dollar_score = min(1.0, max(0.0, 0.4 + uup_r20 * 8))
    # Complacency: large rally + suppressed vol = setup for mean reversion
    vol_suppress_bonus = max(0.0, (0.015 - min(0.015, spy_vol)) / 0.015) * 0.3
    complacency_score  = min(1.0, max(0.0, spy_r20 * 4 + vol_suppress_bonus))

    risks = [
        {
            "name": "Volatility Regime",
            "level": _level(vol_score),
            "score": round(vol_score, 2),
            "description": f"VIX at {vix_val:.1f}. {'Elevated fear; tails wider than normal.' if vol_score>0.5 else 'Calm regime; vol suppression in force.'}",
            "invalidation": "VIX mean-reverts below 18 and holds for 5 sessions"
        },
        {
            "name": "Credit Stress",
            "level": _level(credit_score),
            "score": round(credit_score, 2),
            "description": f"HYG 20d {hyg_r20*100:+.1f}%. {'Spread widening signals funding stress.' if credit_score>0.5 else 'Credit broadly constructive; no systemic signal.'}",
            "invalidation": "HYG recovers to 20d positive return"
        },
        {
            "name": "Rate Re-pricing",
            "level": _level(rate_score),
            "score": round(rate_score, 2),
            "description": f"TLT 20d {tlt_r20*100:+.1f}%. {'Bond sell-off = rates rising; duration assets under pressure.' if rate_score>0.5 else 'Rates stable to falling; supportive for equities.'}",
            "invalidation": "TLT stabilises or rallies; 10Y yield falls below recent range"
        },
        {
            "name": "Growth Slowdown",
            "level": _level(growth_score),
            "score": round(growth_score, 2),
            "description": f"Copper 20d {cper_r20*100:+.1f}%, IWM {iwm_r20*100:+.1f}%. {'Cyclical indicators softening.' if growth_score>0.5 else 'Cyclicals constructive; growth fears not confirmed.'}",
            "invalidation": "Copper and IWM both sustain positive 20d momentum"
        },
        {
            "name": "Inflation Re-pricing",
            "level": _level(infl_score),
            "score": round(infl_score, 2),
            "description": f"TIPS 20d {tip_r20*100:+.1f}%. {'Breakevens rising; inflation expectations not anchored.' if infl_score>0.5 else 'Inflation expectations contained; Fed credibility intact.'}",
            "invalidation": "TIPS underperform nominal treasuries; breakevens fall"
        },
        {
            "name": "Dollar Headwind",
            "level": _level(dollar_score),
            "score": round(dollar_score, 2),
            "description": f"UUP 20d {uup_r20*100:+.1f}%. {'Strong dollar compresses EM earnings and commodity prices.' if dollar_score>0.5 else 'Dollar neutral to weak; no FX drag on multinationals.'}",
            "invalidation": "DXY loses 20d momentum; UUP 20d return goes negative"
        },
        {
            "name": "Complacency Risk",
            "level": _level(complacency_score),
            "score": round(complacency_score, 2),
            "description": f"SPY +{spy_r20*100:.1f}% / 20d with vol {spy_vol*100:.2f}%/day. {'Extended rally with suppressed vol — historically precedes sharp corrections.' if complacency_score>0.5 else 'Risk/return balance reasonable; no excess complacency signal.'}",
            "invalidation": "Vol expands above 1.2%/day or SPY 20d return pulls back below +3%"
        },
    ]

    print(f"Cross-asset: {len(signals)} signals, {len(risks)} risk axes", flush=True)
    return {"signals": signals, "risks": risks}


def main():
    DATA_DIR.mkdir(exist_ok=True)

    print("Loading universe ...", flush=True)
    sectors_df = pd.read_csv(UNIV_FILE)
    sectors_df["ticker"] = sectors_df["ticker"].str.upper().str.strip()
    tickers = sectors_df["ticker"].tolist()
    if "SPY" not in tickers:
        tickers.insert(0, "SPY")

    print(f"Downloading prices for {len(tickers)} tickers ({LOOKBACK_YEARS}y) ...", flush=True)
    prices = download_prices(tickers)
    print(f"Downloaded {len(prices.columns)} tickers, {len(prices)} trading days", flush=True)

    print("Computing features ...", flush=True)
    df = compute_features(prices)
    print(f"Features shape: {df.shape}", flush=True)

    print("Running scan ...", flush=True)
    market_signals, theme_summary = run_scan(df, sectors_df)

    # Save outputs
    market_signals.to_csv(DATA_DIR / "market_signals.csv", index=False)
    theme_summary.to_csv(DATA_DIR / "theme_summary.csv",  index=False)

    # Save SPY state + 20-day history for sparklines and regime streak
    spy_df = df[df["ticker"] == "SPY"].sort_values("date")
    spy_row = spy_df.iloc[-1]
    spy_state = {
        "ret_5d":       round(float(spy_row["return_5"]),  5),
        "ret_20d":      round(float(spy_row["return_20"]), 5),
        "vol_20d":      round(float(spy_row["volatility"]),5),
        "drawdown_60d": round(float(spy_row["drawdown"]),  5),
    }
    history_rows = spy_df.dropna(subset=["return_5","return_20","volatility","drawdown"]).tail(20)
    spy_state["history"] = [
        {
            "ret_5d":       round(float(r["return_5"]),  5),
            "ret_20d":      round(float(r["return_20"]), 5),
            "vol_20d":      round(float(r["volatility"]),5),
            "drawdown_60d": round(float(r["drawdown"]),  5),
        }
        for _, r in history_rows.iterrows()
    ]
    (DATA_DIR / "spy_state.json").write_text(json.dumps(spy_state, indent=2))

    # Cross-asset signals + risk axes
    cross_asset = compute_cross_asset(spy_state)
    (DATA_DIR / "cross_asset.json").write_text(json.dumps(cross_asset, indent=2))

    print(f"\nSaved {len(market_signals)} signals, {len(theme_summary)} theme rows", flush=True)
    print(f"SPY state: {spy_state}", flush=True)


if __name__ == "__main__":
    main()
