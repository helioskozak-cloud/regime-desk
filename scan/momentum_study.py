"""momentum_study.py — does Momentum Shift tell us anything Where It Goes Next doesn't? (Q54)

Owner, 2026-10-08: "what is momentum shift telling us that the other two
arent". Where It Goes Next gives the distribution of the regime label 20
sessions later for every past session with today's label. Momentum Shift
says whether the last 5 sessions' 20-day return and vol moved against the 5
before. The question is whether knowing the momentum state CHANGES that
distribution.

THE RULE, COMMITTED BEFORE THE FIRST RUN
  Data: SPY from its 1993 launch, the scan's own features (compute_features),
  labels (label_history) and momentum shifts (momentum_shifts). Momentum state
  exactly as the page reads it (_tvVerdict): direction Flat if |return shift|
  is under the 40th percentile of |shift|, else Improving/Fading by sign; vol
  steady under its own 40th percentile, else easing/rising. Percentiles are
  taken on the FIT half only.

  Model A (what Home shows now): P(label in 20 | label today).
  Model B (folded in):           P(label in 20 | label today, direction, vol).
  Cells with under 40 sessions or 3 spells fall back to Model A, as the page
  already does for thin labels. Additive smoothing 0.5 on both.

  Fit on sessions up to 2009-12-31; score on 2010-01-01 onward (horizon rows
  that reach past the end are dropped). Score = mean log loss of the label
  actually seen 20 sessions later. Uncertainty = 1,000 bootstrap resamples of
  calendar years of the test half (overlapping days are not independent; years
  are close to it at a 20-session horizon).

  VERDICT
    fold in   B beats A out of sample, and the 95% bootstrap interval of the
              improvement is above zero.
    one line  otherwise.

  Also reported, not part of the verdict: the panel's claim that Fading with
  rising swings "has come before regime changes" — P(label different in 20)
  in that state vs for the same labels in any state, on the test half.

Writes data/momentum_study.json. Run locally; not part of the daily scan.

  python scan/momentum_study.py
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
OUT = ROOT / "data" / "momentum_study.json"
H = rm.NEXT_HORIZON
SPLIT = pd.Timestamp("2009-12-31")
MIN_DAYS, MIN_SPELLS = rm.NEXT_MIN_DAYS, rm.NEXT_MIN_SPELLS
ALPHA = 0.5
BOOT = 1000


def frame() -> pd.DataFrame:
    raw = cs._download_batch(["SPY"], "max")
    f = cs.compute_features(raw)
    f = f[f["ticker"] == "SPY"].sort_values("date").reset_index(drop=True)
    f = f.dropna(subset=["return_20", "volatility", "drawdown"]).reset_index(drop=True)
    f["date"] = pd.to_datetime(f["date"])
    f["label"] = rm.label_history(f).values
    m = rm.momentum_shifts(f)
    f = f.join(m)
    f["later"] = f["label"].shift(-H)
    f["spell"] = (f["label"] != f["label"].shift()).cumsum()
    return f


def states(f: pd.DataFrame, fit: pd.DataFrame) -> pd.DataFrame:
    rq = np.percentile(fit["ret_shift"].abs(), 40)
    vq = np.percentile(fit["vol_shift"].abs(), 40)
    f["dir"] = np.where(f["ret_shift"].abs() < rq, "Flat",
                        np.where(f["ret_shift"] > 0, "Improving", "Fading"))
    f["vol"] = np.where(f["vol_shift"].abs() < vq, "steady",
                        np.where(f["vol_shift"] < 0, "easing", "rising"))
    f["mom"] = f["dir"] + "|" + f["vol"]
    return f


def dist(rows: pd.DataFrame, labels: list[str]) -> dict:
    c = rows["later"].value_counts()
    tot = len(rows) + ALPHA * len(labels)
    return {k: (c.get(k, 0) + ALPHA) / tot for k in labels}


def fit_models(fit: pd.DataFrame, labels: list[str]):
    A = {lab: dist(g, labels) for lab, g in fit.groupby("label")}
    B, thin = {}, []
    for (lab, mom), g in fit.groupby(["label", "mom"]):
        if len(g) >= MIN_DAYS and g["spell"].nunique() >= MIN_SPELLS:
            B[(lab, mom)] = dist(g, labels)
        else:
            thin.append((lab, mom))
    return A, B, thin


def loss(test: pd.DataFrame, A, B, uniform) -> tuple[np.ndarray, np.ndarray]:
    la, lb = [], []
    for lab, mom, later in zip(test["label"], test["mom"], test["later"]):
        pa = A.get(lab, uniform)
        pb = B.get((lab, mom), pa)
        la.append(-np.log(pa[later]))
        lb.append(-np.log(pb[later]))
    return np.array(la), np.array(lb)


def main() -> int:
    f = frame()
    f = f.dropna(subset=["ret_shift", "vol_shift"]).reset_index(drop=True)
    fit0 = f[(f["date"] <= SPLIT)]
    f = states(f, fit0)
    f = f.dropna(subset=["later"]).reset_index(drop=True)
    fit, test = f[f["date"] <= SPLIT], f[f["date"] > SPLIT].copy()
    labels = sorted(f["label"].unique())
    uniform = {k: 1 / len(labels) for k in labels}
    A, B, thin = fit_models(fit, labels)
    la, lb = loss(test, A, B, uniform)
    test["gain"] = la - lb
    years = test["date"].dt.year.values
    uy = np.unique(years)
    by = {y: test["gain"].values[years == y] for y in uy}
    rng = np.random.default_rng(0)
    boots = []
    for _ in range(BOOT):
        pick = rng.choice(uy, size=len(uy), replace=True)
        g = np.concatenate([by[y] for y in pick])
        boots.append(g.mean())
    lo, hi = np.percentile(boots, [2.5, 97.5])
    gain = float(test["gain"].mean())
    verdict = "fold in" if gain > 0 and lo > 0 else "one line"

    # Stay rates by state, test half, for the labels Home actually shows.
    stay = []
    for lab, g in test.groupby("label"):
        base = float((g["later"] == lab).mean())
        for mom, gm in g.groupby("mom"):
            if len(gm) >= MIN_DAYS and gm["spell"].nunique() >= MIN_SPELLS:
                stay.append({"label": lab, "momentum": mom, "sessions": int(len(gm)),
                             "spells": int(gm["spell"].nunique()),
                             "stays": round(float((gm["later"] == lab).mean()), 3),
                             "stays_any_state": round(base, 3)})
    # The panel's claim.
    fr = test[test["mom"] == "Fading|rising"]
    same = test[test["label"].isin(fr["label"].unique())]
    claim = {"sessions": int(len(fr)), "spells": int(fr["spell"].nunique()),
             "changed_in_20": round(float((fr["later"] != fr["label"]).mean()), 3) if len(fr) else None,
             "changed_in_20_same_labels_any_state":
                 round(float((same["later"] != same["label"]).mean()), 3) if len(same) else None}

    out = {"generated": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
           "question": "Q54: does Momentum Shift change where the regime goes in 20 sessions?",
           "rule": "fold in iff out-of-sample log-loss gain > 0 with 95% year-bootstrap interval above 0",
           "fit": [str(fit["date"].min().date()), str(fit["date"].max().date())],
           "test": [str(test["date"].min().date()), str(test["date"].max().date())],
           "test_sessions": int(len(test)), "test_years": int(len(uy)),
           "logloss_label_only": round(float(la.mean()), 4),
           "logloss_label_and_momentum": round(float(lb.mean()), 4),
           "gain_per_session": round(gain, 4),
           "gain_pct": round(gain / float(la.mean()) * 100, 2),
           "gain_ci95": [round(float(lo), 4), round(float(hi), 4)],
           "cells_used": len(B), "cells_thin": len(thin),
           "verdict": verdict,
           "stay_by_state_test": sorted(stay, key=lambda r: (r["label"], -r["sessions"])),
           "fading_rising_claim_test": claim}
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "stay_by_state_test"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
