"""
earnings_scan.py — who in the scan universe reports this week and next, for the
Earnings view of the Filings tab.

Owner, 2026-10-07 (Q35 = b): an earnings calendar across the whole universe,
not only the names clients hold (finvisible's "Coming up" covers those).

Source: Nasdaq's public earnings calendar, one call per weekday,
    https://api.nasdaq.com/api/calendar/earnings?date=YYYY-MM-DD
which gives every US reporter that day with timing (pre/post market), the
consensus EPS forecast, the number of estimates and last year's EPS. Tested
from a GitHub runner on 2026-10-07: a plain client times out at 20 s, a
request with browser headers answers in about 2 s. Hence the headers below.

Window: Monday of this week through Friday of next week (ten calls). Days
already past this week stay in, so the view shows who has reported as well as
who is about to.

Kept: universe names only (scan/universe_ci.csv), with the universe's sector.
Whether a name is on today's signal list is NOT written here: the page works
it out from the same snapshot it already has, as the Filings view does.

A day that fails keeps the previous file's rows for that day; a run where
every day fails keeps the last file and says so. An empty day is a fact
(nobody in the universe reports), a failed day is not, and the file records
which days were read in `days_read`.
"""
import datetime
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).parent.parent
UNIVERSE = Path(__file__).parent / "universe_ci.csv"
OUT = ROOT / "data" / "earnings.json"
URL = "https://api.nasdaq.com/api/calendar/earnings"
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}
TIMING = {"time-pre-market": "pre", "time-after-hours": "post"}


def window(today: datetime.date) -> list[datetime.date]:
    """Weekdays from Monday of this week to Friday of next week."""
    monday = today - datetime.timedelta(days=today.weekday())
    days = (monday + datetime.timedelta(days=i) for i in range(12))
    return [d for d in days if d.weekday() < 5]


def money(s) -> float | None:
    """'$2.29' -> 2.29, '($0.08)' -> -0.08, '$171,498,619,000' -> 1.71e11, 'N/A' -> None."""
    s = str(s or "").strip()
    neg = s.startswith("(") and s.endswith(")")
    num = re.sub(r"[^0-9.]", "", s)
    if not num or num == ".":
        return None
    v = float(num)
    return -v if neg else v


def symbol(s) -> str:
    return str(s or "").strip().upper().replace("/", "-").replace(".", "-")


def fetch_day(d: datetime.date, session=None, tries: int = 3) -> list[dict]:
    """Every reporter Nasdaq lists for one day. Raises when the day can't be read."""
    get = (session or requests).get
    last = None
    for i in range(tries):
        try:
            r = get(URL, params={"date": d.isoformat()}, headers=HEADERS, timeout=25)
            r.raise_for_status()
            data = (r.json() or {}).get("data") or {}
            return data.get("rows") or []
        except Exception as exc:                                    # noqa: BLE001
            last = exc
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{d}: {type(last).__name__}: {last}")


def keep(d: datetime.date, raw: list[dict], meta: dict) -> list[dict]:
    """Universe names only, in the shape the page reads."""
    out = []
    for x in raw:
        tk = symbol(x.get("symbol"))
        if tk not in meta:
            continue
        name, sector = meta[tk]
        if not name or name.lower() == "nan":                       # blank in the universe file
            name = str(x.get("name") or tk)
        n = money(x.get("noOfEsts"))
        out.append({"date": d.isoformat(), "ticker": tk, "name": name, "sector": sector,
                    "time": TIMING.get(x.get("time"), ""),
                    "eps": money(x.get("epsForecast")),
                    "n_est": int(n) if n is not None else None,
                    "eps_ly": money(x.get("lastYearEPS")),
                    "mcap": money(x.get("marketCap")),
                    "quarter": str(x.get("fiscalQuarterEnding") or "")})
    return out


def scan(today: datetime.date | None = None, prev: dict | None = None,
         fetch=fetch_day) -> dict:
    today = today or datetime.date.today()
    uni = pd.read_csv(UNIVERSE)
    meta = {symbol(r.ticker): (str(r.name), str(r.sector)) for r in uni.itertuples()}
    prev_rows = {}
    for r in (prev or {}).get("earnings", []):
        prev_rows.setdefault(r["date"], []).append(r)
    days = window(today)
    rows, read, failed = [], [], []
    session = requests.Session()
    for d in days:
        try:
            raw = fetch(d, session)
        except Exception as exc:                                    # noqa: BLE001
            print(f"[earnings] {exc}; keeping the previous file's rows for that day")
            failed.append(d.isoformat())
            rows += prev_rows.get(d.isoformat(), [])
            continue
        got = keep(d, raw, meta)
        print(f"[earnings] {d}: {len(raw)} reporters, {len(got)} in the universe")
        read.append(d.isoformat())
        rows += got
        time.sleep(0.5)
    rows.sort(key=lambda r: (r["date"], -(r["mcap"] or 0)))
    return {"as_of": today.isoformat(), "start": days[0].isoformat(), "end": days[-1].isoformat(),
            "universe": len(meta), "days_read": read, "days_failed": failed,
            "n": len(rows), "earnings": rows}


def main() -> int:
    prev = None
    if OUT.exists():
        try:
            prev = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:                                           # noqa: BLE001
            prev = None
    blob = scan(prev=prev)
    if not blob["days_read"]:
        print("[earnings] no day could be read; keeping the last file")
        return 0
    OUT.write_text(json.dumps(blob, indent=1), encoding="utf-8")
    print(f"[earnings] wrote {blob['n']} reporters from {blob['start']} to {blob['end']} "
          f"({len(blob['days_read'])} days read, {len(blob['days_failed'])} failed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
