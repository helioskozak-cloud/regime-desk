"""
bubble_scan.py — Bubble Watch data refresh (standalone, read-side).

Computes the CURRENT year's doubled/halved churn row for S&P 500 members and
merges it with the committed static history (scan/bubble_history.json), writing
data/bubble_watch.json for snapshot_builder.

Deliberately independent of ci_scan.py / portfolio_manager.py — it must not
touch the V2 evaluation path (frozen until 2026-08-30). Fail-soft: on any error
it still writes the static history so the dashboard view keeps rendering.

History rows are floors for the dot-com era (37-52% survivor coverage on
Yahoo); AI-era rows are 89-99% complete. See meta.survivorship_note.
"""
import io
import json
import datetime
from pathlib import Path

import pandas as pd
import requests
import yfinance as yf

ROOT = Path(__file__).parent.parent
HISTORY = Path(__file__).parent / "bubble_history.json"
OUT = ROOT / "data" / "bubble_watch.json"

CONSTITUENTS_REPO = "fja05680/sp500"


def _current_members(hist: dict) -> list[str]:
    """Latest point-in-time member list; falls back to the committed one."""
    try:
        api = requests.get(
            f"https://api.github.com/repos/{CONSTITUENTS_REPO}/contents/", timeout=30
        ).json()
        csv_name = next(
            f["name"] for f in api
            if f["name"].endswith(".csv") and "Historical Components" in f["name"]
        )
        raw = requests.get(
            f"https://raw.githubusercontent.com/{CONSTITUENTS_REPO}/master/{csv_name}",
            timeout=60,
        ).text
        cons = pd.read_csv(io.StringIO(raw))
        cons.columns = [c.strip().lower() for c in cons.columns]
        cons["date"] = pd.to_datetime(cons["date"])
        row = cons.sort_values("date").iloc[-1]
        members = sorted(
            t.strip().replace(".", "-") for t in row["tickers"].split(",") if t.strip()
        )
        if len(members) > 400:
            print(f"[bubble] member list refreshed from {csv_name} ({row['date'].date()})")
            return members
    except Exception as exc:
        print(f"[bubble] constituent refresh failed ({exc}); using committed list")
    return hist["members_current"]


def _path(px: pd.DataFrame, idx: pd.DataFrame, base: pd.Series, ibase: pd.Series,
          both: list[str], year: int) -> tuple[list, list]:
    """This year's track, for the Bubble tab's S&P chart (owner, 2026-10-06:
    "a chart of the S&P starting from this year with each lit marker marked
    chronologically").

    spx:  [[date, close]] every session.
    path: the marker inputs as of each week's last session (plus the latest),
          on the SAME base and member set as the year row, so the last point
          equals the headline row and the chart cannot disagree with the tiles.
    """
    cur = px.loc[px.index.year == year, both].ffill()
    icur = idx.loc[idx.index.year == year].ffill()
    spx = [[d.strftime("%Y-%m-%d"), round(float(v), 2)]
           for d, v in icur["^GSPC"].dropna().items()]
    weekly = cur.groupby(cur.index.to_period("W")).tail(1).index
    pts = sorted(set(weekly) | {cur.index[-1]})
    path = []
    for d in pts:
        r = (cur.loc[d] / base[both] - 1.0).dropna()
        if r.empty:
            continue
        sp = icur["^GSPC"].loc[:d].dropna()
        path.append({
            "date": d.strftime("%Y-%m-%d"),
            "pct_doubled": round(100 * float((r >= 1.0).mean()), 2),
            "pct_halved": round(100 * float((r <= -0.5).mean()), 2),
            "median_ret": round(100 * float(r.median()), 2),
            "sp500_ret": round(float(sp.iloc[-1] / ibase["^GSPC"] - 1.0) * 100, 2),
        })
    return spx, path


def _year_row(members: list[str], year: int) -> dict:
    """Compute the doubled/halved row for `year` from prior-year-end to latest close.

    DAILY closes since 2026-10-06 (was monthly): the year path needs them, and
    the prior year's last daily close is the same base the monthly bar closed on.
    """
    start = f"{year - 1}-12-01"
    px = yf.download(members, start=start, interval="1d",
                     auto_adjust=True, threads=True, progress=False)["Close"]
    px = px.dropna(axis=1, how="all")
    idx = yf.download(["^GSPC", "^IXIC"], start=start, interval="1d",
                      auto_adjust=True, progress=False)["Close"]

    base = px.loc[px.index.year == year - 1].ffill().iloc[-1]   # last close of prior year
    last = px.ffill().iloc[-1]
    both = [t for t in members if t in px.columns
            and pd.notna(base.get(t)) and pd.notna(last.get(t)) and base.get(t) > 0]
    r = pd.Series({t: last[t] / base[t] - 1.0 for t in both})

    ibase = idx.loc[idx.index.year == year - 1].ffill().iloc[-1]
    ilast = idx.ffill().iloc[-1]
    try:
        spx, path = _path(px, idx, base, ibase, both, year)
    except Exception as exc:       # the path is extra; never lose the year row over it
        print(f"[bubble] year path failed ({exc}); shipping the row without it")
        spx, path = [], []
    return {
        "spx": spx,
        "path": path,
        "year": year,
        "partial": True,
        "n_members": len(members),
        "n_with_data": len(both),
        "coverage_pct": round(100 * len(both) / len(members), 1),
        "pct_doubled": round(100 * float((r >= 1.0).mean()), 2),
        "pct_halved": round(100 * float((r <= -0.5).mean()), 2),
        "n_doubled": int((r >= 1.0).sum()),
        "n_halved": int((r <= -0.5).sum()),
        "pct_up50": round(100 * float((r >= 0.5).mean()), 2),
        "pct_down30": round(100 * float((r <= -0.3).mean()), 2),
        "median_ret": round(100 * float(r.median()), 2),
        "sp500_ret": round(float(ilast["^GSPC"] / ibase["^GSPC"] - 1.0) * 100, 2),
        "nasdaq_ret": round(float(ilast["^IXIC"] / ibase["^IXIC"] - 1.0) * 100, 2),
        "top5": {k: round(float(v), 3) for k, v in r.nlargest(5).items()},
        "bottom5": {k: round(float(v), 3) for k, v in r.nsmallest(5).items()},
    }


def main() -> None:
    with open(HISTORY, encoding="utf-8") as f:
        hist = json.load(f)

    out = {
        "as_of": str(datetime.date.today()),
        "meta": hist["meta"],
        "years": list(hist["years"]),
    }
    try:
        year = datetime.date.today().year
        members = _current_members(hist)
        row = _year_row(members, year)
        out["years"] = [y for y in out["years"] if y["year"] != year] + [row]
        print(f"[bubble] {year} YTD: {row['n_doubled']} doubled ({row['pct_doubled']}%), "
              f"{row['n_halved']} halved ({row['pct_halved']}%), coverage {row['coverage_pct']}%")
    except Exception as exc:
        print(f"[bubble] current-year computation failed ({exc}); shipping static history only")

    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=1)
    print(f"[bubble] wrote {OUT} ({len(out['years'])} year rows)")


if __name__ == "__main__":
    main()
