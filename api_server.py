"""
api_server.py — Cloud signal API for Regime Desk.

Computes ticker signals on demand using yfinance (no local database required).
Deploy to Render, Railway, or any Python host.

Endpoints:
  GET /api/ping              — health check
  GET /api/ticker?t=TICKER   — compute signal for TICKER
"""
import csv
import math
import os
import re
import threading
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, request

app = Flask(__name__)

SIMILAR_DAY_COUNT = 30
EXCLUDE_RECENT_DAYS = 30
MIN_OBSERVATIONS = 5
HORIZONS = {"5d": 5, "20d": 20, "60d": 60, "120d": 120}
# Analog days within this many trading days are the same regime "episode" — their
# forward windows overlap almost entirely, so the de-clustered hit trio collapses
# each run to one episode to avoid counting the same spell many times.
EPISODE_GAP_DAYS = 10

_state = {
    "spy_df": None,
    "analog_dates": None,
    "ticker_cache": {},
    "last_refresh": None,
    "lock": threading.Lock(),
}

def _load_sector_map() -> dict[str, str]:
    """ticker -> sector, read from scan/universe_ci.csv.

    This used to be a 343-line literal here — 44% of the file — and it was a
    VERBATIM DUPLICATE of that CSV's `sector` column: on 2026-08-18 all 1,351
    entries matched, none differed. Two copies of the same fact, one of them
    hand-maintained, so every universe change silently left the map behind. It
    had drifted 612 tickers behind the universe, including every name added in
    the refresh, which meant finvisible and sim-desk could not theme any of them.

    The universe is the source. Nothing else gets to hold a second copy.
    """
    path = Path(__file__).parent / "scan" / "universe_ci.csv"
    out: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            t = str(row.get("ticker", "")).upper().strip()
            s = str(row.get("sector", "") or "").strip()
            if t and s:
                out[t] = s
    return out


_SECTOR_MAP = _load_sector_map()


# ── CORS ──────────────────────────────────────────────────────────────────────

@app.after_request
def _cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    # Chrome 104+ Private Network Access — required for HTTPS pages
    # (like the GitHub Pages dashboard) to reach localhost. Without
    # this the preflight succeeds but the browser silently blocks the
    # actual request before it ever shows up in the network panel.
    response.headers["Access-Control-Allow-Private-Network"] = "true"
    return response


@app.route("/api/ping", methods=["OPTIONS"])
@app.route("/api/ticker", methods=["OPTIONS"])
@app.route("/api/quote", methods=["OPTIONS"])
@app.route("/api/sim/log", methods=["OPTIONS"])
@app.route("/api/sim/feed", methods=["OPTIONS"])
def _options():
    return "", 200


# ── Sim-desk intern telemetry ─────────────────────────────────────────────────
# The paper-trading simulator posts trade and daily-snapshot events here so the
# owner can watch activity and build daily reports ON THIS MACHINE. Append-only
# JSONL with size-capped fields; paper trades only, nothing sensitive, and the
# log never leaves this box.
SIM_LOG_PATH = r"C:\Portfolizer\sim-logs\events.jsonl"


@app.route("/api/sim/log", methods=["POST"])
def sim_log():
    import json as _json
    try:
        evt = request.get_json(force=True, silent=True) or {}
        rec = {
            "received": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
            "trader":   str(evt.get("trader", "intern"))[:40],
            "type":     str(evt.get("type", "?"))[:20],
        }
        for k in ("t", "side", "qty", "px", "value", "cash", "total",
                  "spy", "as_of", "ts"):
            if k in evt:
                v = evt[k]
                rec[k] = v[:40] if isinstance(v, str) else v
        os.makedirs(os.path.dirname(SIM_LOG_PATH), exist_ok=True)
        with open(SIM_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(_json.dumps(rec) + "\n")
        return jsonify({"ok": True})
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500


@app.route("/api/sim/feed", methods=["GET"])
def sim_feed():
    """Read-back of the intern telemetry for the supervisor dashboard.

    Returns the most recent events (paper-trading only). Read-only — it never
    writes — reading the same append-only log the POST handler above appends to.
    The dashboard (a GitHub Pages page) reaches this through the same tunnel the
    intern's app uses; CORS is handled globally by _cors().
    """
    import json as _json
    try:
        limit = min(max(int(request.args.get("limit", 2000)), 1), 10000)
    except Exception:
        limit = 2000
    events = []
    if os.path.exists(SIM_LOG_PATH):
        try:
            with open(SIM_LOG_PATH, "r", encoding="utf-8") as f:
                lines = f.readlines()[-limit:]
        except Exception as exc:
            return jsonify({"ok": False, "error": str(exc)}), 500
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                events.append(_json.loads(line))
            except Exception:
                continue
    return jsonify({"ok": True, "count": len(events),
                    "server_time": pd.Timestamp.utcnow().isoformat(timespec="seconds"),
                    "events": events})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _to_naive_index(index):
    """Return a tz-naive DatetimeIndex regardless of whether input has a timezone."""
    idx = pd.to_datetime(index)
    if idx.tz is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    return idx


# ── SPY features ──────────────────────────────────────────────────────────────

def _fetch_spy():
    hist = yf.Ticker("SPY").history(period="5y", auto_adjust=True)
    if hist.empty or len(hist) < 150:
        raise ValueError("Insufficient SPY data from yfinance")
    close = hist["Close"]
    spy = pd.DataFrame({"close": close.values}, index=_to_naive_index(close.index))
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

def _signal_for_dates(prices, analog_dates, ticker, med_vol, min_obs, short_history=False,
                      spy_df=None):
    """Return {label: signal_dict} for every horizon that meets min_obs.

    Each horizon carries a TRIO of hit rates over the same analog-day sample:
      hit_rate  (Hit edge)  — share of analog days with a positive forward return.
      hit_self              — share beating the stock's OWN all-history median
                              forward return (the per-obs sign of `edge`).
      hit_alpha             — share beating SPY's forward return over the SAME
                              window measured from the SAME analog date. Requires
                              `spy_df`; None when it can't be aligned.
    """
    results = {}
    # SPY forward returns per horizon, keyed by date string, so Hit(alpha) can
    # compare each analog day's stock return to SPY's return over the same
    # forward window from that same date.
    spy_fr_by_ds = {}
    if spy_df is not None:
        spy_ds = spy_df.index.strftime("%Y-%m-%d")
        for _lbl, _d in HORIZONS.items():
            _fut = spy_df["close"].shift(-_d) / spy_df["close"] - 1
            spy_fr_by_ds[_lbl] = pd.Series(_fut.values, index=spy_ds)
    for label, days in HORIZONS.items():
        future = prices["close"].shift(-days) / prices["close"] - 1
        valid = prices.assign(fr=future).dropna(subset=["fr"])
        if len(valid) < 10:
            continue
        baseline = float(valid["fr"].median())
        analog_rows = valid[valid["ds"].isin(analog_dates)].sort_index()
        n = len(analog_rows)
        if n < min_obs:
            continue
        vals = analog_rows["fr"].values
        cond = float(np.median(vals))
        edge = round(cond - baseline, 4)
        pcts = np.percentile(vals, [10, 25, 50, 75, 90])
        hit = round(float((vals > 0).mean()), 3)
        hit_self = round(float((vals > baseline).mean()), 3)
        # SPY forward return aligned per analog row (for the alpha comparisons).
        if label in spy_fr_by_ds:
            spy_aligned = spy_fr_by_ds[label].reindex(analog_rows["ds"].values).values.astype(float)
        else:
            spy_aligned = np.full(n, np.nan)
        amask = ~np.isnan(spy_aligned)
        hit_alpha = (round(float((vals[amask] > spy_aligned[amask]).mean()), 3)
                     if int(amask.sum()) >= 1 else None)

        # De-clustered ("episode") hit trio: adjacent analog days are the same
        # regime spell with near-identical forward windows, so collapse runs
        # within EPISODE_GAP_DAYS trading days into one episode, represent each
        # by its members' median outcome, and take the hit over episodes. n_obs
        # stays the raw analog count; n_episodes is the independent-ish sample.
        pos = analog_rows.index.to_numpy()
        bounds = [0] + [i for i in range(1, n) if pos[i] - pos[i - 1] > EPISODE_GAP_DAYS] + [n]
        ep_fr, ep_alpha = [], []
        for a_, b_ in zip(bounds[:-1], bounds[1:]):
            ep_fr.append(float(np.median(vals[a_:b_])))
            seg = spy_aligned[a_:b_]
            sm = ~np.isnan(seg)
            if int(sm.sum()):
                ep_alpha.append(float(np.median(vals[a_:b_][sm] - seg[sm])))
        ep_fr = np.array(ep_fr)
        n_ep = len(ep_fr)
        hit_dc = round(float((ep_fr > 0).mean()), 3) if n_ep else None
        hit_self_dc = round(float((ep_fr > baseline).mean()), 3) if n_ep else None
        hit_alpha_dc = (round(float((np.array(ep_alpha) > 0).mean()), 3)
                        if len(ep_alpha) else None)

        results[label] = {
            "edge":            edge,
            "n_obs":           n,
            "n_episodes":      n_ep,
            "p10":             round(float(pcts[0]), 4),
            "p25":             round(float(pcts[1]), 4),
            "p50":             round(float(pcts[2]), 4),
            "p75":             round(float(pcts[3]), 4),
            "p90":             round(float(pcts[4]), 4),
            "hit_rate":        hit,
            "hit_alpha":       hit_alpha,
            "hit_self":        hit_self,
            "hit_rate_dc":     hit_dc,
            "hit_alpha_dc":    hit_alpha_dc,
            "hit_self_dc":     hit_self_dc,
            "vol":             round(med_vol, 4),
            "below_threshold": edge < 0.05,
            "short_history":   short_history,
        }
    return results


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
        "date": _to_naive_index(close.index),
        "close": close.values,
        "volatility": vol.values,
    }).dropna(subset=["close"]).reset_index(drop=True)
    prices = prices.drop_duplicates(subset=["date"]).reset_index(drop=True)
    prices["ds"] = prices["date"].dt.strftime("%Y-%m-%d")
    med_vol = float(prices["volatility"].median())

    horizons = _signal_for_dates(prices, analog_dates, ticker, med_vol, MIN_OBSERVATIONS,
                                 spy_df=spy_df)
    short_history = False
    if not horizons:
        restricted = _restricted_analog_dates(spy_df, prices["date"].min())
        if restricted:
            horizons = _signal_for_dates(prices, restricted, ticker, med_vol,
                                          min_obs=3, short_history=True, spy_df=spy_df)
            short_history = bool(horizons)

    if not horizons:
        _state["ticker_cache"][cache_key] = None
        return None

    recent = [round(float(v), 2) for v in close.values[-7:]]
    best_edge = max(h["edge"] for h in horizons.values())

    result = {
        "ticker":          ticker,
        "name":            ticker,
        "sector":          _SECTOR_MAP.get(ticker, "Unknown"),
        "from_watchlist":  True,
        "short_history":   short_history,
        "below_threshold": best_edge < 0.05,
        "source":          "cloud",
        "horizons":        horizons,
    }
    if len(recent) >= 2:
        result["week_closes"] = recent
        result["price"]       = recent[-1]
        result["change_pct"]  = round((recent[-1] - recent[-2]) / recent[-2], 4)

    _state["ticker_cache"][cache_key] = result
    return result


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/api/ping")
def ping():
    spy_ready = _state["spy_df"] is not None
    return jsonify({"ok": True, "source": "cloud", "port": 0, "spy_ready": spy_ready})


@app.route("/api/quote")
def quote():
    t = re.sub(r"[^A-Z0-9.]", "", request.args.get("t", "").strip().upper())
    if not t:
        return jsonify({"error": "missing ?t=TICKER"}), 400
    cache_key = f"quote:{t}:{date.today()}"
    if cache_key in _state["ticker_cache"]:
        return jsonify(_state["ticker_cache"][cache_key])
    try:
        hist = yf.Ticker(t).history(period="12d", auto_adjust=True)
        if hist.empty or len(hist) < 2:
            return jsonify({"error": "insufficient data"}), 404
        closes = [round(float(v), 2) for v in hist["Close"].values]
        prev = closes[-2]
        curr = closes[-1]
        result = {
            "ticker": t,
            "price": curr,
            "prev_close": prev,
            "change_pct": round((curr - prev) / prev, 4),
            "week_closes": closes[-7:],
        }
        _state["ticker_cache"][cache_key] = result
        return jsonify(result)
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


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
        edges = ", ".join(f"{lbl}:{h['edge']:+.0%}(n={h['n_obs']})"
                          for lbl, h in signal.get("horizons", {}).items())
        print(f"[api] {t}: {edges}{flag}", flush=True)
        return jsonify(signal)
    print(f"[api] {t}: not found or insufficient data", flush=True)
    return jsonify({"error": f"{t} not found or insufficient data"}), 404


# ── Warmup — runs immediately when module is imported (gunicorn or direct) ────

def _warmup():
    try:
        _ensure_spy()
        print("[api] Warmup complete.", flush=True)
    except Exception as exc:
        print(f"[api] Warmup failed: {exc}", flush=True)


threading.Thread(target=_warmup, daemon=True).start()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    print(f"[api] Regime Desk Cloud API -> http://0.0.0.0:{port}", flush=True)
    # Use waitress (production-grade pure-Python WSGI server) instead of
    # Flask's dev server. The dev server crashed intermittently on Windows
    # under cross-origin preflight traffic with no traceback — waitress is
    # stable, handles concurrent connections cleanly, and falls back to
    # Flask's dev server only if waitress isn't installed.
    try:
        from waitress import serve
        print(f"[api] Serving with waitress on port {port}", flush=True)
        serve(app, host="0.0.0.0", port=port, threads=4)
    except ImportError:
        print("[api] waitress not installed; falling back to Flask dev server", flush=True)
        app.run(host="0.0.0.0", port=port, threaded=False)