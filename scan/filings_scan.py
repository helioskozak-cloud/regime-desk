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
news.

FORM 4 (2026-10-06, roadmap item E): OPEN-MARKET buys (code P) and sells (S)
by insiders of universe companies, per ticker over the same window. Grants,
exercises, tax withholding and gifts are compensation mechanics and left out.
About 2,200 Form 4s a week, so each accession is parsed ONCE and carried in the
output file; a daily run only parses what is new. A sale can still be a 10b5-1
plan sale; a buy almost never is, which is why buys are the screen.

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


MAX_FORM4_PARSE = 2500      # per run; anything beyond waits for tomorrow, logged


def role(position) -> str:
    """A Form 4 title collapsed to a word (same rules as finvisible/filings.py)."""
    p = str(position or "").lower()
    words = p.replace(",", " ").split()
    if "chief executive" in p or "ceo" in words:
        return "CEO"
    if "chief financial" in p or "cfo" in words:
        return "CFO"
    if "10%" in p:
        return "10% owner"
    if "director" in p and not any(w in p for w in ("officer", "president", "vp", "chief")):
        return "director"
    return "officer" if p else "insider"


def _form4(cik: int, company: str, date_: str, acc: str) -> dict | None:
    """{owner, role, buy, sell} for one Form 4, or None when the filing is not
    an insider trade IN this company (a filer listed as reporting owner of
    someone else's stock, e.g. a holding company buying another issuer)."""
    from edgar import Filing
    o = Filing(cik=cik, company=company, form="4", filing_date=date_, accession_no=acc).obj()
    try:
        if int(getattr(o.issuer, "cik", 0) or 0) != int(cik):
            return None
    except Exception:                                   # noqa: BLE001
        return None
    s = o.get_ownership_summary()
    buy = sum(float(t.value_numeric or 0) for t in s.transactions if t.code == "P")
    sell = sum(float(t.value_numeric or 0) for t in s.transactions if t.code == "S")
    owner = str(getattr(s, "reporting_owner_name", None) or getattr(s, "insider_name", None) or "")
    return {"owner": owner, "role": role(getattr(s, "position", "")), "buy": round(buy),
            "sell": round(sell)}


def insiders(identity: str, since: str, today: str, meta: dict, cik2tk: dict,
             prev: dict) -> tuple[list[dict], dict]:
    """(per-ticker insider rows, parsed-accession cache for the window)."""
    from edgar import get_filings
    idx = get_filings(form="4", filing_date=f"{since}:{today}").to_pandas()
    cache, todo = {}, []
    for r in idx.itertuples():
        tks = [t for t in cik2tk.get(int(r.cik), []) if t in meta]
        if not tks:
            continue
        acc = str(r.accession_number)
        if acc in prev:
            cache[acc] = prev[acc]
        elif acc not in cache and len(todo) < MAX_FORM4_PARSE:
            todo.append((int(r.cik), str(r.company), str(r.filing_date)[:10], acc, tks[0]))
    parsed = len(todo)

    def one(job):
        cik, company, d, acc, tk = job
        time.sleep(0.3)                  # 3 workers x ~3 requests/s: under SEC's 10/s
        try:
            x = _form4(cik, company, d, acc)
        except Exception as exc:                        # noqa: BLE001
            return acc, ("rate" if "429" in str(exc) else "error")
        return acc, (None if x is None else {**x, "ticker": tk, "date": d})

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=3) as ex:
        for i, (acc, x) in enumerate(ex.map(one, todo), start=1):
            if x == "rate":
                print("[filings] SEC rate limit during Form 4s; unparsed ones wait for tomorrow")
                continue
            if x != "error":
                cache[acc] = x
            if i % 250 == 0:
                print(f"[filings] Form 4: {i} of {parsed} parsed", flush=True)
    if parsed >= MAX_FORM4_PARSE:
        print(f"[filings] parsed the {MAX_FORM4_PARSE}-Form-4 cap; the rest wait for tomorrow")
    agg: dict[str, dict] = {}
    for acc, x in cache.items():
        if not x or not (x["buy"] or x["sell"]):
            continue
        a = agg.setdefault(x["ticker"], {"buy": 0, "sell": 0, "buyers": set(), "roles": set(),
                                         "last_buy": "", "n_sell": 0})
        if x["buy"]:
            a["buy"] += x["buy"]
            a["buyers"].add(x["owner"] or acc)
            a["roles"].add(x["role"])
            a["last_buy"] = max(a["last_buy"], x["date"])
        if x["sell"]:
            a["sell"] += x["sell"]
            a["n_sell"] += 1
    rows = []
    for tk, a in agg.items():
        if not a["buy"]:
            continue
        name, sector = meta[tk]
        rows.append({"ticker": tk, "name": name, "sector": sector, "buy": a["buy"],
                     "buyers": len(a["buyers"]), "roles": sorted(a["roles"]),
                     "last_buy": a["last_buy"], "sell": a["sell"], "n_sell": a["n_sell"]})
    rows.sort(key=lambda r: (-r["buyers"], -r["buy"]))
    print(f"[filings] Form 4: {parsed} parsed this run, {len(cache)} in the window, "
          f"{len(rows)} names with open-market buying")
    return rows, cache


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


def scan(identity: str, today: datetime.date | None = None, prev: dict | None = None) -> dict:
    from edgar import set_identity, get_filings
    set_identity(identity)
    today = today or datetime.date.today()
    since = (today - datetime.timedelta(days=WINDOW_DAYS)).isoformat()
    uni = pd.read_csv(UNIVERSE)
    meta = {str(r.ticker).upper(): (str(r.name), str(r.sector)) for r in uni.itertuples()}

    idx = get_filings(form=FORMS, filing_date=f"{since}:{today.isoformat()}").to_pandas()
    cik2tk = _tickers(identity)
    try:
        ins, f4cache = insiders(identity, since, today.isoformat(), meta, cik2tk,
                                (prev or {}).get("form4_cache", {}))
    except Exception as exc:                            # noqa: BLE001
        # Insider rows are extra; a failure keeps yesterday's rather than losing the 8-Ks.
        print(f"[filings] Form 4 step failed ({type(exc).__name__}); keeping the last insider rows")
        ins, f4cache = (prev or {}).get("insiders", []), (prev or {}).get("form4_cache", {})
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
            "universe": len(meta), "n": len(out), "filings": out,
            "insiders": ins, "form4_cache": f4cache}


def main() -> int:
    identity = os.environ.get("EDGAR_IDENTITY", "").strip()
    if not identity:
        print("[filings] SKIPPED: EDGAR_IDENTITY is not set; keeping the last file")
        return 0
    try:
        prev = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
    except Exception:                                   # noqa: BLE001
        prev = {}
    try:
        blob = scan(identity, prev=prev)
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
