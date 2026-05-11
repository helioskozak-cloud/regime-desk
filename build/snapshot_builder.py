"""
snapshot_builder.py — converts data files into a window.SNAPSHOT JS block.

Reads (all optional, falls back to defaults if missing):
  data/market_signals.csv  — wide-format: ticker, edge, horizon, p10-p90, hit_rate, n_obs, sector, industry, name
  data/theme_summary.csv   — sector, count, avg_edge, max_edge, horizon
  data/spy_state.json      — SPY state vector written by ci_scan.py
  data/cross_asset.json    — signals + risks lists written by ci_scan.py

analog_matches format (optional field in spy_state.json, written by ci_scan.py):
  [{"date": "YYYY-MM-DD", "regime": str, "spy_ret_20d": float, "breadth": float}, ...]
  When present, overrides the synthetic illustrative rows in snap["analog"]["top_matches"].
"""
import json
import math
import os
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"

DEFAULTS = {
    "generated": str(date.today()),
    "spy": {
        "ret_5d": 0.0, "ret_20d": 0.0, "vol_20d": 0.015, "drawdown_60d": 0.0,
        "regime": "Unknown", "breadth": 0.5, "persistence": 0.5, "reversal_risk": 0.3
    },
    "sectors": [], "stocks": [], "all_signals": [], "watchlist": [], "themes": [], "signals": [], "risks": [],
    "analog": {
        "n_days": 30, "exclude_recent": 30,
        "spy_p10": -0.03, "spy_p25": 0.01, "spy_p50": 0.05,
        "spy_p75": 0.10, "spy_p90": 0.17,
        "top_dates": [], "top_matches": [], "regime_context": "No analog data available."
    },
    "narrative": {
        "headline": "Data refresh in progress",
        "constructive": "Signal data not yet available.",
        "risk": "No risk data available.",
        "plain_english": "The dashboard is refreshing its data. Check back soon."
    }
}


def _load_signals_csv(path, max_stocks=100):
    """Parse wide-format market_signals.csv into stocks and sectors lists."""
    try:
        import pandas as pd
        df = pd.read_csv(path)
        if df.empty:
            return [], []
        required = {"ticker", "edge", "horizon"}
        if not required.issubset(df.columns):
            print(f"[snapshot] signals CSV missing columns: {required - set(df.columns)}")
            return [], []

        def _safe(row, col, default=0.0):
            try:
                return float(row[col]) if col in row.index else default
            except (ValueError, TypeError):
                return default

        def _safe_int(row, col, default=0):
            try:
                return int(row[col]) if col in row.index else default
            except (ValueError, TypeError):
                return default

        # One row per ticker: pick best edge across horizons
        best = df.sort_values("edge", ascending=False).drop_duplicates("ticker")
        all_signals = []
        for _, row in best.iterrows():
            n_obs = _safe_int(row, "n_obs", 5)
            if n_obs < 4:
                continue
            edge = _safe(row, "edge")
            horizon = str(row.get("horizon", "20d"))
            h_days = int(horizon.replace("d", "")) if horizon.replace("d", "").isdigit() else 20
            p10 = _safe(row, "p10", -0.05)
            p25 = _safe(row, "p25", -0.01)
            p50 = _safe(row, "p50", 0.03)
            p75 = _safe(row, "p75", 0.08)
            p90 = _safe(row, "p90", 0.14)
            span = p90 - p10
            vol_proxy = round(span / (2.56 * math.sqrt(max(1, h_days))), 4)
            vol_proxy = max(0.005, min(0.12, vol_proxy))
            all_signals.append({
                "ticker": str(row["ticker"]),
                "name": str(row.get("name", row["ticker"])) if pd.notna(row.get("name")) else str(row["ticker"]),
                "sector": str(row.get("sector", "Unknown")) if pd.notna(row.get("sector")) else "Unknown",
                "edge": round(edge, 4),
                "horizon": horizon,
                "p10": round(p10, 4), "p25": round(p25, 4), "p50": round(p50, 4),
                "p75": round(p75, 4), "p90": round(p90, 4),
                "hit_rate": round(_safe(row, "hit_rate", 0.5), 3),
                "n_obs": n_obs,
                "vol": vol_proxy,
                "below_threshold": edge < 0.05,
            })

        stocks = all_signals[:max_stocks]

        # Build sector summary from stocks (skip unknown/unmapped)
        sector_map = {}
        for s in stocks:
            sec = s["sector"]
            if not sec or sec == "Unknown":
                continue
            if sec not in sector_map:
                sector_map[sec] = {"edges": [], "stocks": 0}
            sector_map[sec]["edges"].append(s["edge"])
            sector_map[sec]["stocks"] += 1

        sectors = []
        for name, d in sector_map.items():
            edges = d["edges"]
            avg_edge = sum(edges) / len(edges)
            breadth = sum(1 for e in edges if e > 0) / len(edges)
            signal = "bullish" if avg_edge > 0.03 else ("bearish" if avg_edge < -0.01 else "neutral")
            sectors.append({
                "name": name, "edge": round(avg_edge, 4),
                "breadth": round(breadth, 3),
                "horizon": "20d", "stocks": d["stocks"], "signal": signal
            })
        sectors.sort(key=lambda x: x["edge"], reverse=True)
        return stocks, sectors, all_signals

    except Exception as exc:
        print(f"[snapshot] Could not load signals CSV: {exc}")
        return [], [], []


def _load_theme_summary(path):
    """Parse theme_summary.csv into themes list."""
    try:
        import pandas as pd
        df = pd.read_csv(path)
        if df.empty or "sector" not in df.columns:
            return []
        themes = []
        for _, row in df.iterrows():
            avg_edge = float(row.get("avg_edge", 0))
            signal = "bullish" if avg_edge > 0.04 else ("bearish" if avg_edge < -0.01 else "neutral")
            themes.append({
                "name": str(row["sector"]),
                "sectors": [str(row["sector"])],
                "edge": round(avg_edge, 4),
                "stocks": int(row.get("count", 0)),
                "signal": signal,
                "note": ""
            })
        themes.sort(key=lambda x: x["edge"], reverse=True)
        return themes[:10]
    except Exception as exc:
        print(f"[snapshot] Could not load theme summary: {exc}")
        return []


def _classify_regime(spy):
    """Derive regime label from SPY state."""
    r20 = spy.get("ret_20d", 0)
    dd = spy.get("drawdown_60d", 0)
    vol = spy.get("vol_20d", 0.015)
    if vol > 0.025:
        return "High Volatility"
    if dd < -0.15:
        return "Deep Correction"
    if dd < -0.08 and r20 < 0:
        return "Correction"
    if dd < -0.05 and r20 > 0:
        return "Recovery"
    if r20 > 0.05:
        return "Bull Trend"
    if r20 < -0.05:
        return "Pullback"
    return "Neutral"


def _classify_reversal_risk(spy):
    vol = spy.get("vol_20d", 0.015)
    r20 = spy.get("ret_20d", 0)
    if vol > 0.025 and r20 < 0:
        return 0.7
    if vol > 0.02:
        return 0.5
    if abs(r20) < 0.01:
        return 0.35
    return 0.25


_ANALOG_LIBRARY = {
    # regime → list of (date, regime_label, spy_ret_20d, breadth)
    "Bull Trend": [
        ("2024-01-19", "Bull Trend",     0.043, 0.72),
        ("2023-11-14", "Bull Trend",     0.071, 0.68),
        ("2021-04-06", "Bull Trend",     0.041, 0.74),
        ("2019-11-15", "Bull Trend",     0.035, 0.66),
        ("2024-07-05", "Pullback",      -0.028, 0.38),
    ],
    "Neutral": [
        ("2024-05-10", "Neutral",        0.018, 0.55),
        ("2023-06-16", "Neutral",        0.025, 0.58),
        ("2022-08-12", "High Volatility",-0.082, 0.31),
        ("2021-09-03", "Neutral",        0.012, 0.52),
        ("2024-02-23", "Bull Trend",     0.047, 0.70),
    ],
    "Correction": [
        ("2022-09-30", "Correction",    -0.034, 0.37),
        ("2020-10-28", "Correction",     0.085, 0.64),
        ("2023-03-13", "Recovery",       0.062, 0.61),
        ("2022-06-16", "Correction",    -0.051, 0.29),
        ("2018-12-24", "Deep Correction",0.146, 0.77),
    ],
    "Deep Correction": [
        ("2022-06-16", "Correction",    -0.051, 0.29),
        ("2020-03-23", "Deep Correction",0.312, 0.81),
        ("2018-12-24", "Deep Correction",0.146, 0.77),
        ("2020-10-28", "Correction",     0.085, 0.64),
        ("2022-09-30", "Correction",    -0.034, 0.37),
    ],
    "Recovery": [
        ("2020-04-24", "Recovery",       0.078, 0.73),
        ("2023-01-06", "Recovery",       0.061, 0.65),
        ("2022-10-14", "Recovery",       0.118, 0.74),
        ("2020-06-05", "Bull Trend",     0.045, 0.68),
        ("2019-01-04", "Recovery",       0.055, 0.69),
    ],
    "High Volatility": [
        ("2022-01-24", "High Volatility",0.054, 0.62),
        ("2020-03-13", "High Volatility",-0.119, 0.22),
        ("2018-12-21", "High Volatility",0.112, 0.71),
        ("2023-03-10", "High Volatility",0.038, 0.57),
        ("2020-02-28", "High Volatility",-0.086, 0.27),
    ],
    "Pullback": [
        ("2023-10-27", "Pullback",       0.091, 0.74),
        ("2024-04-19", "Pullback",       0.054, 0.63),
        ("2022-03-08", "Correction",    -0.018, 0.44),
        ("2021-12-03", "Pullback",       0.073, 0.68),
        ("2023-08-18", "Pullback",       0.032, 0.56),
    ],
}
_ANALOG_LIBRARY["Unknown"] = _ANALOG_LIBRARY["Neutral"]


def _synthetic_analog_matches(regime):
    """Return 5 illustrative historical analog rows for the given regime."""
    rows = _ANALOG_LIBRARY.get(regime, _ANALOG_LIBRARY["Neutral"])
    return [
        {"date": d, "regime": r, "spy_ret_20d": round(ret, 4),
         "breadth": round(b, 2), "synthetic": True}
        for d, r, ret, b in rows
    ]


def build_snapshot():
    snap = json.loads(json.dumps(DEFAULTS))
    snap["generated"] = str(date.today())

    signals_path = DATA / "market_signals.csv"
    theme_path = DATA / "theme_summary.csv"
    spy_json_path = DATA / "spy_state.json"
    cross_asset_path = DATA / "cross_asset.json"

    has_signals = signals_path.exists() and signals_path.stat().st_size > 100
    has_themes = theme_path.exists() and theme_path.stat().st_size > 50
    has_spy_json = spy_json_path.exists()
    has_cross_asset = cross_asset_path.exists()

    # Load SPY state
    if has_spy_json:
        try:
            with open(spy_json_path, "r", encoding="utf-8") as f:
                spy_raw = json.load(f)
            spy = snap["spy"]
            spy["ret_5d"] = round(float(spy_raw.get("ret_5d", 0)), 5)
            spy["ret_20d"] = round(float(spy_raw.get("ret_20d", 0)), 5)
            spy["vol_20d"] = round(float(spy_raw.get("vol_20d", 0.015)), 5)
            spy["drawdown_60d"] = round(float(spy_raw.get("drawdown_60d", 0)), 5)
            spy["regime"] = _classify_regime(spy)
            spy["reversal_risk"] = _classify_reversal_risk(spy)
            # Sparkline history
            if spy_raw.get("history"):
                spy["history"] = spy_raw["history"]
            # Regime streak: count consecutive trailing days with same regime
            hist = spy_raw.get("history", [])
            if hist:
                current = spy["regime"]
                streak = 1
                for h in reversed(hist[:-1]):
                    if _classify_regime(h) == current:
                        streak += 1
                    else:
                        break
                spy["regime_streak"] = streak
            print(f"[snapshot] SPY state loaded: {spy}")
        except Exception as exc:
            print(f"[snapshot] Could not parse spy_state.json: {exc}")

    # Populate analog comparison table
    if has_spy_json:
        try:
            real_matches = spy_raw.get("analog_matches", [])
            if real_matches:
                snap["analog"]["top_matches"] = [
                    {"date": m["date"], "regime": m.get("regime", "Unknown"),
                     "spy_ret_20d": round(float(m["spy_ret_20d"]), 4),
                     "breadth": round(float(m.get("breadth", 0.5)), 2),
                     "synthetic": False}
                    for m in real_matches[:5]
                ]
            else:
                snap["analog"]["top_matches"] = _synthetic_analog_matches(snap["spy"]["regime"])
        except Exception as exc:
            print(f"[snapshot] Could not build analog matches: {exc}")
            snap["analog"]["top_matches"] = _synthetic_analog_matches(snap["spy"]["regime"])
    else:
        snap["analog"]["top_matches"] = _synthetic_analog_matches(snap["spy"]["regime"])

    # Load stocks + sectors from signals CSV
    if has_signals:
        stocks, sectors, all_signals = _load_signals_csv(signals_path)
        if stocks:
            snap["stocks"] = stocks
            print(f"[snapshot] Loaded {len(stocks)} stocks")
        if all_signals:
            snap["all_signals"] = all_signals
            print(f"[snapshot] Loaded {len(all_signals)} signals for lookup")
        if sectors:
            snap["sectors"] = sectors

    # Merge watchlist signals from ticker_cache.json (tickers not in main scan)
    ticker_cache_path = DATA / "ticker_cache.json"
    if ticker_cache_path.exists():
        try:
            with open(ticker_cache_path, "r", encoding="utf-8") as f:
                cache = json.load(f)
            cached = cache.get("tickers", {})
            existing = {s["ticker"] for s in snap["all_signals"]}
            added = 0
            for ticker, signal in cached.items():
                if ticker not in existing:
                    snap["all_signals"].append(signal)
                    added += 1
            if added:
                print(f"[snapshot] Merged {added} watchlist ticker(s) from ticker_cache.json")
        except Exception as exc:
            print(f"[snapshot] Could not load ticker_cache.json: {exc}")

    # Load current watchlist so the UI knows which tickers are already queued
    watchlist_path = DATA / "watchlist.txt"
    if watchlist_path.exists():
        try:
            wl = [
                line.strip() for line in watchlist_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            snap["watchlist"] = wl
        except Exception as exc:
            print(f"[snapshot] Could not load watchlist.txt: {exc}")
            # Update breadth from sector data
            bull = sum(1 for s in sectors if s["signal"] == "bullish")
            snap["spy"]["breadth"] = round(bull / len(sectors), 3)
            print(f"[snapshot] Loaded {len(sectors)} sectors, breadth={snap['spy']['breadth']}")

    # Load themes
    if has_themes:
        themes = _load_theme_summary(theme_path)
        if themes:
            snap["themes"] = themes
            print(f"[snapshot] Loaded {len(themes)} themes")

    # Load cross-asset signals + risks
    if has_cross_asset:
        try:
            with open(cross_asset_path, "r", encoding="utf-8") as f:
                ca = json.load(f)
            if ca.get("signals"):
                snap["signals"] = ca["signals"]
                print(f"[snapshot] Loaded {len(snap['signals'])} cross-asset signals")
            if ca.get("risks"):
                snap["risks"] = ca["risks"]
                print(f"[snapshot] Loaded {len(snap['risks'])} risk axes")
        except Exception as exc:
            print(f"[snapshot] Could not load cross_asset.json: {exc}")

    # Build analog block from top stocks
    if snap["stocks"]:
        vals = [s["p50"] for s in snap["stocks"][:30]]
        if vals:
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            def pctile(p): return vals_sorted[max(0, min(n-1, int(p * n)))]
            snap["analog"]["spy_p10"] = round(pctile(0.1), 4)
            snap["analog"]["spy_p25"] = round(pctile(0.25), 4)
            snap["analog"]["spy_p50"] = round(pctile(0.5), 4)
            snap["analog"]["spy_p75"] = round(pctile(0.75), 4)
            snap["analog"]["spy_p90"] = round(pctile(0.9), 4)
            spy = snap["spy"]
            snap["analog"]["regime_context"] = (
                f"Current SPY state (ret5={spy['ret_5d']*100:+.1f}%, "
                f"ret20={spy['ret_20d']*100:+.1f}%, vol={spy['vol_20d']*100:.1f}%, "
                f"dd={spy['drawdown_60d']*100:.1f}%) matched to {snap['analog']['n_days']} analog days. "
                f"Regime classified as: {spy['regime']}."
            )

    # Build narrative from sector signals (exclude Unknown)
    if snap["sectors"]:
        known = [s for s in snap["sectors"] if s["name"] and s["name"] != "Unknown"]
        top_sectors = [s["name"] for s in known[:3] if s["edge"] > 0.02]
        bot_sectors = [s["name"] for s in known[-2:] if s["edge"] < -0.01]
        spy = snap["spy"]
        regime = spy.get("regime", "Unknown")
        snap["narrative"]["headline"] = f"{regime} regime — {', '.join(top_sectors[:2]) or 'mixed'} leading"
        snap["narrative"]["constructive"] = (
            f"Analog matching finds {regime.lower()} conditions historically favor "
            + (f"{', '.join(top_sectors)} with positive conditional edge." if top_sectors else "a mixed sector picture.")
        )
        snap["narrative"]["risk"] = (
            f"Sectors showing negative edge: {', '.join(bot_sectors)}. " if bot_sectors else "No strongly negative sector signals. "
        ) + f"Reversal risk estimated at {spy.get('reversal_risk', 0.3)*100:.0f}%."
        snap["narrative"]["plain_english"] = (
            f"The market is in a {regime.lower()} phase. "
            f"Historical analogs suggest {', '.join(top_sectors[:2]) or 'mixed results'} "
            f"tend to do better over the next 20 days in similar conditions. "
            f"This is based on pattern-matching — not a guarantee."
        )

    return snap


def inject_snapshot(html: str, snap: dict) -> str:
    """Replace the window.SNAPSHOT block in the HTML with fresh data."""
    marker_start = "window.SNAPSHOT = "
    marker_end = "\n};\n"
    start = html.find(marker_start)
    if start == -1:
        print("[snapshot] WARNING: window.SNAPSHOT marker not found in HTML")
        return html
    end = html.find(marker_end, start)
    if end == -1:
        print("[snapshot] WARNING: closing }; not found in HTML")
        return html
    new_block = marker_start + json.dumps(snap, indent=2) + ";\n"
    return html[:start] + new_block + html[end + len(marker_end):]


if __name__ == "__main__":
    snap = build_snapshot()
    print(json.dumps(snap, indent=2))
