"""THE SCANNER — what a name is doing NOW, as opposed to what names like it did once.

Owner, 2026-09-16: "Can you explain why regime desk isnt a market scanner and
help me work toward turning it into one? I was uder the inpression that I'm
looking at a market snapshot when I refresh this page daily."

It wasn't one, and this is the missing half. The existing engine conditions on
the MARKET's state (four SPY features), picks ~30 analog days from history, and
reports what each ticker did over the following weeks. Nothing in it ever looks
at the ticker's own current behaviour, which is why the published list was 78%
to 100% unchanged day over day and twice byte-identical across a week.

Everything here is a property of the last bar and the bars immediately behind
it, so it moves when the market moves. No forward returns, no analog days, no
history-conditioned statistics: this module answers "what is this stock doing",
and B2/B3 decide whether any of it should influence a purchase.

DESIGN RULES, learned from what went wrong in the conditional engine:

  - EVERY FEATURE IS NORMALISED BY SOMETHING. A raw 20-day return ranks the
    most volatile names top every time, which is exactly the artifact measured
    in the old feed (top edge quartile: beta 1.32, p90-p10 spread 1.58 against
    0.97 / 0.32 in the bottom). Moves are expressed in the stock's OWN
    volatility, so "big move" means big for this name.

  - MISSING IS None, NEVER ZERO. A name with 40 days of history has no
    200-day average, and a 0.0 there would read as "sitting exactly on its
    200-day" — a fact, not a gap. Every helper returns None when it cannot be
    computed, and the composite refuses to score a name with holes in it.

  - NOTHING IS LOOK-AHEAD. Each function takes a series that ends at the bar
    being evaluated. The walk-forward harness in validate.py depends on that
    being true, so nothing here may peek at a later index.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# Windows, in trading days. One month ~= 21 sessions.
MONTH = 21
QUARTER = 63
HALF_YEAR = 126
YEAR = 252


def _clean(s: pd.Series) -> pd.Series:
    return pd.Series(s).astype(float).dropna()


def _ret(s: pd.Series, n: int) -> float | None:
    """Simple return over the last n bars. None when the history is short."""
    s = _clean(s)
    if len(s) < n + 1:
        return None
    prior = s.iloc[-(n + 1)]
    if prior <= 0:
        return None
    return float(s.iloc[-1] / prior - 1.0)


def relative_strength(stock: pd.Series, bench: pd.Series, n: int) -> float | None:
    """Return over n bars MINUS the benchmark's over the same bars.

    The whole point of the exercise is to stop paying for beta. Measured on the
    old feed: its picks returned +20.7% at 120 days and still lost to SPY in
    77.6% of cases, because a raw return in a rising tape flatters everything.
    """
    a, b = _ret(stock, n), _ret(bench, n)
    if a is None or b is None:
        return None
    return a - b


def distance_from_ma(s: pd.Series, n: int) -> float | None:
    """How far above/below its n-day moving average, as a fraction of the MA."""
    s = _clean(s)
    if len(s) < n:
        return None
    ma = float(s.iloc[-n:].mean())
    if ma <= 0:
        return None
    return float(s.iloc[-1] / ma - 1.0)


def range_position(s: pd.Series, n: int = 20) -> float | None:
    """Where the last close sits in its n-day range: 0 = the low, 1 = the high.

    A flat range is not a name sitting at its low. When high == low the position
    is undefined and returns None rather than 0.0.
    """
    s = _clean(s)
    if len(s) < n:
        return None
    window = s.iloc[-n:]
    lo, hi = float(window.min()), float(window.max())
    if hi - lo <= 0:
        return None
    return float((s.iloc[-1] - lo) / (hi - lo))


def volume_surge(v: pd.Series, n: int = 20, base: int = 63) -> float | None:
    """Recent average volume over its longer-run average. 1.0 = normal."""
    v = _clean(v)
    if len(v) < base or base <= n:
        return None
    recent = float(v.iloc[-n:].mean())
    normal = float(v.iloc[-base:].mean())
    if normal <= 0:
        return None
    return recent / normal


def realised_vol(s: pd.Series, n: int = 20) -> float | None:
    """Daily return standard deviation over n bars. The normaliser for moves."""
    s = _clean(s)
    if len(s) < n + 1:
        return None
    r = s.pct_change().dropna().iloc[-n:]
    if len(r) < n or r.std() <= 0:
        return None
    return float(r.std())


def move_in_sigma(s: pd.Series, n: int = MONTH, vol_window: int = 63) -> float | None:
    """The n-day move expressed in this name's OWN daily sigma.

    This is the anti-artifact feature. A 15% month is routine for a biotech and
    extraordinary for a utility; ranking on the raw number sorts the universe by
    volatility, which is the trap the conditional engine fell into.
    """
    r = _ret(s, n)
    sd = realised_vol(s, vol_window)
    if r is None or sd is None or sd <= 0:
        return None
    # Scale the per-day sigma to the length of the window being measured.
    return float(r / (sd * np.sqrt(n)))


def drawdown_from_high(s: pd.Series, n: int = YEAR) -> float | None:
    """Distance below the highest close of the last n bars (<= 0)."""
    s = _clean(s)
    if len(s) < min(n, 60):
        return None
    window = s.iloc[-n:]
    hi = float(window.max())
    if hi <= 0:
        return None
    return float(s.iloc[-1] / hi - 1.0)


def features(stock: pd.Series, bench: pd.Series, volume: pd.Series | None = None) -> dict:
    """Every current-state feature for one name, as of the last bar given."""
    return {
        "rs_1m": relative_strength(stock, bench, MONTH),
        "rs_3m": relative_strength(stock, bench, QUARTER),
        "rs_6m": relative_strength(stock, bench, HALF_YEAR),
        "above_50d": distance_from_ma(stock, 50),
        "above_200d": distance_from_ma(stock, 200),
        "range_pos_20d": range_position(stock, 20),
        "move_1m_sigma": move_in_sigma(stock, MONTH),
        "vol_20d": realised_vol(stock, 20),
        "drawdown_1y": drawdown_from_high(stock, YEAR),
        "volume_surge": volume_surge(volume) if volume is not None else None,
    }


# ── the composite ────────────────────────────────────────────────────────────
#
# WEIGHTS ARE EQUAL AND DELIBERATELY SO. Tuning them against the same history
# that would then be used to judge the result is how the conditional engine
# produced a +53% edge that delivered +20%. If B3's walk-forward says a
# weighting earns its keep, it can be fitted THERE, on data held out from the
# test. Until then, equal weight over z-scores is the honest default.
COMPOSITE_FEATURES = ("rs_1m", "rs_3m", "rs_6m", "above_50d", "range_pos_20d")


def cross_section_rank(rows: dict[str, dict], feature: str) -> dict[str, float]:
    """Percentile rank of one feature across names, 0..1. Names missing it are
    ABSENT from the result rather than ranked last — a stock we cannot measure
    is not a stock that scored badly."""
    vals = {t: f[feature] for t, f in rows.items() if f.get(feature) is not None}
    if len(vals) < 2:
        return {}
    s = pd.Series(vals).rank(pct=True)
    return {t: float(v) for t, v in s.items()}


def composite(rows: dict[str, dict],
              features_used: tuple[str, ...] = COMPOSITE_FEATURES,
              min_present: int = 4) -> dict[str, float]:
    """Average percentile rank across features, 0..1, per ticker.

    A name must carry at least `min_present` of the features to be scored at
    all. Scoring on one of five would let a stock with almost no history win on
    a single lucky percentile.
    """
    ranked = {f: cross_section_rank(rows, f) for f in features_used}
    out: dict[str, float] = {}
    for ticker in rows:
        got = [ranked[f][ticker] for f in features_used if ticker in ranked.get(f, {})]
        if len(got) < min_present:
            continue
        out[ticker] = float(sum(got) / len(got))
    return out


def table(prices, volumes=None, bench: str = "SPY", min_bars: int = 260):
    """Score a whole price panel at its last bar. Returns a DataFrame indexed
    by ticker with every feature plus `composite`, best first.

    Lives here rather than inline in ci_scan so it can be tested: the daily job
    calls exactly the function the tests exercise.

    A ticker with fewer than `min_bars` of history is ABSENT from the result,
    never present with a zero — the same rule every feature above follows.
    """
    import pandas as _pd
    if bench not in prices.columns:
        raise ValueError(f"no {bench} column to measure strength against")
    b = prices[bench].dropna()
    if len(b) < min_bars:
        raise ValueError(f"{bench} has {len(b)} bars, need {min_bars}")
    rows = {}
    for t in prices.columns:
        s = prices[t].dropna()
        if len(s) < min_bars:
            continue
        v = None
        if volumes is not None and t in getattr(volumes, "columns", []):
            v = volumes[t].dropna()
        rows[t] = features(s, b, v)
    if not rows:
        return _pd.DataFrame()
    out = _pd.DataFrame.from_dict(rows, orient="index")
    out.index.name = "ticker"
    out["composite"] = _pd.Series(composite(rows))
    return out[out["composite"].notna()].sort_values("composite", ascending=False)
