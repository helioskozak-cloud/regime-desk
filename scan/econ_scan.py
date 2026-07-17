"""
econ_scan.py — FRED macro snapshot for the #econ dashboard view (standalone,
read-side; no V2 decision-path involvement).

Pulls a small set of series from FRED's keyless fredgraph.csv endpoint and
writes data/econ.json: per series, ~1y of weekly-downsampled history plus the
latest value and a short-window change. Fail-soft per series — a missing
series shows as absent in the UI, never breaks the build.
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
YEARS = 1   # chart display window (tactical — matches the desk's short horizons)

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


def main() -> None:
    # Fetch a padded window (display window + 400d) so the YoY / month-over-month
    # transforms have prior history to compute against; the chart history is
    # trimmed back to the display window (disp_start) below.
    cutoff = pd.Timestamp(datetime.date.today() - datetime.timedelta(days=365 * YEARS + 400))
    disp_start = pd.Timestamp(datetime.date.today() - datetime.timedelta(days=365 * YEARS + 15))
    out = {"as_of": str(datetime.date.today()), "series": {}}
    for sid, (label, unit, transform) in SERIES.items():
        s = fetch_series(sid)
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
        # unemployment) stay at their native monthly cadence. Trim to the display
        # window so the chart shows the tactical window, not the transform buffer.
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

    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"[econ] wrote {OUT} ({len(out['series'])} series)", flush=True)


if __name__ == "__main__":
    main()
