"""
repair_db.py — build data/market_data_clean.db: a deduplicated, repaired COPY
of data/market_data.db. The original is never written.

Owner, 2026-09-23, on SPLICE_REVIEW_2026-09-23.md: repair the broken series in
a copy (option b) rather than keep a curated exclusion list, and dedupe.

TWO FIXES.

1. Duplicate dates. 2.9M rows (19%) exist twice, as 'YYYY-MM-DD' and
   'YYYY-MM-DD 00:00:00', same values. validate.load_closes() truncates and
   pivots with aggfunc="last" so it never noticed; anything counting rows as
   days would. The long form is dropped where a twin exists, else shortened.

2. The 16 real problems from the review (SMST, unclear, is left alone). Each
   repair is declared below with its evidence, and is one of three kinds:
     drop    rows that are not trades of this security: pre-listing
             placeholders, one-to-four-day bad prints, a mis-applied split
             that reverses itself, pre-bankruptcy equity joined to the new one.
     scale   an unadjusted or mis-adjusted split: OHLC before `date` are
             multiplied by `factor` and volume divided by it. A clean factor
             (10, 5) is used when the jump matches one within ~3%.
     scale (observed)  when no clean factor fits (RETO 2025 7.21x, SXTC
             16.81x), the observed close ratio is used: the jump day's return
             becomes 0, which is honest about not knowing the factor and costs
             exactly one day's real move.

Every repair is recorded in a `repairs` table inside the clean database, so
the copy carries its own provenance. Re-running rebuilds the copy from the
original: the script is the record, the output is disposable.

Using it: run_validation.py --db clean. The pre-registered tests' default is
unchanged; choosing the clean copy is an explicit, visible flag.

Run:  python scan/repair_db.py
"""
import shutil
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "market_data.db"
DST = ROOT / "data" / "market_data_clean.db"

# (ticker, kind, date, arg, evidence)
#   drop_before  date: delete rows strictly before `date`
#   drop_days    date..arg inclusive
#   scale        multiply OHLC strictly before `date` by arg; volume / arg
REPAIRS = [
    # pre-listing placeholders
    ("DFTX", "drop_before", "2020-03-03", None, "flat 0.75 at zero volume until trading starts 03-03"),
    ("ENLT", "drop_before", "2023-02-10", None, "flat 2.60 at zero volume; US listing 02-10 on 4.6M shares"),
    ("PECO", "drop_before", "2021-07-15", None, "zero-volume 6.14/18.43/6.19 before the 07-15 IPO"),
    ("SEZL", "drop_before", "2023-09-14", None, "first row 13.51 at zero volume; trades 2.2-2.9 from 09-14"),
    ("IVT",  "drop_before", "2021-10-12", None, "thin/zero-volume history incl. a 10x mis-adjusted Aug-Sep window, before the NYSE listing 10-12 (971k shares)"),
    ("CHRD", "drop_before", "2020-11-20", None, "pre-reorganisation Oasis equity (~$0.07) joined to the new equity (~$19)"),
    # bad prints and self-reversing mis-adjustments
    ("HELP", "drop_before", "2020-11-11", None, "placeholder quotes at ~zero volume with three false jumps: 49.99->13.01 on 2 shares (03-10), a single 7.14 print (05-22), a 1:6.7 one-day mis-adjustment (11-10)"),
    ("INDV", "drop_days", "2022-11-23", "2022-11-25", "3.13 for two days at zero volume between 19.64 and 21.03"),
    ("DFSC", "drop_days", "2022-10-28", "2022-10-31", "1:70 mis-adjustment for two days (17.01), zero volume"),
    ("DFSC", "drop_days", "2025-04-23", "2025-04-23", "1:21 mis-adjustment for one day (0.217), zero volume"),
    ("NCPL", "drop_days", "2020-11-05", "2020-11-10", "1:2000 mis-adjustment for four days (0.21), zero volume"),
    # splits: clean factor
    ("RETO", "scale", "2023-05-12", 0.1,  "1:10 applied the wrong way: 1,190 at ~zero volume -> 119 trading"),
    ("OMH",  "scale", "2025-03-10", 10.0, "unrecorded reverse split: 0.255 -> 2.495 (x9.8) on lower volume, holds"),
    ("SMX",  "scale", "2025-11-18", 5.0,  "unrecorded reverse split: 5.15 -> 25.88 (x5.03) on lower volume, holds"),
    ("MUD",  "scale", "2026-03-05", 0.1,  "forward split never back-adjusted: 375 -> 38.65 on 10x volume, holds"),
    ("TSLS", "scale", "2026-03-05", 0.1,  "forward split never back-adjusted: 555 -> 55.6, holds (Yahoo has since fixed it)"),
    # splits: no clean factor -> observed ratio, neutralising the jump day
    ("RETO", "scale", "2025-03-07", "observed", "unrecorded reverse split: 3.75 -> 27.05 (x7.21, no clean factor)"),
    ("SXTC", "scale", "2022-05-19", "observed", "unrecorded reverse split: 423.8 -> 7,125 (x16.81, no clean factor), volume fell"),
]


# Days over 3x that STAY, each read by hand. The review (or, for the last three,
# this build) found them volume-backed and holding: real events, and removing
# them would bias any backtest against the tails. verify() refuses any other.
GENUINE = {
    ("OMH", "2023-05-08"): "review: genuine event (faded)",
    ("OMH", "2023-05-16"): "30.88 -> 6.35 on 12.5M shares: the dump after 05-08",
    ("OMH", "2025-06-09"): "review: genuine event (faded)",
    ("RETO", "2023-08-24"): "review: genuine event",
    ("SMX", "2025-11-28"): "review: genuine event (faded)",
    ("SMX", "2025-12-31"): "252 -> 80 on 762k shares inside a steady slide",
    ("SXTC", "2025-02-25"): "review: genuine event",
    ("SXTC", "2026-01-09"): "review: genuine event",
    ("NCPL", "2022-07-13"): "577 -> 183 on 12,777 shares vs tens, and holds",
}


def dedupe(c: sqlite3.Connection) -> tuple[int, int]:
    dropped = c.execute("""
        DELETE FROM prices WHERE length(date) = 19 AND EXISTS (
          SELECT 1 FROM prices p2 WHERE p2.ticker = prices.ticker
            AND p2.date = substr(prices.date, 1, 10))""").rowcount
    shortened = c.execute(
        "UPDATE prices SET date = substr(date, 1, 10) WHERE length(date) = 19").rowcount
    return dropped, shortened


def observed_ratio(c, ticker, date) -> float:
    after = c.execute("SELECT close FROM prices WHERE ticker=? AND date=?", (ticker, date)).fetchone()
    before = c.execute("SELECT close FROM prices WHERE ticker=? AND date<? ORDER BY date DESC LIMIT 1",
                       (ticker, date)).fetchone()
    if not after or not before or not before[0]:
        raise SystemExit(f"ABORT: cannot read the jump for {ticker} {date}")
    return after[0] / before[0]


def apply(c: sqlite3.Connection) -> list[tuple]:
    log = []
    for ticker, kind, date, arg, why in REPAIRS:
        if kind == "drop_before":
            n = c.execute("DELETE FROM prices WHERE ticker=? AND date<?", (ticker, date)).rowcount
            detail = f"dropped {n} rows before {date}"
        elif kind == "drop_days":
            n = c.execute("DELETE FROM prices WHERE ticker=? AND date BETWEEN ? AND ?",
                          (ticker, date, arg)).rowcount
            detail = f"dropped {n} rows {date}..{arg}"
        elif kind == "scale":
            f = observed_ratio(c, ticker, date) if arg == "observed" else float(arg)
            n = c.execute("""UPDATE prices SET open=open*?, high=high*?, low=low*?, close=close*?,
                             volume=volume/? WHERE ticker=? AND date<?""",
                          (f, f, f, f, f, ticker, date)).rowcount
            detail = f"scaled {n} rows before {date} by {f:.4f}" + (" (observed)" if arg == "observed" else "")
        else:
            raise SystemExit(f"unknown repair kind {kind}")
        if n == 0:
            raise SystemExit(f"ABORT: {ticker} {kind} {date} touched no rows — the evidence no longer matches the data")
        log.append((ticker, kind, date, detail, why))
        print(f"  {ticker:5s} {detail}")
    return log


def verify(c: sqlite3.Connection) -> None:
    """Loud, not graceful: a repair that leaves a jump in place is not a repair."""
    dup = c.execute("SELECT count(*) FROM prices WHERE length(date) <> 10").fetchone()[0]
    assert dup == 0, f"{dup} non-canonical dates remain"
    bad = []
    for t in sorted({r[0] for r in REPAIRS}):
        rows = c.execute("SELECT date, close FROM prices WHERE ticker=? ORDER BY date", (t,)).fetchall()
        for (d0, c0), (d1, c1) in zip(rows, rows[1:]):
            if c0 and c1 and (c1 / c0 > 3.0 or c1 / c0 < 1 / 3.0) and (t, d1) not in GENUINE:
                bad.append(f"{t} {d1} x{c1 / c0:.2f}")
    if bad:
        raise SystemExit("ABORT: jumps above 3x remain after repair:\n  " + "\n  ".join(bad))
    print(f"  verified: canonical dates only; no unexplained >3x day left on the {len({r[0] for r in REPAIRS})} repaired tickers")


def main() -> None:
    if not SRC.exists():
        sys.exit(f"no {SRC}")
    print(f"copying {SRC.name} -> {DST.name} (the original is only read)")
    tmp = DST.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    shutil.copyfile(SRC, tmp)
    c = sqlite3.connect(tmp)
    try:
        before = c.execute("SELECT count(*) FROM prices").fetchone()[0]
        d, s = dedupe(c)
        print(f"dedupe: dropped {d:,} duplicate rows, shortened {s:,} long-form dates")
        print("repairs:")
        log = apply(c)
        c.execute("DROP TABLE IF EXISTS repairs")
        c.execute("CREATE TABLE repairs (ticker TEXT, kind TEXT, date TEXT, detail TEXT, evidence TEXT)")
        c.executemany("INSERT INTO repairs VALUES (?,?,?,?,?)", log)
        c.execute("INSERT INTO repairs VALUES ('*', 'dedupe', '', ?, 'YYYY-MM-DD vs YYYY-MM-DD 00:00:00 twins')",
                  (f"dropped {d} duplicates, shortened {s} dates",))
        verify(c)
        c.commit()
        after = c.execute("SELECT count(*) FROM prices").fetchone()[0]
        print(f"rows {before:,} -> {after:,}; compacting...")
        c.execute("VACUUM")
    finally:
        c.close()
    tmp.replace(DST)
    print(f"[OK] wrote {DST.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
