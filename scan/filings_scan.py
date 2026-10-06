"""
filings_scan.py — SEC filings across the scan universe, for the Filings tab.

Owner, 2026-10-06 (Q31 = a): market-wide EDGAR belongs on the desk; finvisible
keeps only its per-holding "Filed (30d)" column. So this reads the WHOLE
market's filings for the last week in one index call, keeps the forms that
can change a thesis, and keeps only names in scan/universe_ci.csv.

Forms kept (same choices as finvisible/filings.py, which is private, so the
labels below are a copy; change both together):
  8-K / 8-K/A   with item codes, labelled and ranked; 9.01 (exhibits) dropped
  NT 10-K/10-Q  late filing
  13D (+/A)     activist stake; 13G is passive and left out
  S-1/S-3/424B5 registered offering, possible dilution
Periodic 10-K/10-Q are left out: across 1,700 names they are a calendar, not
news. Form 4 insider trades are left out for now: parsing every one in the
universe is hundreds of documents a day.

Identity: SEC fair-access needs a name + email on every request. It comes from
the EDGAR_IDENTITY env var (a repo secret in CI) and is never written here —
this repo is public. No identity = the scan skips and says so; the tab then
shows its last good file with its date, never an empty "nothing filed".
"""
import datetime
import json
import os
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).parent.parent
UNIVERSE = Path(__file__).parent / "universe_ci.csv"
OUT = ROOT / "data" / "filings.json"
WINDOW_DAYS = 7

ITEM_LABEL = {
    "1.01": "material agreement", "1.02": "agreement ended", "1.03": "bankruptcy",
    "1.05": "cyber incident",
    "2.01": "acquisition/disposal", "2.02": "results", "2.03": "new debt",
    "2.04": "debt trigger", "2.05": "exit costs", "2.06": "impairment",
    "3.01": "delisting notice", "3.02": "unregistered sale", "3.03": "holder rights changed",
    "4.01": "auditor change", "4.02": "NON-RELIANCE",
    "5.01": "change in control", "5.02": "officer/director change", "5.03": "charter/bylaws",
    "5.07": "shareholder vote", "7.01": "Reg FD", "8.01": "other event",
}
# 0 = read first (could break the thesis) ... 6 = routine.
ITEM_RANK = {"4.02": 0, "1.03": 0, "3.01": 1, "4.01": 1, "2.06": 1, "1.05": 1,
             "5.01": 2, "2.01": 2, "2.04": 2, "5.02": 3, "2.05": 3, "2.03": 3,
             "3.02": 3, "1.01": 4, "1.02": 4, "2.02": 5}
LATE = {"NT 10-K", "NT 10-Q", "NT 20-F"}
ACTIVIST = {"SC 13D", "SC 13D/A", "SCHEDULE 13D", "SCHEDULE 13D/A"}
OFFERING = {"S-1", "S-3", "S-3ASR", "424B5"}
EIGHT_K = {"8-K", "8-K/A"}
FORMS = sorted(LATE | ACTIVIST | OFFERING | EIGHT_K)


def _url(cik: int, acc: str) -> str:
    return (f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
            f"{acc.replace('-', '')}/{acc}-index.htm")


def describe(form: str, items: list[str]) -> tuple[int, str, str]:
    """(rank, kind, text) for one filing."""
    if form in LATE:
        return 0, "late", f"Late {form[3:]} filing"
    if form in ACTIVIST:
        return 2, "activist", "13D activist stake" + (" (amended)" if form.endswith("/A") else "")
    if form in OFFERING:
        return 3, "offering", f"Registered offering ({form})"
    its = sorted((i for i in items if i != "9.01"), key=lambda i: ITEM_RANK.get(i, 6))
    if not its:
        return 6, "8-K", form
    return (ITEM_RANK.get(its[0], 6), "8-K",
            "; ".join(f"{i} {ITEM_LABEL.get(i, '')}".strip() for i in its))


def _tickers(identity: str) -> dict[int, list[str]]:
    """CIK -> tickers, from SEC's own map."""
    r = requests.get("https://www.sec.gov/files/company_tickers.json",
                     headers={"User-Agent": identity}, timeout=60)
    r.raise_for_status()
    out: dict[int, list[str]] = {}
    for v in r.json().values():
        out.setdefault(int(v["cik_str"]), []).append(str(v["ticker"]).upper().replace(".", "-"))
    return out


def _items(cik: int, since: str, identity: str) -> dict[str, list[str]]:
    """accession -> 8-K item codes, from the company's submissions file."""
    r = requests.get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json",
                     headers={"User-Agent": identity}, timeout=60)
    r.raise_for_status()
    rec = r.json().get("filings", {}).get("recent", {})
    out = {}
    for acc, d, it in zip(rec.get("accessionNumber", []), rec.get("filingDate", []),
                          rec.get("items", [])):
        if d < since:
            break
        out[acc] = [i.strip() for i in str(it or "").split(",") if i.strip()]
    return out


def scan(identity: str, today: datetime.date | None = None) -> dict:
    from edgar import set_identity, get_filings
    set_identity(identity)
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    uni = pd.read_csv(UNIVERSE)
    meta = {str(r.ticker).upper(): (str(r.name), str(r.sector)) for r in uni.itertuples()}

    idx = get_filings(form=FORMS, filing_date=f"{since}:{today.isoformat()}").to_pandas()
    cik2tk = _tickers(identity)
    rows = []
    for r in idx.itertuples():
        tks = [t for t in cik2tk.get(int(r.cik), []) if t in meta]
        if not tks:
            continue
        rows.append({"ticker": tks[0], "cik": int(r.cik), "form": str(r.form),
                     "date": str(r.filing_date)[:10], "acc": str(r.accession_number)})
    # Item codes only for the 8-Ks we kept: one submissions call per company.
    need = sorted({x["cik"] for x in rows if x["form"] in EIGHT_K})
    items: dict[str, list[str]] = {}
    for cik in need:
        try:
            items.update(_items(cik, since, identity))
        except Exception as exc:                       # noqa: BLE001
            print(f"[filings] items for CIK {cik} failed ({type(exc).__name__})")
        time.sleep(0.12)                                # well under SEC's 10/s
    out = []
    for x in rows:
        rank, kind, text = describe(x["form"], items.get(x["acc"], []))
        name, sector = meta[x["ticker"]]
        out.append({"ticker": x["ticker"], "name": name, "sector": sector,
                    "date": x["date"], "form": x["form"], "kind": kind,
                    "rank": rank, "what": text, "url": _url(x["cik"], x["acc"])})
    out.sort(key=lambda e: e["date"], reverse=True)   # newest first...
    out.sort(key=lambda e: e["rank"])                  # ...within each rank (stable)
    return {"as_of": today.isoformat(), "window_days": WINDOW_DAYS,
            "universe": len(meta), "n": len(out), "filings": out}


def main() -> int:
    identity = os.environ.get("EDGAR_IDENTITY", "").strip()
    if not identity:
        print("[filings] SKIPPED: EDGAR_IDENTITY is not set; keeping the last file")
        return 0
    try:
        blob = scan(identity)
    except Exception as exc:                           # noqa: BLE001
        print(f"[filings] FAILED ({type(exc).__name__}: {exc}); keeping the last file")
        return 0
    if blob["n"] == 0:
        # A week with no 8-K anywhere in 1,700 names is a failed pull, not news.
        print("[filings] 0 filings matched the universe; keeping the last file")
        return 0
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(blob, indent=1), encoding="utf-8")
    print(f"[filings] wrote {blob['n']} filings for {blob['universe']} names "
          f"({blob['window_days']}d) to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
