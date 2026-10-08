"""analog_spy_study.py — do the SPY analog readings add anything to the regime label?

Owner, 2026-10-08 (chose to test before cutting): the analog STOCK edge was
retired after it lost to random picks once beta was removed. Two readings on
Home still come from the same 30 analog days, but read SPY itself:

  1. REVERSAL RISK (Regime Analysis): the share of analog days whose next 20
     sessions went the other way from their trailing 20.
  2. THE ANALOG LINE in Where It Goes Next: the regime label 20 sessions after
     each analog day.

Neither was ever tested. The question for each: given today's regime label,
does knowing the analog days make the 20-session forecast better?

THE RULE, COMMITTED BEFORE THE FIRST RUN
  Data: SPY from its 1993 launch through the scan's own code — features
  (ci_scan.compute_features), labels (regime_measures.label_history, on the
  full history, as the momentum study did; the same labels feed every model,
  so any look-ahead in them is shared, not an advantage to one side).

  Analog days at a test date t, exactly as the daily scan builds them: the
  window is the 756 sessions ending at t (the scan downloads 3 years);
  z-score the four ANALOG_FEATURES over that window; drop the last 30
  sessions (EXCLUDE_RECENT_DAYS); take the 30 nearest (SIMILAR_DAY_COUNT).
  Every analog day's 20-session outcome is finished by t.

  Test dates: every session from 2010-01-01 whose own 20-session outcome is
  known. Every model is fitted only on sessions whose outcome was known at t
  (s + 20 <= t), so nothing looks ahead.

  NEXT REGIME (10 labels), smoothing 0.5 per label:
    A  label only:  P(label at s+20 | label at s = today's label), all s
                    since 1993 with s + 20 <= t. What Home's main table shows.
    B  analog only: the labels 20 sessions after today's 30 analog days.
    C  both:        0.5 A + 0.5 B.          <- the verdict model
  REVERSAL (yes/no; sessions where either window is exactly flat are
  dropped, as on the page), Beta(0.5, 0.5) smoothing:
    A  label only:  P(reversal | today's label), all s since 1993, s + 20 <= t.
    B  analog only: reversals among today's analog days.
    C  both:        0.5 A + 0.5 B.          <- the verdict model

  Score: mean log loss of what actually happened 20 sessions later.
  Uncertainty: 1,000 bootstrap resamples of calendar years of test dates
  (overlapping 20-session windows are not independent; years nearly are).

  VERDICT, per reading
    keep   C beats A (mean log-loss gain > 0) AND the 95% bootstrap interval
           of the gain is above zero.
    cut    otherwise.
  B against A is reported beside it, not part of the verdict. So is the page's
  own comparison for reversal: the share of ALL sessions in the 756-session
  window that reversed ("any day").

Writes data/analog_spy_study.json. Run locally; not part of the daily scan.

  python scan/analog_spy_study.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ci_scan as cs  # noqa: E402
import regime_measures as rm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "analog_spy_study.json"
H = rm.NEXT_HORIZON                 # 20
WINDOW = 756                        # 3 years of sessions, as the scan downloads
N_ANALOG = cs.SIMILAR_DAY_COUNT     # 30
EXCLUDE = cs.EXCLUDE_RECENT_DAYS    # 30
START = pd.Timestamp("2010-01-01")
ALPHA = 0.5
BOOT = 1000


def frame() -> pd.DataFrame:
    raw = cs._download_batch(["SPY"], "max")
    f = cs.compute_features(raw)
    f = f[f["ticker"] == "SPY"].sort_values("date").reset_index(drop=True)
    f = f.dropna(subset=rm.ANALOG_FEATURES).reset_index(drop=True)
    f["date"] = pd.to_datetime(f["date"])
    f["label"] = rm.label_history(f).values
    f["later"] = f["label"].shift(-H)
    fwd = f["close"].shift(-H) / f["close"] - 1
    f["rev"] = [rm._flip(t, x) for t, x in zip(f["return_20"], fwd)]
    return f


def analogs_at(X: np.ndarray, t: int) -> np.ndarray:
    """Row indices of the analog days for test row t (as rm.analog_days)."""
    lo = max(0, t - WINDOW + 1)
    w = X[lo:t + 1]
    mu, sd = w.mean(axis=0), w.std(axis=0, ddof=1)
    sd[sd == 0] = 1
    z = (w - mu) / sd
    d = np.linalg.norm(z - z[-1], axis=1)[:-EXCLUDE]
    near = np.argsort(d, kind="stable")[:N_ANALOG]
    return lo + near


def cat(counts: dict, n: int, labels: list[str]) -> dict:
    tot = n + ALPHA * len(labels)
    return {k: (counts.get(k, 0) + ALPHA) / tot for k in labels}


def boot_ci(gain: np.ndarray, years: np.ndarray, seed: int) -> tuple[float, float]:
    uy = np.unique(years)
    by = {y: gain[years == y] for y in uy}
    rng = np.random.default_rng(seed)
    b = [np.concatenate([by[y] for y in rng.choice(uy, size=len(uy))]).mean() for _ in range(BOOT)]
    lo, hi = np.percentile(b, [2.5, 97.5])
    return float(lo), float(hi)


def verdict(la, lc, years, seed) -> dict:
    g = la - lc
    lo, hi = boot_ci(g, years, seed)
    return {"gain": float(g.mean()), "ci95": [lo, hi],
            "verdict": "keep" if g.mean() > 0 and lo > 0 else "cut"}


def main() -> int:
    f = frame()
    labels = sorted(f["label"].unique())
    X = f[rm.ANALOG_FEATURES].to_numpy(dtype=float)
    lab = f["label"].to_numpy()
    later = f["later"].to_numpy()
    rev = f["rev"].to_numpy()
    dates = f["date"]

    # Expanding label tables, updated as each session's outcome becomes known.
    nxt = {k: {} for k in labels}          # label today -> counts of label in 20
    nxt_n = {k: 0 for k in labels}
    rv = {k: [0, 0] for k in labels}        # label today -> [reversed, usable]
    added = 0                               # sessions s already counted (s + H <= t)

    R = {"next": {"A": [], "B": [], "C": []}, "rev": {"A": [], "B": [], "C": [], "any": []}}
    yrs_next, yrs_rev = [], []
    n_test = 0
    for t in range(len(f)):
        while added + H <= t:               # outcome of session `added` known at t
            s = added
            if isinstance(later[s], str):
                nxt[lab[s]][later[s]] = nxt[lab[s]].get(later[s], 0) + 1
                nxt_n[lab[s]] += 1
            if rev[s] is not None:
                rv[lab[s]][0] += int(rev[s]); rv[lab[s]][1] += 1
            added += 1
        if dates.iloc[t] < START or t < WINDOW:
            continue
        idx = analogs_at(X, t)
        idx = idx[idx + H <= t]
        if len(idx) == 0:
            continue
        n_test += 1
        y = dates.iloc[t].year
        today = lab[t]

        if isinstance(later[t], str):
            pa = cat(nxt[today], nxt_n[today], labels)
            ac = {}
            for i in idx:
                ac[later[i]] = ac.get(later[i], 0) + 1
            pb = cat(ac, len(idx), labels)
            pc = {k: 0.5 * pa[k] + 0.5 * pb[k] for k in labels}
            o = later[t]
            R["next"]["A"].append(-np.log(pa[o]))
            R["next"]["B"].append(-np.log(pb[o]))
            R["next"]["C"].append(-np.log(pc[o]))
            yrs_next.append(y)

        if rev[t] is not None:
            k, n = rv[today]
            qa = (k + ALPHA) / (n + 2 * ALPHA)
            ar = [rev[i] for i in idx if rev[i] is not None]
            qb = (sum(ar) + ALPHA) / (len(ar) + 2 * ALPHA)
            qc = 0.5 * qa + 0.5 * qb
            lo = max(0, t - WINDOW + 1)
            win = [rev[s] for s in range(lo, t - H + 1) if rev[s] is not None]
            qany = (sum(win) + ALPHA) / (len(win) + 2 * ALPHA)
            o = bool(rev[t])
            ll = lambda q: -np.log(q if o else 1 - q)
            for key, q in (("A", qa), ("B", qb), ("C", qc), ("any", qany)):
                R["rev"][key].append(ll(q))
            yrs_rev.append(y)

    out = {"as_of": str(dates.iloc[-1].date()), "test_from": str(START.date()),
           "test_dates": n_test, "rule": "see scan/analog_spy_study.py docstring"}
    for name, yrs, seed in (("next", np.array(yrs_next), 1), ("rev", np.array(yrs_rev), 2)):
        L = {k: np.array(v) for k, v in R[name].items()}
        res = {"n": int(len(yrs)), "years": int(len(np.unique(yrs))),
               "logloss": {k: float(v.mean()) for k, v in L.items()},
               "C_vs_A": verdict(L["A"], L["C"], yrs, seed),
               "B_vs_A": verdict(L["A"], L["B"], yrs, seed + 10)}
        if name == "rev":
            res["A_vs_any"] = verdict(L["any"], L["A"], yrs, seed + 20)
            res["B_vs_any"] = verdict(L["any"], L["B"], yrs, seed + 30)
        out[name] = res
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
