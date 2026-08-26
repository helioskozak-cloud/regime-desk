"""
econ_scan.py — FRED macro snapshot for the #econ dashboard view (standalone,
read-side; no V2 decision-path involvement).

Pulls a small set of series from FRED's keyless fredgraph.csv endpoint and
writes data/econ.json: per series, up to ~5y of weekly history (the dashboard
toggles a 1y / 2y / 5y view over it, defaulting to 1y) plus the latest value
and a short-window change. Fail-soft per series — a missing series shows as
absent in the UI, never breaks the build.

ALSO writes a `curve` block: the full Treasury constant-maturity curve as a
cross-section (yield by tenor, today) plus ~3y of DAILY history per tenor.

The daily history exists for one specific downstream consumer: finvisible
measures a bond fund's EMPIRICAL duration by regressing the fund's daily
returns on daily changes in Treasury yields. That needs daily observations,
which the display `series` above cannot supply — it is weekly-resampled for
charting. The two blocks are shaped for different jobs and are built from the
SAME fetch, so a tenor appearing in both is one fetch reported twice, never
two independently-maintained copies of one number.
"""
import io
import json
import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "econ.json"
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}"
YEARS = 5   # max history stored; the dashboard toggles a 1y/2y/5y view over it

# sid → (label, unit, transform)
# transform: raw | yoy_pct (12m % change) | mom_diff (1m difference)
SERIES = {
    "T10Y2Y":       ("10Y minus 2Y Treasury spread", "pp", "raw"),
    "DGS10":        ("10Y Treasury yield", "%", "raw"),
    "BAMLH0A0HYM2": ("High-yield OAS", "pp", "raw"),
    "CPIAUCSL":     ("CPI inflation (YoY)", "%", "yoy_pct"),
    "PAYEMS":       ("Nonfarm payrolls (monthly change)", "k", "mom_diff"),
    "UNRATE":       ("Unemployment rate", "%", "raw"),
}


# Treasury constant-maturity curve: sid → (short label, maturity in years).
# Ordered short→long; the dashboard and finvisible both rely on that order.
CURVE = {
    "DGS1MO": ("1M",  1 / 12),
    "DGS3MO": ("3M",  0.25),
    "DGS6MO": ("6M",  0.5),
    "DGS1":   ("1Y",  1.0),
    "DGS2":   ("2Y",  2.0),
    "DGS3":   ("3Y",  3.0),
    "DGS5":   ("5Y",  5.0),
    "DGS7":   ("7Y",  7.0),
    "DGS10":  ("10Y", 10.0),
    "DGS20":  ("20Y", 20.0),
    "DGS30":  ("30Y", 30.0),
}
CURVE_HISTORY_YEARS = 3   # daily history retained per tenor, for regression use


def fetch_series(sid: str) -> pd.Series | None:
    try:
        resp = requests.get(FRED.format(sid=sid), timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        date_col, val_col = df.columns[0], df.columns[1]
        df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
        df[val_col] = pd.to_numeric(df[val_col], errors="coerce")
        s = df.dropna().set_index(date_col)[val_col]
        return s if len(s) else None
    except Exception as exc:
        print(f"[econ] {sid}: fetch failed ({exc})", flush=True)
        return None


def build_curve(fetch) -> dict | None:
    """Cross-section of the Treasury curve today, plus daily history per tenor.

    `fetch` is the shared, memoised fetcher so a tenor that also appears in the
    display SERIES costs one HTTP request, not two. Fail-soft per tenor: a
    missing tenor drops out of the curve rather than failing the build. Returns
    None only if NOTHING could be fetched, so a total FRED outage leaves the
    previous curve in place rather than publishing an empty one.
    """
    hist_start = pd.Timestamp(
        datetime.date.today() - datetime.timedelta(days=365 * CURVE_HISTORY_YEARS)
    )
    points, history, dates_union = [], {}, None
    for sid, (label, years) in CURVE.items():
        s = fetch(sid)
        if s is None or not len(s):
            print(f"[econ] curve {sid}: absent, dropped from curve", flush=True)
            continue
        points.append({
            "sid": sid,
            "label": label,
            "years": round(years, 4),
            "yield": round(float(s.iloc[-1]), 3),
            "date": s.index[-1].date().isoformat(),
        })
        h = s[s.index >= hist_start]
        history[sid] = h
        dates_union = h.index if dates_union is None else dates_union.union(h.index)

    if not points:
        print("[econ] curve: no tenors fetched — curve block omitted", flush=True)
        return None

    # Align every tenor to one date index so a consumer can zip dates against
    # values without re-deriving the alignment. Missing observations stay null
    # rather than being forward-filled: a fabricated yield would silently become
    # a fabricated yield CHANGE, which is what the regression actually consumes.
    # sort_values() is redundant today — DatetimeIndex.union() already returns
    # sorted, and mutation-testing confirmed removing it changes nothing. It
    # stays because ASCENDING IS THE CONTRACT, not an incidental property of how
    # the index happens to be built: consumers zip dates against values
    # positionally and diff them to get yield changes. Kept explicit so a future
    # change to how idx is assembled cannot quietly lose the ordering.
    idx = dates_union.sort_values()
    if not len(idx):
        # Every tenor's data predates the retention window, so there are points
        # but no history to go with them. Publishing that would satisfy the
        # "curve exists" check while failing the alignment contract downstream,
        # and finvisible would show a curve it cannot regress against. Treat it
        # as unbuildable so main() keeps the previous, coherent curve.
        print("[econ] curve: all observations older than the "
              f"{CURVE_HISTORY_YEARS}y window — curve block omitted", flush=True)
        return None

    aligned = {sid: [None if pd.isna(v) else round(float(v), 3)
                     for v in h.reindex(idx).values]
               for sid, h in history.items()}

    latest_date = max(p["date"] for p in points)
    stale = [p["label"] for p in points if p["date"] != latest_date]
    if stale:
        print(f"[econ] curve: tenors not on {latest_date}: {', '.join(stale)}", flush=True)
    return {
        "as_of": latest_date,
        "stale_tenors": stale,
        "points": points,
        "history": {
            "dates": [d.date().isoformat() for d in idx],
            "values": aligned,
        },
    }


def main() -> None:
    # Fetch a padded window (display window + 400d) so the YoY / month-over-month
    # transforms have prior history to compute against; the chart history is
    # trimmed back to the display window (disp_start) below.
    cutoff = pd.Timestamp(datetime.date.today() - datetime.timedelta(days=365 * YEARS + 400))
    disp_start = pd.Timestamp(datetime.date.today() - datetime.timedelta(days=365 * YEARS + 15))

    _cache: dict[str, pd.Series | None] = {}

    def fetch(sid: str):
        if sid not in _cache:
            _cache[sid] = fetch_series(sid)
        return _cache[sid]

    out = {"as_of": str(datetime.date.today()), "series": {}}
    for sid, (label, unit, transform) in SERIES.items():
        s = fetch(sid)
        if s is None:
            continue
        s = s[s.index >= cutoff]
        if transform == "yoy_pct":
            s = (s / s.shift(12) - 1.0) * 100 if s.index.freqstr else (s / s.shift(12) - 1.0) * 100
        elif transform == "mom_diff":
            s = s.diff()
        s = s.dropna()
        # Weekly resolution keeps recent inflections visible on the daily series
        # (curve, credit spread); inherently-monthly series (CPI, payrolls,
        # unemployment) stay at their native monthly cadence. Trim to the max
        # stored window (5y); the dashboard slices 1y/2y/5y over it client-side.
        hist = s.resample("W").last().dropna()
        hist = hist[hist.index >= disp_start]
        recent = s.iloc[-1]
        prev_q = s[s.index <= s.index[-1] - pd.Timedelta(days=90)]
        chg_3m = float(recent - prev_q.iloc[-1]) if len(prev_q) else None
        out["series"][sid] = {
            "label": label,
            "unit": unit,
            "latest": round(float(recent), 3),
            "latest_date": s.index[-1].date().isoformat(),
            "chg_3m": round(chg_3m, 3) if chg_3m is not None else None,
            "history": {
                "dates": [d.date().isoformat() for d in hist.index],
                "values": [round(float(v), 3) for v in hist.values],
            },
        }
        print(f"[econ] {sid}: latest {out['series'][sid]['latest']} "
              f"({out['series'][sid]['latest_date']})", flush=True)

    curve = build_curve(fetch)
    if curve is not None:
        out["curve"] = curve
        pts = curve["points"]
        print(f"[econ] curve: {len(pts)} tenors as of {curve['as_of']} "
              f"({pts[0]['label']} {pts[0]['yield']}% -> "
              f"{pts[-1]['label']} {pts[-1]['yield']}%), "
              f"{len(curve['history']['dates'])} daily observations", flush=True)
    else:
        # Preserve whatever curve is already published rather than dropping it.
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
            if "curve" in prev:
                out["curve"] = prev["curve"]
                print(f"[econ] curve: fetch failed, kept previous "
                      f"(as of {prev['curve'].get('as_of')})", flush=True)
        except Exception:
            pass

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"[econ] wrote {OUT} ({len(out['series'])} series"
          f"{', + curve' if 'curve' in out else ''})", flush=True)


if __name__ == "__main__":
    main()
