"""WHAT HAS A PUBLISHED EDGE ACTUALLY BEEN WORTH?

Owner, 2026-09-16, after reading the risk-axis tooltips: "I was under the
impression that I'm looking at a market snapshot when I refresh this page
daily... I thought they were looking for stocks that performed well in certain
market conditions but now im not so sure."

He was right to be suspicious. Measured over the 6,886 predictions this engine
has logged and resolved since 2026-02-23:

    horizon   predicted   realized   beat SPY
    5d          +6.9%       -1.1%      17.6%
    20d         +9.6%       +3.0%      33.9%
    60d        +22.2%       +5.7%      28.3%
    120d       +53.1%      +20.7%      22.4%

The engine overstates by roughly 3.5x and loses to SPY about 70% of the time.
That is not a bug in the arithmetic; it is what taking a maximum over ~7,800
candidate statistics, each resting on ~10 independent episodes, produces. The
winners of that contest are largely the names whose small samples got lucky.

This module does not fix the selection bias — nothing here can, and a rule that
could is a separate piece of work. What it does is stop the number lying about
its own magnitude: every published edge is paired with what edges like it have
HISTORICALLY DELIVERED, measured out of sample from the engine's own log.

Two deliberate choices:

  - CALIBRATION IS PER HORIZON. A 5-day and a 120-day forecast are different
    instruments with different noise; one blended shrinkage factor would flatter
    the short horizons and punish the long ones.

  - IT RETURNS NULL RATHER THAN A FACTOR WHEN THE SAMPLE IS THIN. An
    uncalibrated feed must read as unmeasured, never as a feed with no error —
    the same rule the MEFL projections follow. A calibration fitted on twelve
    resolved predictions would be a second layer of the first mistake.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Iterable, Sequence

# Below this many resolved predictions a horizon is unmeasured, not perfect.
MIN_RESOLVED = 60


@dataclass(frozen=True)
class HorizonCalibration:
    horizon: str
    n: int
    predicted_mean: float
    realized_mean: float
    #: realized / predicted. 0.28 means a posted +50% has returned about +14%.
    ratio: float
    #: Share of predictions that beat SPY over the same window.
    beat_rate: float
    #: Cross-sectional correlation between posted edge and realized return.
    correlation: float
    #: Realized mean of the WORST decile, so the downside is stated too.
    realized_p10: float

    def calibrate(self, edge: float) -> float:
        """What this posted edge has historically been worth."""
        return edge * self.ratio


def _mean(xs: Sequence[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _corr(xs: Sequence[float], ys: Sequence[float]) -> float:
    n = len(xs)
    if n < 3:
        return 0.0
    mx, my = _mean(xs), _mean(ys)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return 0.0
    return sxy / (sxx * syy) ** 0.5


def _percentile(xs: Sequence[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    if len(s) == 1:
        return s[0]
    pos = q * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    frac = pos - lo
    return s[lo] * (1 - frac) + s[hi] * frac


def calibrate_horizon(rows: Iterable[dict]) -> HorizonCalibration | None:
    """Fit one horizon from resolved rows of signal_outcomes.csv.

    Rows need `predicted_edge`, `actual_return` and (optionally) `regime_alpha`.
    Returns None when too few have resolved — see MIN_RESOLVED.
    """
    rows = [r for r in rows
            if r.get("predicted_edge") is not None and r.get("actual_return") is not None]
    if len(rows) < MIN_RESOLVED:
        return None

    pred = [float(r["predicted_edge"]) for r in rows]
    act = [float(r["actual_return"]) for r in rows]
    alpha = [float(r["regime_alpha"]) for r in rows if r.get("regime_alpha") is not None]

    pm, am = _mean(pred), _mean(act)
    # A predicted mean at or below zero cannot scale anything. Publishing a
    # ratio from it would divide by noise and invert signs at random.
    ratio = (am / pm) if pm > 1e-9 else 1.0

    return HorizonCalibration(
        horizon=str(rows[0].get("horizon", "")),
        n=len(rows),
        predicted_mean=pm,
        realized_mean=am,
        ratio=ratio,
        beat_rate=(sum(1 for a in alpha if a > 0) / len(alpha)) if alpha else 0.0,
        correlation=_corr(pred, act),
        realized_p10=_percentile(act, 0.10),
    )


def calibrate_all(rows: Iterable[dict]) -> dict[str, HorizonCalibration]:
    """Per-horizon calibration. Horizons with too little history are absent."""
    by_horizon: dict[str, list[dict]] = {}
    for r in rows:
        h = str(r.get("horizon") or "")
        if not h:
            continue
        by_horizon.setdefault(h, []).append(r)
    out = {}
    for h, rs in by_horizon.items():
        c = calibrate_horizon(rs)
        if c is not None:
            out[h] = c
    return out


def scorecard(rows: Iterable[dict]) -> dict:
    """The engine's own report card, for publishing alongside the signals.

    B8 in the owner's plan: the dashboard grades its own predictions in public.
    Everything here is measured from the log — nothing is asserted.
    """
    rows = list(rows)
    cals = calibrate_all(rows)
    resolved = [r for r in rows
                if r.get("predicted_edge") is not None and r.get("actual_return") is not None]
    dates = sorted({str(r.get("run_date")) for r in resolved if r.get("run_date")})
    alpha = [float(r["regime_alpha"]) for r in resolved if r.get("regime_alpha") is not None]
    return {
        "resolved": len(resolved),
        "first_run": dates[0] if dates else None,
        "last_run": dates[-1] if dates else None,
        "beat_rate": (sum(1 for a in alpha if a > 0) / len(alpha)) if alpha else None,
        "horizons": {h: asdict(c) for h, c in sorted(cals.items())},
        # Said in the payload rather than left to a reader to infer, because
        # every consumer of this file needs the same warning attached.
        "note": (
            "Posted edge is the mean forward return of ~10 independent historical "
            "episodes, selected as the best of roughly 7,800 candidates. It is a "
            "research statistic, not a forecast: ratio is what edges like it have "
            "actually delivered. Use for reviewing holdings, not for picking."
        ),
    }
