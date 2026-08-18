"""Export the universe's ticker -> sector map as public data/sector_map.json.

finvisible and sim-desk both fetch this file; it is how they speak regime-desk's
own sector vocabulary rather than inventing a coarser one.

It used to be extracted from a `_SECTOR_MAP` literal inside api_server.py. That
literal was a verbatim duplicate of `scan/universe_ci.csv`'s `sector` column —
on 2026-08-18 all 1,351 entries matched and none differed — and being a second
copy, it fell 612 tickers behind the universe without anyone noticing. Every
name added by the universe refresh was unthemed downstream.

So the universe is the source now, here and in api_server.py, and this script
just publishes it. Runs in daily.yml before the scan, so it cannot drift.
"""
import csv
import json
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
UNIVERSE = REPO_ROOT / "scan" / "universe_ci.csv"
OUT_FILE = REPO_ROOT / "data" / "sector_map.json"


def build() -> dict[str, str]:
    """{TICKER: sector} for every universe row that has one.

    Tickers with a blank sector are omitted rather than mapped to "" — a theme
    of empty string is not a theme, and a consumer grouping by it would create a
    bucket that means "we do not know" while looking like a category. Those are
    almost all ETFs, which genuinely have no sector.
    """
    out: dict[str, str] = {}
    with UNIVERSE.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            t = str(row.get("ticker", "")).upper().strip()
            s = str(row.get("sector", "") or "").strip()
            if t and s:
                out[t] = s
    return out


def main() -> None:
    mapping = dict(sorted(build().items()))
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps(mapping, indent=1), encoding="utf-8")
    print(f"Wrote {len(mapping)} tickers to {OUT_FILE}")


if __name__ == "__main__":
    main()
