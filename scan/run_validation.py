"""Run B3 over the local price history and print the verdict table.

    python scan/run_validation.py [--horizon 20] [--dates 24] [--universe 900]

Everything it prints is out of sample: at each as-of date the rule sees only
bars up to that date, and is scored on what happened after.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

import validate as v  # noqa: E402

ROOT = Path(__file__).parent.parent


def universe(limit: int, rev: str | None = None) -> list[str]:
    """The CI universe, which is what the engine actually trades.

    `rev` reads the file as of a git commit instead of the working copy. The
    universe is refreshed weekly, so reproducing an earlier run (B7 reproduces
    B5, cb2d56a) needs the list that run actually used."""
    f = Path(__file__).parent / "universe_ci.csv"
    if rev:
        import io
        import subprocess
        raw = subprocess.run(["git", "show", f"{rev}:scan/universe_ci.csv"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
        df = pd.read_csv(io.StringIO(raw))
    else:
        df = pd.read_csv(f)
    col = "ticker" if "ticker" in df.columns else df.columns[0]
    names = [str(t).strip().upper() for t in df[col].dropna()]
    names = [n for n in names if n and n.isalpha()]
    return names[:limit]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=20)
    ap.add_argument("--dates", type=int, default=24)
    ap.add_argument("--universe", type=int, default=900)
    ap.add_argument("--out", default=str(ROOT / "data" / "validation.json"))
    ap.add_argument("--universe-rev", default=None,
                    help="read universe_ci.csv as of this git commit (reproducing a past run)")
    ap.add_argument("--matched", action="append", default=[],
                    help="B7: also score this rule against a beta-matched control (repeatable)")
    ap.add_argument("--match-method", choices=["decile", "nearest"], default="decile",
                    help="B7 = decile, B7b = nearest")
    ap.add_argument("--drop-splices", action="store_true",
                    help="B7c: remove tickers with an impossible one-day move before the walk")
    args = ap.parse_args()

    tickers = universe(args.universe, args.universe_rev)
    if v.BENCH not in tickers:
        tickers.append(v.BENCH)
    print(f"Loading {len(tickers)} tickers from {v.DB.name} ...", flush=True)
    closes = v.load_closes(tickers)
    closes = closes.dropna(axis=1, thresh=400)
    dropped = []
    if args.drop_splices:
        dropped = [t for t in v.spliced_tickers(closes) if t != v.BENCH]
        closes = closes.drop(columns=dropped)
        print(f"  removed as spliced series: {', '.join(dropped) or 'none'}", flush=True)
    print(f"  {closes.shape[1]} tickers with usable history, "
          f"{closes.index.min().date()} -> {closes.index.max().date()}", flush=True)
    if v.BENCH not in closes.columns:
        print(f"FATAL: no {v.BENCH} in the price database", flush=True)
        return 1

    # As-of dates spread across the usable span. The first 300 bars are needed
    # to build features and the last `horizon` bars to score the outcome.
    idx = closes.index
    first, last = 300, len(idx) - args.horizon - 1
    if last <= first:
        print("FATAL: not enough history for this horizon", flush=True)
        return 1
    step = max(1, (last - first) // args.dates)
    as_of_dates = [idx[i] for i in range(first, last, step)][: args.dates]
    print(f"{len(as_of_dates)} as-of dates, horizon {args.horizon} bars "
          f"({as_of_dates[0].date()} -> {as_of_dates[-1].date()})\n", flush=True)

    results = v.walk_forward(closes, args.horizon, as_of_dates,
                             matched_for=tuple(args.matched),
                             match_method=args.match_method)

    print("\n" + "=" * 78)
    print(f"WALK-FORWARD RESULT — horizon {args.horizon} bars, alpha vs SPY")
    print("=" * 78)
    print(f"{'rule':<24}{'runs':>5}{'vs SPY':>9}{'vs random':>11}{'beat':>7}{'t':>7}{'picks':>7}{'beta':>6}")

    # VERSUS THE CONTROL, ON THE SAME DATES. Every rule here is negative
    # against SPY, because an equal-weighted basket of these names simply
    # lagged the index over this period — that is a size and beta fact, not a
    # verdict on any rule. The question a rule must answer is whether it beat
    # DRAWING NAMES OUT OF THE SAME HAT on the days it actually fired, and a
    # rule that abstains half the time can only be judged on those days.
    ctrl = {d: a for d, a in zip(results["random (control)"].dates,
                                 results["random (control)"].alpha)}
    rows = []
    for name, res in results.items():
        s = res.summary()
        paired = [(a - ctrl[d]) for d, a in zip(res.dates, res.alpha)
                  if a == a and d in ctrl and ctrl[d] == ctrl[d]]
        s["vs_random"] = (sum(paired) / len(paired)) if paired else None
        s["paired_n"] = len(paired)
        rows.append(s)
        if s["runs"] == 0:
            print(f"{name:<24}{0:>5}{'never fired':>9}{'':>11}{'':>7}{'':>7}{s['avg_picks']:>7.1f}")
            continue
        vr = f"{s['vs_random'] * 100:>10.2f}%" if s["vs_random"] is not None else f"{'-':>11}"
        print(f"{name:<24}{s['runs']:>5}{s['mean_alpha'] * 100:>8.2f}%{vr}"
              f"{s['beat_rate'] * 100:>6.0f}%"
              f"{(s['t'] if s['t'] is not None else float('nan')):>7.2f}"
              f"{s['avg_picks']:>7.1f}"
              f"{(s['avg_pick_beta'] if s['avg_pick_beta'] is not None else float('nan')):>6.2f}")

    for s in rows:
        if "vs_matched" in s:
            print(f"B7 {s['rule']:<22} vs matched {s['vs_matched'] * 100:+6.2f}%  "
                  f"beat {s['vs_matched_beat_rate'] * 100:3.0f}%  t {s['vs_matched_t'] or float('nan'):5.2f}  "
                  f"beta picks {s['matched_pick_beta']:.2f} / control {s['matched_ctrl_beta']:.2f}  "
                  f"unbeta {s['matched_unbeta_picks']}  short {s['matched_short_deciles']}")

    out = {
        "horizon": args.horizon,
        "universe_rev": args.universe_rev,
        "match_method": args.match_method if args.matched else None,
        "dropped_as_spliced": dropped,
        "as_of_dates": [str(d.date()) for d in as_of_dates],
        "universe": int(closes.shape[1]),
        "results": rows,
    }
    Path(args.out).write_text(json.dumps(out, indent=2))
    print(f"\nwritten to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
