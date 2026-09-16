"""B2 — SURVIVING THE FACT THAT WE TOOK A MAXIMUM OVER 7,800 THINGS.

The conditional engine scores ~1,960 tickers at 4 horizons and publishes the
best. Even if every one of those statistics were pure noise, the top of 7,800
draws would look spectacular — and measured against the engine's own resolved
log, that is roughly what is happening: posted +16.6% against realized +4.8%,
correlation with actual returns ~0.00 at every horizon, beating SPY 30% of the
time.

Two corrections, in this order.

SHRINKAGE first, because the estimate is the problem before the threshold is.
Each edge is the mean of about ten independent episodes; a mean from ten noisy
quarterly observations is mostly noise, and the right response is to pull it
toward the population mean by an amount that depends on how little evidence
stands behind it. James-Stein in its plainest form:

    shrunk = grand_mean + (raw - grand_mean) * n / (n + k)

With k = SHRINK_K, a row resting on 10 episodes keeps about half its distance
from the crowd, one resting on 40 keeps four fifths, and a row with a single
episode keeps almost none. This is not a haircut applied for conservatism —
it is the estimate that minimises expected squared error when many noisy means
are estimated at once.

MULTIPLE COMPARISONS second, because "is this big" is meaningless without "how
many chances did it have to look big". Benjamini-Hochberg controls the false
discovery rate across the whole candidate set: at q = 0.10, at most ~10% of
whatever survives is expected to be noise. It is deliberately less brutal than
Bonferroni, which at 7,800 tests would demand a p-value near 6e-6 and pass
nothing, ever.

EXPECT VERY FEW SURVIVORS, OFTEN NONE. That is the correct output of an honest
filter on most days, and it is the same discipline as the fantasy board's "keep
your money this week". A day with no names is information, not a failure.

────────────────────────────────────────────────────────────────────────────
DO NOT RUN THIS ON data/market_signals.csv. Verified 2026-09-16: doing so
"passes" 386 of 408 rows at q=0.10, which is not a result, it is a circular
argument. That file is what SURVIVED the engine's MIN_EDGE filter — the losers
were discarded before it was written. Testing a set of pre-selected winners
against a null of "edge = 0" rejects the null almost everywhere, and the
multiple-comparisons correction is being applied to 408 tests when the real
experiment ran ~7,800.

Two things are required for the correction to mean anything, and validate.py
(B3) supplies both:

  1. THE FULL CANDIDATE SET, every ticker at every horizon, including all the
     rows that never cleared the threshold. The denominator IS the correction.

  2. THE RIGHT NULL. Not "is the conditional mean above zero" — in a rising
     market almost every stock clears that, which is how a screen returned
     +20.7% at 120 days while losing to SPY 78% of the time. The question is
     whether conditioning on the regime beats the SAME stock's unconditional
     forward return over the same horizon. Anything less tests whether the
     market went up.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

# Episodes at which a row keeps half its distance from the population mean.
SHRINK_K = 10.0
# False discovery rate for the survivor test.
DEFAULT_Q = 0.10


def shrink(raw: float, grand_mean: float, n_episodes: float, k: float = SHRINK_K) -> float:
    """Pull an estimate toward the population mean by its own evidence weight."""
    n = max(0.0, float(n_episodes))
    w = n / (n + k)
    return grand_mean + (raw - grand_mean) * w


def shrink_all(rows: list[dict], value_key: str = "edge",
               n_key: str = "n_episodes", k: float = SHRINK_K) -> list[dict]:
    """Shrink every row toward the CROSS-SECTIONAL mean of the same column.

    The population mean is taken from the published set itself. That is the
    right reference: these rows are what the engine is choosing between.
    """
    vals = [float(r[value_key]) for r in rows if r.get(value_key) is not None]
    if not vals:
        # Nothing to take a population mean FROM. Every row still gets the key,
        # set to None — a caller reading `row["shrunk"]` must not get a
        # KeyError on the one path where no row can be shrunk at all.
        return [dict(r, shrunk=None) for r in rows]
    grand = sum(vals) / len(vals)
    out = []
    for r in rows:
        d = dict(r)
        if r.get(value_key) is None:
            d["shrunk"] = None
        else:
            d["shrunk"] = shrink(float(r[value_key]), grand, r.get(n_key) or 0, k)
        out.append(d)
    return out


# ── is it distinguishable from luck at all? ──────────────────────────────────

def _normal_sf(z: float) -> float:
    """P(Z > z). math.erfc is exact enough and avoids a scipy dependency."""
    return 0.5 * math.erfc(z / math.sqrt(2.0))


def t_stat(mean: float, spread: float, n_episodes: float) -> float | None:
    """How many standard errors above zero, using EPISODES as the sample size.

    The engine reports n_obs around 24-28 and n_episodes around 10. Using the
    observation count would divide the standard error by 5 instead of 3.2 and
    overstate significance by roughly 60% — analog days that sit one or two
    sessions apart, measured over a 120-day forward window, are the same
    observation wearing different dates.
    """
    n = float(n_episodes or 0)
    if n < 2 or spread is None or spread <= 0:
        return None
    return float(mean / (spread / math.sqrt(n)))


def p_value(mean: float, spread: float, n_episodes: float) -> float | None:
    """One-sided: we only ever act on a POSITIVE edge, so that is the test."""
    t = t_stat(mean, spread, n_episodes)
    if t is None:
        return None
    return _normal_sf(t)


@dataclass(frozen=True)
class Survivor:
    key: str
    value: float
    p: float
    rank: int
    threshold: float


def benjamini_hochberg(pvalues: dict[str, float], q: float = DEFAULT_Q) -> set[str]:
    """Return the keys whose p-values survive FDR control at level q.

    Sort ascending, find the largest i where p_(i) <= i/m * q, and keep
    everything up to it. Returns an empty set when nothing survives — which is
    the expected answer most days and must never be papered over.
    """
    items = sorted(((k, p) for k, p in pvalues.items() if p is not None),
                   key=lambda kv: kv[1])
    m = len(items)
    if m == 0:
        return set()
    cutoff_index = 0
    for i, (_, p) in enumerate(items, start=1):
        if p <= (i / m) * q:
            cutoff_index = i
    return {k for k, _ in items[:cutoff_index]}


def select(rows: list[dict], q: float = DEFAULT_Q, k: float = SHRINK_K,
           value_key: str = "edge", spread_key: str = "spread",
           n_key: str = "n_episodes", key_field: str = "key") -> dict:
    """The whole B2 pipeline: shrink, test, control, report.

    Returns both the survivors and the counts, because "0 of 398 survived" is
    the single most useful line this module can print on a given day.
    """
    shrunk = shrink_all(rows, value_key=value_key, n_key=n_key, k=k)
    pvals: dict[str, float] = {}
    for r in shrunk:
        if r.get("shrunk") is None or r.get(spread_key) is None:
            continue
        p = p_value(r["shrunk"], r[spread_key], r.get(n_key) or 0)
        if p is not None:
            pvals[str(r[key_field])] = p
    kept = benjamini_hochberg(pvals, q)
    return {
        "survivors": kept,
        "n_candidates": len(rows),
        "n_tested": len(pvals),
        "n_survivors": len(kept),
        "q": q,
        "rows": shrunk,
        "pvalues": pvals,
    }
