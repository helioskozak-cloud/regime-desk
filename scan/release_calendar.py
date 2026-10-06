"""
release_calendar.py — the macro releases due in the coming weeks, for Home.

Owner, 2026-10-06 (roadmap item G): "What releases land this week?" Keyless
sources only, like econ_scan.py:
  * BEA's own release-date JSON  — GDP, Personal Income and Outlays (PCE), trade
  * the Federal Reserve's FOMC calendar page — decision days and minutes
  * BLS's iCalendar feed — CPI, PPI, the jobs report, JOLTS. BLS refuses many
    non-browser clients (403), so the same releases are then read from FRED's
    release calendar (keyless; filtered per release, it lists the year's dates).
    Only if both fail does the file say so (`missing`), and the banner names the
    gap rather than looking complete without CPI. (2026-10-06, owner Q34 = a)

Writes data/releases.json. Fail-soft: a source that fails is listed in
`missing`; the others still publish.
"""
import datetime
import json
import re
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).parent.parent
OUT = ROOT / "data" / "releases.json"
UA = {"User-Agent": "Mozilla/5.0 (regime-desk research; +https://github.com/helioskozak-cloud/regime-desk)"}
AHEAD_DAYS = 45

BEA_KEEP = {"Gross Domestic Product": ("GDP", 3),
            "Personal Income and Outlays": ("PCE inflation & spending", 3),
            "U.S. International Trade in Goods and Services": ("Trade balance", 1)}
BLS_KEEP = [("Consumer Price Index", "CPI", 3), ("Employment Situation", "Jobs report", 3),
            ("Producer Price Index", "PPI", 2), ("Job Openings and Labor Turnover", "JOLTS", 2),
            ("Employment Cost Index", "Employment cost index", 2)]
MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July",
                                      "August", "September", "October", "November", "December"], 1)}


def bea(today):
    j = requests.get("https://apps.bea.gov/API/signup/release_dates.json", headers=UA, timeout=40).json()
    out = []
    for name, (label, imp) in BEA_KEEP.items():
        for d in (j.get(name) or {}).get("release_dates", []):
            t = datetime.datetime.fromisoformat(d)
            out.append({"date": t.date().isoformat(), "time": "08:30", "name": label,
                        "agency": "BEA", "importance": imp})
    return out


def fomc(today):
    h = requests.get("https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                     headers=UA, timeout=40).text
    out = []
    for year in (today.year, today.year + 1):
        i = h.find(f"{year} FOMC Meetings")
        if i < 0:
            continue
        seg = h[i:i + 20000]
        j = seg.find("FOMC Meetings", 20)          # stop at the next year's block
        seg = seg[:j] if j > 0 else seg
        months = re.findall(r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>', seg)
        days = re.findall(r'fomc-meeting__date[^>]*>([^<]+)<', seg)
        for m, d in zip(months, days):
            m0 = m.split("/")[-1].strip()            # "Apr/May" -> the decision month
            dd = re.findall(r"\d+", d)
            if m0 not in MONTHS or not dd:
                continue
            day = int(dd[-1])
            out.append({"date": datetime.date(year, MONTHS[m0], day).isoformat(), "time": "14:00",
                        "name": "FOMC decision" + (" + projections" if "*" in d else ""),
                        "agency": "Fed", "importance": 3})
    return out


def bls(today):
    r = requests.get("https://www.bls.gov/schedule/news_release/bls.ics", headers=UA, timeout=40)
    r.raise_for_status()
    out = []
    for ev in r.text.split("BEGIN:VEVENT")[1:]:
        summ = re.search(r"SUMMARY[^:]*:(.+)", ev)
        start = re.search(r"DTSTART[^:]*:(\d{8})(?:T(\d{4}))?", ev)
        if not summ or not start:
            continue
        s = summ.group(1).strip()
        for key, label, imp in BLS_KEEP:
            if s.startswith(key):
                d = datetime.datetime.strptime(start.group(1), "%Y%m%d").date()
                tm = start.group(2)
                out.append({"date": d.isoformat(), "time": f"{tm[:2]}:{tm[2:]}" if tm else "08:30",
                            "name": label, "agency": "BLS", "importance": imp})
                break
    return out


FRED_CAL = "https://fred.stlouisfed.org/releases/calendar"
# No browser User-Agent: FRED stalls on one, and answers a plain client.


def bls_via_fred(today):
    """The BLS releases' dates from FRED's calendar, this year and next."""
    page = requests.get(FRED_CAL, timeout=40).text
    ids = {name.strip(): rid for rid, name in re.findall(r'<option value="(\d+)">([^<]+)</option>', page)}
    out = []
    for key, label, imp in BLS_KEEP:
        rid = ids.get(key) or next((v for k, v in ids.items() if k.startswith(key)), None)
        if not rid:
            continue
        for year in (today.year, today.year + 1):
            t = requests.get(f"{FRED_CAL}?rid={rid}&y={year}", timeout=40).text
            for m, d in set(re.findall(r"(" + "|".join(MONTHS) + r") (\d{1,2}), " + str(year), t)):
                out.append({"date": datetime.date(year, MONTHS[m], int(d)).isoformat(),
                            "time": "10:00" if label == "JOLTS" else "08:30",
                            "name": label, "agency": "BLS", "importance": imp})
    if not out:
        raise RuntimeError("FRED calendar listed none of the BLS releases")
    return out


def main() -> int:
    today = datetime.date.today()
    end = today + datetime.timedelta(days=AHEAD_DAYS)
    rows, missing = [], []
    for name, fns in (("BEA", (bea,)), ("Fed", (fomc,)), ("BLS", (bls, bls_via_fred))):
        for fn in fns:
            try:
                got = fn(today)
                rows += got
                print(f"[releases] {name}: {len(got)} dates ({fn.__name__})")
                break
            except Exception as exc:                    # noqa: BLE001
                print(f"[releases] {name} via {fn.__name__} unavailable "
                      f"({type(exc).__name__}: {str(exc)[:80]})")
        else:
            missing.append(name)
    rows = sorted((r for r in rows if today.isoformat() <= r["date"] <= end.isoformat()),
                  key=lambda r: (r["date"], r["time"]))
    if not rows and OUT.exists():
        print("[releases] nothing came back; keeping the last file")
        return 0
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps({"as_of": today.isoformat(), "ahead_days": AHEAD_DAYS,
                               "missing": missing, "releases": rows}, indent=1), encoding="utf-8")
    print(f"[releases] wrote {len(rows)} releases (missing: {', '.join(missing) or 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
