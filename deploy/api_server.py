"""
api_server.py — Cloud signal API for Regime Desk.

Computes ticker signals on demand using yfinance (no local database required).
Deploy to Render, Railway, or any Python host.

Endpoints:
  GET /api/ping              — health check
  GET /api/ticker?t=TICKER   — compute signal for TICKER
"""
import math
import os
import re
import threading
from datetime import date

import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, request

app = Flask(__name__)

SIMILAR_DAY_COUNT = 30
EXCLUDE_RECENT_DAYS = 30
MIN_OBSERVATIONS = 5
HORIZONS = {"5d": 5, "20d": 20, "60d": 60, "120d": 120}

_state = {
    "spy_df": None,
    "analog_dates": None,
    "ticker_cache": {},
    "last_refresh": None,
    "lock": threading.Lock(),
}


# ── CORS ──────────────────────────────────────────────────────────────────────

@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@app.route("/api/ping", methods=["OPTIONS"])
@app.route("/api/ticker", methods=["OPTIONS"])
def _options():
    return "", 200


# ── SPY features ──────────────────────────────────────────────────────────────

def _fetch_spy():
    hist = yf.Ticker("SPY").history(period="5y", auto_adjust=True)
    if hist.empty or len(hist) < 150:
        raise ValueError("Insufficient SPY data from yfinance")
    close = hist["Close"]
    spy = pd.DataFrame({"close": close.values}, index=pd.to_datetime(close.index).tz_localize(None))
    spy["return_5"] = spy["close"].pct_change(5)
    spy["return_20"] = spy["close"].pct_change(20)
    spy["volatility"] = spy["close"].pct_change().rolling(20).std()
    rolling_max = spy["close"].rolling(60).max()
    spy["drawdown"] = (spy["close"] - rolling_max) / rolling_max
    return spy.dropna()


def _compute_analog_dates(spy_df):
    vec = np.array([spy_df.iloc[-1][c] for c in ["return_5", "return_20", "volatility", "drawdown"]])
    hist = spy_df.iloc[:-EXCLUDE_RECENT_DAYS].copy()
    cols = ["return_5", "return_20", "volatility", "drawdown"]
    hist["dist"] = hist[cols].apply(lambda r: float(np.linalg.norm(r.values - vec)), axis=1)
    similar = hist.nsmallest(SIMILAR_DAY_COUNT, "dist")
    return set(similar.index.strftime("%Y-%m-%d"))


def _restricted_analog_dates(spy_df, ticker_start, count=20):
    """Find best SPY analog days within a recently-listed ticker's date range."""
    vec = np.array([spy_df.iloc[-1][c] for c in ["return_5", "return_20", "volatility", "drawdown"]])
    cutoff = spy_df.index[-EXCLUDE_RECENT_DAYS]
    cols = ["return_5", "return_20", "volatility", "drawdown"]
    hist = spy_df[(spy_df.index >= ticker_start) & (spy_df.index <= cutoff)].copy()
    if len(hist) < 3:
        return set()
    hist["dist"] = hist[cols].apply(lambda r: float(np.linalg.norm(r.values - vec)), axis=1)
    similar = hist.nsmallest(min(count, len(hist)), "dist")
    return set(similar.index.strftime("%Y-%m-%d"))


def _ensure_spy():
    """Return (spy_df, analog_dates), fetched once per calendar day."""
    with _state["lock"]:
        today = str(date.today())
        if _state["last_refresh"] == today and _state["spy_df"] is not None:
            return _state["spy_df"], _state["analog_dates"]
        print("[api] Fetching SPY from yfinance...", flush=True)
        spy_df = _fetch_spy()
        analog_dates = _compute_analog_dates(spy_df)
        _state["spy_df"] = spy_df
        _state["analog_dates"] = analog_dates
        _state["last_refresh"] = today
        _state["ticker_cache"] = {}
        print(f"[api] SPY ready — {len(analog_dates)} analog dates", flush=True)
        return spy_df, analog_dates


# ── Signal computation ────────────────────────────────────────────────────────

def _signal_for_dates(prices, analog_dates, ticker, med_vol, min_obs, short_history=False):
    best = None
    best_nobs = -1
    for label, days in HORIZONS.items():
        future = prices["close"].shift(-days) / prices["close"] - 1
        valid = prices.assign(fr=future).dropna(subset=["fr"])
        if len(valid) < 10:
            continue
        baseline = float(valid["fr"].median())
        analog_rows = valid[valid["ds"].isin(analog_dates)]
        n = len(analog_rows)
        if n < min_obs:
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
                "sector": "Unknown",
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
                "short_history": short_history,
                "source": "cloud",
            }
    return best


def _compute_ticker(ticker):
    spy_df, analog_dates = _ensure_spy()

    cache_key = f"{ticker}:{_state['last_refresh']}"
    if cache_key in _state["ticker_cache"]:
        return _state["ticker_cache"][cache_key]

    hist = yf.Ticker(ticker).history(period="5y", auto_adjust=True)
    if hist.empty or len(hist) < 30:
        return None

    close = hist["Close"]
    daily_ret = close.pct_change()
    vol = daily_ret.rolling(20).std()

    prices = pd.DataFrame({
        "date": pd.to_datetime(close.index).tz_localize(None),
        "close": close.values,
        "volatility": vol.values,
    }).dropna(subset=["close"]).reset_index(drop=True)
    prices = prices.drop_duplicates(subset=["date"]).reset_index(drop=True)
    prices["ds"] = prices["date"].dt.strftime("%Y-%m-%d")
    med_vol = float(prices["volatility"].median())

    best = _signal_for_dates(prices, analog_dates, ticker, med_vol, MIN_OBSERVATIONS)
    if best is None:
        restricted = _restricted_analog_dates(spy_df, prices["date"].min())
        if restricted:
            best = _signal_for_dates(prices, restricted, ticker, med_vol, min_obs=3, short_history=True)

    _state["ticker_cache"][cache_key] = best
    return best


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/api/ping")
def ping():
    return jsonify({"ok": True, "source": "cloud", "port": 0})


@app.route("/api/ticker")
def ticker():
    t = re.sub(r"[^A-Z0-9.]", "", request.args.get("t", "").strip().upper())
    if not t:
        return jsonify({"error": "missing ?t=TICKER"}), 400
    print(f"[api] Computing {t}...", flush=True)
    try:
        signal = _compute_ticker(t)
    except Exception as exc:
        print(f"[api] {t}: ERROR — {exc}", flush=True)
        return jsonify({"error": f"computation failed: {exc}"}), 500
    if signal:
        flag = " [below threshold]" if signal["below_threshold"] else ""
        print(f"[api] {t}: edge={signal['edge']:+.1%} ({signal['horizon']}, n={signal['n_obs']}){flag}", flush=True)
        return jsonify(signal)
    print(f"[api] {t}: not found or insufficient data", flush=True)
    return jsonify({"error": f"{t} not found or insufficient data"}), 404


# ── Startup ───────────────────────────────────────────────────────────────────

def _warmup():
    try:
        _ensure_spy()
    except Exception as exc:
        print(f"[api] Warmup failed: {exc}", flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[api] Regime Desk Cloud API -> http://0.0.0.0:{port}", flush=True)
    threading.Thread(target=_warmup, daemon=True).start()
    app.run(host="0.0.0.0", port=port, threaded=False)
