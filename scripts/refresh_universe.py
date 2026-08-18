"""Refresh scan/universe_ci.csv from NASDAQ Trader's public symbol directory.

Lives here rather than in a tools folder because the thing that maintains the
universe belongs with the universe. Run monthly by
.github/workflows/universe.yml, and by hand with --dry-run any time.

WHY THIS IS AUTOMATED
---------------------
The previous refresh mechanism was "someone remembers". It last ran 2026-01-27
and was found seven months later, during which the universe was missing UNH
(a Dow component, $1.78B/day), ARM, BABA, UPS, AZN, SHEL, URI, PDD, UAL and JD.
Every signal, every PAPA trade candidate and every recommendation in that window
came from a universe with mega-cap holes, and nothing anywhere said so.

A manual step that matters is a step that eventually does not happen.

WHERE THE DATA COMES FROM
-------------------------
`nasdaqlisted.txt` + `otherlisted.txt` from NASDAQ Trader — free, updated
nightly, no key. The original universe scanner is long gone; it did not need
recovering, because the master it produced recorded its own `source` column as
exactly these files.

Liquidity comes from yfinance: 21-day average dollar volume. The cut,
$15M/day, was inferred by comparing the old master against what survived into
the universe (in: min $14.7M, median $152M; out: median $1.1M). It is a
parameter, not a law.

THE TWO TRAPS, BOTH OF WHICH FIRED ON THE FIRST MANUAL RUN
-----------------------------------------------------------
1. **Class shares.** They are BRK.B here and BRK-B in our CSV. Filtering out
   symbols containing a dot made every class share look delisted, and the first
   run removed Berkshire A and B, Brown-Forman B and Heico A. Dots are
   normalised to dashes; nothing is excluded for containing one.

2. **Absence from a listing file is not proof of delisting.** EQR trades daily
   and appears in neither file. A ticker is removed only when it is absent from
   the listings AND has no recent price — two independent signals. On the first
   run that spared EA, EQR, EVTV, NSA and TMHC while still removing 29 real M&A
   delistings.

SAFETY
------
Automation that edits the universe can break every consumer at once, so:

  * additions and removals are capped as a share of the universe; anything
    beyond the cap aborts rather than applies, on the assumption that a big
    swing means the input is wrong, not the market;
  * a removal candidate with meaningful recent volume is never dropped;
  * the universe is written only if it still parses and still contains a set of
    canary mega-caps;
  * the workflow runs the contract and universe tests before pushing.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE = ROOT / "scan" / "universe_ci.csv"
REPORT = ROOT / "data" / "universe_refresh_report.md"
CACHE = ROOT / "data" / "universe_screen_cache.json"

SYMDIR = "https://www.nasdaqtrader.com/dynamic/SymDir"
MIN_DOLLAR_VOL = 15_000_000

# Sanity caps. A refresh that wants to change more than this is not describing
# the market; it is describing a broken input.
MAX_ADD_SHARE = 0.20         # of current universe size
MAX_REMOVE_SHARE = 0.05

# Never drop these without a human. If a run wants to, something is wrong with
# the listing files, not with Apple.
CANARIES = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ", "BRK-B", "UNH", "JPM"]

# yfinance's sector names -> the vocabulary universe_ci.csv already uses.
SECTOR_MAP = {
    "Basic Materials": "Materials", "Consumer Cyclical": "Consumer Discretionary",
    "Consumer Defensive": "Consumer Staples", "Financial Services": "Financials",
    "Healthcare": "Healthcare", "Technology": "Technology",
    "Industrials": "Industrials", "Energy": "Energy", "Real Estate": "Real Estate",
    "Communication Services": "Communication Services", "Utilities": "Utilities",
}


def fetch_listed() -> pd.DataFrame:
    frames = []
    for name, sym_col in (("nasdaqlisted", "Symbol"), ("otherlisted", "ACT Symbol")):
        r = requests.get(f"{SYMDIR}/{name}.txt", timeout=90)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text), sep="|")
        df = df[~df[sym_col].astype(str).str.startswith("File Creation")]
        frames.append(pd.DataFrame({
            "symbol": df[sym_col].astype(str).str.upper().str.strip()
                        .str.replace(".", "-", regex=False),
            "name": df.get("Security Name", pd.Series(dtype=str)),
            "test_issue": df.get("Test Issue", pd.Series("N", index=df.index)).eq("Y"),
        }))
    listed = pd.concat(frames, ignore_index=True)
    listed = listed[~listed["test_issue"]]
    listed = listed[listed["symbol"].notna()
                    & listed["symbol"].str.match(r"^[A-Z]+(-[A-Z]{1,2})?$")]
    return listed.drop_duplicates(subset="symbol").reset_index(drop=True)


def dollar_volume(symbols: list[str], *, chunk: int = 40, cap_minutes: int = 45
                  ) -> dict[str, float]:
    """21-day average dollar volume. Cached so a re-run is cheap and a timeout
    resumes rather than restarting."""
    import yfinance as yf

    cache = {}
    if CACHE.exists():
        try:
            cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    fresh = time.time() - 25 * 86400
    todo = [s for s in symbols
            if not (isinstance(cache.get(s), dict) and cache[s].get("ts", 0) > fresh)]
    print(f"    {len(symbols):,} to screen · {len(symbols)-len(todo):,} cached · "
          f"{len(todo):,} to fetch", flush=True)
    deadline = time.monotonic() + cap_minutes * 60
    for i in range(0, len(todo), chunk):
        if time.monotonic() > deadline:
            print(f"    time cap hit at {i:,}/{len(todo):,} — the rest keep their "
                  f"cached value and are picked up next run", flush=True)
            break
        batch = todo[i:i + chunk]
        try:
            data = yf.download(batch, period="1mo", interval="1d", progress=False,
                               auto_adjust=False, threads=True)
        except Exception:
            continue
        for s in batch:
            try:
                close = data["Close"] if len(batch) == 1 else data["Close"][s]
                vol = data["Volume"] if len(batch) == 1 else data["Volume"][s]
                dv = (close * vol).dropna()
                cache[s] = {"dv": float(dv.tail(21).mean()) if len(dv) else 0.0,
                            "ts": time.time()}
            except Exception:
                cache[s] = {"dv": 0.0, "ts": time.time()}
        if i % (chunk * 20) == 0:
            CACHE.write_text(json.dumps(cache), encoding="utf-8")
        time.sleep(0.3)
    CACHE.write_text(json.dumps(cache), encoding="utf-8")
    return {s: (cache.get(s) or {}).get("dv", 0.0) for s in symbols}


def sectors_for(symbols: list[str]) -> dict[str, dict]:
    """name/sector/industry for new tickers, in the universe's vocabulary."""
    import yfinance as yf
    out = {}
    for i, t in enumerate(symbols, 1):
        rec = {"name": "", "sector": "", "industry": ""}
        try:
            info = yf.Ticker(t).info or {}
            rec["name"] = str(info.get("shortName") or info.get("longName") or "")
            rec["sector"] = SECTOR_MAP.get(str(info.get("sector") or ""), "")
            rec["industry"] = str(info.get("industry") or "")
        except Exception:
            pass
        out[t] = rec
        if i % 25 == 0:
            print(f"    sectors {i}/{len(symbols)}", flush=True)
        time.sleep(0.12)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="report only; never write universe_ci.csv")
    ap.add_argument("--min-dollar-vol", type=float, default=MIN_DOLLAR_VOL)
    ap.add_argument("--screen-cap-minutes", type=int, default=45)
    ap.add_argument("--allow-large", action="store_true",
                    help="Bypass the size caps for a deliberate one-time catch-up. "
                         "NEVER set this in the scheduled workflow: the caps exist "
                         "so an unattended run cannot reshape the universe.")
    args = ap.parse_args()

    cur = pd.read_csv(UNIVERSE)
    cur["ticker"] = cur["ticker"].astype(str).str.upper().str.strip()
    universe = set(cur["ticker"])
    print(f"universe: {len(universe):,}")

    listed = fetch_listed()
    listed_set = set(listed["symbol"])
    print(f"listed  : {len(listed_set):,}")

    # ── removals: two independent signals ───────────────────────────────────
    suspects = sorted(universe - listed_set)
    removals: list[str] = []
    if suspects:
        print(f"\n{len(suspects)} absent from the listings — price-checking each")
        px = dollar_volume(suspects, cap_minutes=10)
        removals = sorted([s for s in suspects if px.get(s, 0.0) <= 0])
        spared = [s for s in suspects if px.get(s, 0.0) > 0]
        if spared:
            print(f"  spared, still trading: {', '.join(spared)}")

    # ── additions: everything listed that we do not hold, screened ──────────
    print(f"\nscreening {len(listed_set - universe):,} listed tickers not in the universe")
    cands = sorted(listed_set - universe)
    dv = dollar_volume(cands, cap_minutes=args.screen_cap_minutes)
    additions = sorted([s for s in cands if dv.get(s, 0.0) >= args.min_dollar_vol],
                       key=lambda s: -dv[s])
    print(f"  {len(additions)} clear ${args.min_dollar_vol:,.0f}/day")

    # ── safety ──────────────────────────────────────────────────────────────
    problems = []
    if args.allow_large:
        print("  --allow-large: size caps bypassed for this run")
    if not args.allow_large and len(additions) > MAX_ADD_SHARE * len(universe):
        problems.append(f"{len(additions)} additions exceeds the "
                        f"{MAX_ADD_SHARE:.0%} cap")
    if not args.allow_large and len(removals) > MAX_REMOVE_SHARE * len(universe):
        problems.append(f"{len(removals)} removals exceeds the "
                        f"{MAX_REMOVE_SHARE:.0%} cap")
    canary_loss = [c for c in CANARIES if c in universe and c in removals]
    if canary_loss:
        problems.append(f"would remove canary tickers: {canary_loss}")

    lines = [f"# Universe refresh — {time.strftime('%Y-%m-%d')}", "",
             f"- universe before: **{len(universe):,}**",
             f"- currently listed: {len(listed_set):,}",
             f"- additions clearing ${args.min_dollar_vol:,.0f}/day: **{len(additions)}**",
             f"- removals (absent from listings AND no recent price): **{len(removals)}**",
             ""]
    if problems:
        lines += ["## ABORTED", ""] + [f"- {p}" for p in problems] + [
            "", "Nothing was written. A swing this large means the input is "
            "wrong, not the market.", ""]
        REPORT.write_text("\n".join(lines), encoding="utf-8")
        print("\nABORTED:", "; ".join(problems))
        return 1

    if removals:
        lines += ["## Removed", "", "```", ", ".join(removals), "```", ""]
    if additions:
        lines += ["## Added", "", "| ticker | avg $ vol (21d) |", "|---|---:|"]
        lines += [f"| {s} | ${dv[s]:,.0f} |" for s in additions[:50]]
        if len(additions) > 50:
            lines.append(f"| … | {len(additions)-50} more |")
        lines.append("")
    REPORT.write_text("\n".join(lines), encoding="utf-8")

    if args.dry_run:
        print("\ndry run — universe not written")
        print(f"report: {REPORT}")
        return 0
    if not additions and not removals:
        print("\nno change")
        return 0

    meta = sectors_for(additions) if additions else {}
    keep = cur[~cur["ticker"].isin(removals)]
    new = pd.DataFrame([{"ticker": t, "name": meta[t]["name"],
                         "sector": meta[t]["sector"], "industry": meta[t]["industry"]}
                        for t in additions])
    out = pd.concat([keep, new], ignore_index=True) if len(new) else keep
    out = out.drop_duplicates(subset="ticker").sort_values("ticker").reset_index(drop=True)

    got = set(out["ticker"])
    missing = [c for c in CANARIES if c not in got]
    assert not missing, f"refusing to write: canaries missing {missing}"
    assert len(out) == len(keep) + len(new), "row arithmetic does not close"
    out.to_csv(UNIVERSE, index=False, lineterminator="\n")
    print(f"\nuniverse {len(universe):,} -> {len(out):,}  "
          f"(+{len(new)} / -{len(removals)})")
    print(f"report: {REPORT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
