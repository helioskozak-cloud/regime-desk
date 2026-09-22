"""Find spliced price series in the local price database.

A splice is one ticker's series carrying two DIFFERENT securities end to end:
a company reorganises, the old equity is cancelled, the new shares reuse the
symbol, and the download stitches them into one continuous line. CHRD is the
known case — a +25,733% single day — and it already produced a wrong result:
B5's "the picks run beta ~0.7" was that join, not a fact about the strategy
(the real figure is ~1.08). Anything that reads this database inherits the
artefact, which is why `run_validation.py --drop-splices` exists.

That flag only removes what it happens to meet in one run's universe. This
walks the WHOLE database once and reports every ticker with an impossible
day, so the list is known rather than discovered.

Thresholds are `validate.SPLICE_UP` / `SPLICE_DOWN`, the same ones the
validation harness drops on, plus a softer REVIEW band that is suspicious
rather than impossible — a real security CAN halve, so the softer list is for
reading, not for automatic exclusion.

    python scan/splice_scan.py [--db DATA/market_data.db] [--out FILE.csv]

Live CI is unaffected: it scans fresh downloads, not this file.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scan"))

try:
    import validate as v                      # thresholds live there
    SPLICE_UP, SPLICE_DOWN = v.SPLICE_UP, v.SPLICE_DOWN
except Exception:                             # stand-alone use
    SPLICE_UP, SPLICE_DOWN = 10.0, -0.95

REVIEW_UP, REVIEW_DOWN = 2.0, -0.80           # +200% / -80% in a day: read these

SQL = """
WITH stepped AS (
    SELECT ticker, date, close,
           LAG(close) OVER (PARTITION BY ticker ORDER BY date) AS prev
    FROM prices
    WHERE close IS NOT NULL AND close > 0
),
moves AS (
    SELECT ticker, date, prev, close, (close / prev) - 1.0 AS ret
    FROM stepped WHERE prev IS NOT NULL AND prev > 0
)
SELECT ticker, date, prev, close, ret FROM moves
WHERE ret >= ? OR ret <= ?
ORDER BY ticker, date
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=str(ROOT / "data" / "market_data.db"))
    ap.add_argument("--out", default=str(ROOT / "data" / "splice_scan.csv"))
    args = ap.parse_args(argv)

    con = sqlite3.connect(args.db)
    n_tick = con.execute("SELECT COUNT(DISTINCT ticker) FROM prices").fetchone()[0]
    n_rows = con.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    print(f"{args.db}: {n_rows:,} rows, {n_tick:,} tickers", flush=True)
    print(f"impossible: >= {SPLICE_UP:+.0%} or <= {SPLICE_DOWN:+.0%} in one day; "
          f"review: >= {REVIEW_UP:+.0%} or <= {REVIEW_DOWN:+.0%}", flush=True)

    rows = list(con.execute(SQL, (REVIEW_UP, REVIEW_DOWN)))
    con.close()

    hard, soft = [], []
    for ticker, date, prev, close, ret in rows:
        (hard if (ret >= SPLICE_UP or ret <= SPLICE_DOWN) else soft).append(
            (ticker, str(date)[:10], float(prev), float(close), float(ret)))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as fh:
        fh.write("ticker,date,prev_close,close,pct_move,severity\n")
        for t, d, p, c, r in hard + soft:
            sev = "impossible" if (r >= SPLICE_UP or r <= SPLICE_DOWN) else "review"
            fh.write(f"{t},{d},{p:.6f},{c:.6f},{r * 100:.2f},{sev}\n")

    def summarise(label, items):
        names = sorted({t for t, *_ in items})
        print(f"\n{label}: {len(items)} day(s) across {len(names)} ticker(s)")
        for t in names:
            worst = max((x for x in items if x[0] == t), key=lambda x: abs(x[4]))
            print(f"  {t:<8} {worst[1]}  {worst[2]:>12,.2f} -> {worst[3]:<12,.2f} "
                  f"{worst[4] * 100:>12,.1f}%")
        return names

    hard_names = summarise("IMPOSSIBLE (drop these)", hard)
    summarise("REVIEW (suspicious, judge each)", soft)
    print(f"\nwrote {out}")
    print("drop list: " + (",".join(hard_names) or "none"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
