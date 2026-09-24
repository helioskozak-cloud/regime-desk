"""The Regime Analysis card's rules and measurements, in one place.

Imported by BOTH ends of the pipeline: scan/ci_scan.py, which has three years
of prices and computes the measurements, and build/snapshot_builder.py, which
labels today's regime and explains it. They used to hold separate copies of
nothing in particular — the rules lived only in the builder — but three of the
measurements below need the rules applied to years of SPY history, and that
history exists only in the scan. A second copy of the rules in the scan would
be the first thing to drift. So the rules live here, and both import them.

Everything in this file is pure: data in, numbers out, no I/O, no network.

WHAT IS MEASURED, AND WHY EACH REPLACED WHAT IT DID
---------------------------------------------------

Owner, 2026-09-14, after the card's explainer panels showed two tiles had never
been computed and a third was a lookup dressed as a probability: "build breadth
and persistence", and rebuild Reversal Risk "as a measured number".

  BREADTH       Share of the scan universe closing above its own 50-day
                average. Was: a hardcoded 0.5 default, shown as 50% since the
                card existed.

  PERSISTENCE   Of every past session that carried today's regime label, the
                share still carrying it 20 sessions later. Was: the same
                hardcoded 0.5.

  REVERSAL      Of the 30 past days most like today — the SAME analog days
                the stock-signal engine uses — the share where SPY's next 20
                sessions went the opposite way to its last 20. Shown against
                the same rate across every day, because 40% means nothing
                until you know whether any-day is 30% or 50%. Was: a four-step
                lookup that could only ever read 25, 35, 50 or 70.

Every one of them can come back None, and None means NOT MEASURED — too few
names, too few past sessions, or a latest session that did not finish loading.
It is never a stand-in for a middling reading. Three placeholders just got
removed from this card for exactly that reason.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── THE REGIME RULES ─────────────────────────────────────────────────────────
#
# Read top to bottom, first match wins. The classifier and the explainer both
# walk this table, so the rule highlighted on the card and the label printed on
# it cannot disagree.
#
# Defaults are the ones the original if-ladder used for a missing key, kept
# exactly: the regime streak re-classifies every past session, so a changed
# default would silently relabel history. tests/test_regime_rules.py pins the
# table against a verbatim copy of that ladder.
REGIME_DEFAULTS = {"ret_20d": 0.0, "drawdown_60d": 0.0, "vol_20d": 0.015}

# (label, [(key, op, threshold), ...]) — every condition must hold.
REGIME_RULES = [
    ("High Volatility", [("vol_20d", ">", 0.025)]),
    ("Deep Correction", [("drawdown_60d", "<", -0.15)]),
    ("Correction",      [("drawdown_60d", "<", -0.08), ("ret_20d", "<", 0.0)]),
    ("Recovery",        [("drawdown_60d", "<", -0.05), ("ret_20d", ">", 0.0)]),
    ("Bull Trend",      [("ret_20d", ">", 0.05)]),
    ("Pullback",        [("ret_20d", "<", -0.05)]),
]
REGIME_FALLBACK = "Neutral"


def _val(state, key):
    v = state.get(key, REGIME_DEFAULTS[key])
    return REGIME_DEFAULTS[key] if v is None else float(v)


def holds(x, op, t):
    if op == ">":
        return x > t
    if op == "<":
        return x < t
    if op == "abs<":
        return abs(x) < t
    raise ValueError(f"unknown operator {op!r}")


def first_match(state, rules, fallback):
    for out, conds in rules:
        if all(holds(_val(state, k), op, t) for k, op, t in conds):
            return out
    return fallback


def classify_regime(state):
    """Regime label for one SPY state dict (ret_20d, drawdown_60d, vol_20d)."""
    return first_match(state, REGIME_RULES, REGIME_FALLBACK)


def explain_rules(state, rules, fallback):
    """Every rule, each condition against today's reading, and which one fired."""
    result = first_match(state, rules, fallback)
    out, fired_seen = [], False
    for label, conds in rules:
        cs = [{"key": k, "op": op, "threshold": t, "value": _val(state, k),
               "met": holds(_val(state, k), op, t)} for k, op, t in conds]
        is_fired = (not fired_seen) and all(c["met"] for c in cs)
        fired_seen = fired_seen or is_fired
        out.append({"result": label, "conditions": cs, "fired": is_fired,
                    "shadowed": (not is_fired) and all(c["met"] for c in cs)})
    return {"result": result, "rules": out, "fallback": fallback,
            "fell_through": not fired_seen}


# ── SPY FEATURES -> REGIME LABELS ────────────────────────────────────────────

def label_history(spy: pd.DataFrame) -> pd.Series:
    """Regime label for every row of SPY's feature frame, oldest first.

    `spy` has the scan's own column names: return_20, drawdown, volatility.
    """
    return pd.Series(
        [classify_regime({"ret_20d": r, "drawdown_60d": d, "vol_20d": v})
         for r, d, v in zip(spy["return_20"], spy["drawdown"], spy["volatility"])],
        index=spy.index,
    )


def _runs(labels: list[str]) -> list[tuple[str, int]]:
    """[(label, run length), ...] in order."""
    out = []
    for lab in labels:
        if out and out[-1][0] == lab:
            out[-1] = (lab, out[-1][1] + 1)
        else:
            out.append((lab, 1))
    return out


def regime_streak(labels: pd.Series) -> int | None:
    """Consecutive sessions, ending today, carrying today's label.

    Over the WHOLE history, not the last 20 rows. The builder used to count
    streaks from a 20-session window, so any regime older than 20 sessions was
    silently reported as a 20-day streak — a cap that looked like a reading.
    """
    if labels is None or len(labels) == 0:
        return None
    return _runs(list(labels))[-1][1]


# ── PERSISTENCE ──────────────────────────────────────────────────────────────

PERSIST_HORIZON = 20      # sessions: the same window as the 20-day return
PERSIST_MIN_DAYS = 40     # below this, a base rate is an anecdote
PERSIST_MIN_SPELLS = 3    # ...and so is one that rests on one or two spells


def persistence(labels: pd.Series, horizon: int = PERSIST_HORIZON) -> dict:
    """How often today's regime has still held `horizon` sessions later.

    Asks "is this label still on the card a month from now", not "does it hold
    unbroken", so a spell that dips out for a day and returns counts as held.
    Stated on the panel.

    Overlapping daily observations are not independent — forty days inside one
    long spell are closer to one observation than forty — so the number of
    separate SPELLS is reported beside the day count, and a rate resting on too
    few spells is withheld rather than printed.
    """
    labs = list(labels) if labels is not None else []
    if not labs:
        return {"value": None, "reason": "no regime history"}
    today = labs[-1]
    held = [labs[i + horizon] == today
            for i in range(len(labs) - horizon) if labs[i] == today]
    runs = _runs(labs)
    # Completed spells only: the one still running has no length yet, and
    # counting it would drag the median towards today's streak.
    finished = [n for lab, n in runs[:-1] if lab == today]
    spells = sum(1 for lab, _ in runs if lab == today)
    # THE BASE RATE, because a common label is sticky by construction. If a
    # label covers 80% of all sessions, a day carrying it will carry it again
    # 20 sessions later most of the time for no reason beyond how common it is.
    # So: over the same window, the share of ALL sessions whose label 20 sessions
    # on was today's label. Persistence is information only above that.
    ahead = [labs[i + horizon] == today for i in range(len(labs) - horizon)]
    out = {
        "label": today,
        "horizon": horizon,
        "days": len(held),
        "held": int(sum(held)),
        "base_rate": (round(sum(ahead) / len(ahead), 4) if ahead else None),
        "spells": spells,
        "median_spell": (float(np.median(finished)) if finished else None),
        "streak": runs[-1][1],
        "history_sessions": len(labs),
    }
    if len(held) < PERSIST_MIN_DAYS or spells < PERSIST_MIN_SPELLS:
        out["value"] = None
        out["reason"] = (f"only {len(held)} past sessions in {spells} spell"
                         f"{'' if spells == 1 else 's'} of {today} in the history")
    else:
        out["value"] = round(sum(held) / len(held), 4)
    return out


# ── ANALOG DAYS (shared with the stock-signal engine) ────────────────────────

ANALOG_FEATURES = ["return_5", "return_20", "volatility", "drawdown"]


def analog_days(spy: pd.DataFrame, n: int, exclude_recent: int) -> pd.DataFrame:
    """The `n` past SPY sessions closest to today, by z-scored distance.

    Lifted verbatim out of ci_scan.run_scan so the Reversal measurement uses
    the SAME days the stock signals are conditioned on. Two analog engines
    would disagree about what "a day like today" is, and the card would be
    describing one market while the signals described another.

    Returns the rows of `spy` (with a `distance` column), not just dates.
    """
    spy = spy.copy()
    current_vector = spy.iloc[-1][ANALOG_FEATURES].values.astype(float)
    feature_mean = spy[ANALOG_FEATURES].mean()
    feature_std = spy[ANALOG_FEATURES].std().replace(0, 1)
    spy_norm = (spy[ANALOG_FEATURES] - feature_mean) / feature_std
    current_norm = ((pd.Series(dict(zip(ANALOG_FEATURES, current_vector)))
                     - feature_mean) / feature_std)
    spy["distance"] = np.linalg.norm(spy_norm.values - current_norm.values, axis=1)
    historical = spy.iloc[:-exclude_recent]
    return historical.nsmallest(n, "distance")


def analog_episode_ids(dates) -> dict:
    """date -> episode id, clustering analog days the way run_scan does.

    Adjacent analog days are one regime spell with overlapping forward windows,
    so a new episode starts only when the gap to the previous analog day exceeds
    EPISODE_GAP_CAL calendar days. Mirrors run_scan's ep_map exactly (sorted
    dates, strict >), which tests/test_regime_measures.py pins."""
    ordered = sorted(pd.to_datetime(list(dates)))
    out, eid = {}, 0
    for i, d in enumerate(ordered):
        if i and (d - ordered[i - 1]).days > EPISODE_GAP_CAL:
            eid += 1
        out[d] = eid
    return out


def analog_days_payload(analogs: pd.DataFrame, as_of) -> dict:
    """data/analog_days.json — today's analog days, published (2026-09-17).

    finvisible's book-level stress test runs a household's CURRENT positions
    forward from each past spell that looked like today. It needs the same days
    the signals are conditioned on, not a second implementation of "a day like
    today" that could quietly disagree — so the days are published from here.

    Each episode carries an `anchor`: its CLOSEST day to today by distance. A
    spell of eight adjacent analog days is one piece of evidence, and running a
    book forward from all eight would count it eight times."""
    a = analogs.copy()
    a["date"] = pd.to_datetime(a["date"])
    ep = analog_episode_ids(a["date"])
    a["episode"] = a["date"].map(ep)
    days = [{"date": d.strftime("%Y-%m-%d"), "distance": round(float(x), 4), "episode": int(e)}
            for d, x, e in sorted(zip(a["date"], a["distance"], a["episode"]))]
    episodes = []
    for eid, g in a.groupby("episode"):
        anchor = g.loc[g["distance"].idxmin()]
        episodes.append({
            "episode": int(eid),
            "first": g["date"].min().strftime("%Y-%m-%d"),
            "last": g["date"].max().strftime("%Y-%m-%d"),
            "n_days": int(len(g)),
            "anchor": anchor["date"].strftime("%Y-%m-%d"),
            "anchor_distance": round(float(anchor["distance"]), 4),
        })
    return {
        "as_of": pd.Timestamp(as_of).strftime("%Y-%m-%d"),
        "features": ANALOG_FEATURES,
        "episode_gap_days": EPISODE_GAP_CAL,
        "n_days": len(days),
        "n_episodes": len(episodes),
        "days": days,
        "episodes": sorted(episodes, key=lambda e: e["first"]),
        "note": ("The past SPY sessions closest to today on 5- and 20-day return, "
                 "20-day volatility and drawdown from the 60-day high — the same days "
                 "market_signals.csv is conditioned on. Episodes collapse adjacent "
                 "days; each episode's anchor is its closest day."),
    }


# ── REVERSAL ─────────────────────────────────────────────────────────────────

REVERSAL_HORIZON = 20
REVERSAL_MIN_ANALOGS = 20
EPISODE_GAP_CAL = 14   # the signal engine's own de-clustering gap


def _flip(trailing: float, forward: float) -> bool | None:
    """True if the next window went the other way. None if either is flat."""
    if trailing == 0 or forward == 0 or pd.isna(trailing) or pd.isna(forward):
        return None
    return (trailing > 0) != (forward > 0)


def reversal(spy: pd.DataFrame, analogs: pd.DataFrame,
             horizon: int = REVERSAL_HORIZON) -> dict:
    """How often SPY's next `horizon` sessions reversed its last 20.

    `spy` is SPY's feature frame (date, close, return_20), oldest first, one row
    per session. `analogs` is analog_days() output.

    Measured twice — on the analog days and on EVERY day — because a rate is
    only information against its base: "12 of 30 reversed" is alarming if any
    day reverses 20% of the time and reassuring if it reverses 55%.
    """
    spy = spy.reset_index(drop=True)
    fwd = spy["close"].shift(-horizon) / spy["close"] - 1
    flips_all = [_flip(t, f) for t, f in zip(spy["return_20"], fwd)]
    base = [x for x in flips_all if x is not None]

    by_date = dict(zip(pd.to_datetime(spy["date"]), flips_all))
    analog_dates = sorted(pd.to_datetime(analogs["date"]))
    flips = [(d, by_date.get(d)) for d in analog_dates]
    usable = [(d, x) for d, x in flips if x is not None]

    episodes = 0
    prev = None
    for d, _ in usable:
        if prev is None or (d - prev).days > EPISODE_GAP_CAL:
            episodes += 1
        prev = d

    out = {
        "horizon": horizon,
        "analogs": len(usable),
        "reversed": int(sum(x for _, x in usable)),
        "episodes": episodes,
        "base_days": len(base),
        "base_reversed": int(sum(base)),
        "base_rate": (round(sum(base) / len(base), 4) if base else None),
        "trailing_20d": (round(float(spy["return_20"].iloc[-1]), 5)
                         if len(spy) else None),
    }
    if len(usable) < REVERSAL_MIN_ANALOGS:
        out["value"] = None
        out["reason"] = f"only {len(usable)} analog days have a finished {horizon}-session window"
    else:
        out["value"] = round(out["reversed"] / len(usable), 4)
    return out


# ── ANALOG FORWARD RETURNS ───────────────────────────────────────────────────

ANALOG_FWD_HORIZON = 20
ANALOG_FWD_MIN = 20


def analog_forward(spy: pd.DataFrame, analogs: pd.DataFrame,
                   horizon: int = ANALOG_FWD_HORIZON) -> dict:
    """SPY's next `horizon` sessions after each analog day, p10..p90.

    Added 2026-09-24. The Analysis tab's distribution tile had been reading the
    medians of the top 30 stocks BY EDGE — a cross-section selected for being
    high, at mixed horizons — so it showed p50 +73% under a caption about
    analog days. This is the number the caption describes, with the same
    percentiles over every day as the base it has to be read against.
    """
    spy = spy.reset_index(drop=True)
    fwd = spy["close"].shift(-horizon) / spy["close"] - 1
    by_date = dict(zip(pd.to_datetime(spy["date"]), fwd))
    vals = [by_date.get(d) for d in pd.to_datetime(analogs["date"])]
    vals = np.array([v for v in vals if v is not None and pd.notna(v)], dtype=float)
    base = fwd.dropna().to_numpy(dtype=float)

    def pct(a):
        return {f"p{q}": round(float(np.percentile(a, q)), 4) for q in (10, 25, 50, 75, 90)}

    out = {"horizon": horizon, "analogs": int(len(vals)), "base_days": int(len(base)),
           "base": pct(base) if len(base) else None}
    if len(vals) < ANALOG_FWD_MIN:
        out["value"] = None
        out["reason"] = f"only {len(vals)} analog days have a finished {horizon}-session window"
    else:
        out["value"] = pct(vals)
    return out


# ── BREADTH ──────────────────────────────────────────────────────────────────

BREADTH_MA = 50
BREADTH_MIN_NAMES = 300
# The latest session is withheld if it measured fewer than this share of the
# names the last 30 sessions typically measured. A half-loaded day would read
# as a real move in breadth.
BREADTH_COMPLETE_SHARE = 0.8


def breadth_series(prices: pd.DataFrame, exclude=("SPY",)) -> pd.DataFrame:
    """Per session: share of names above their 50-day average, and how many counted.

    `prices` is the scan's wide close frame (dates x tickers). A name counts on a
    session only if it has a close that day and a full 50-session average.
    """
    px = prices.drop(columns=[c for c in exclude if c in prices.columns])
    ma = px.rolling(BREADTH_MA, min_periods=BREADTH_MA).mean()
    valid = px.notna() & ma.notna()
    above = (px > ma) & valid
    n = valid.sum(axis=1)
    share = above.sum(axis=1) / n.where(n > 0)
    return pd.DataFrame({"share": share, "n": n})


def summarize_breadth(bs: pd.DataFrame) -> dict:
    """Today's breadth with its 30/90-session range and 3-year percentile."""
    if bs is None or bs.empty:
        return {"value": None, "reason": "no price history"}
    ok = bs[bs["n"] >= BREADTH_MIN_NAMES].dropna(subset=["share"])
    last = bs.iloc[-1]
    typical = float(bs["n"].tail(30).median()) if len(bs) else 0.0
    out = {
        "ma": BREADTH_MA,
        "n": int(last["n"]),
        "n_typical": int(typical),
        "days": int(len(ok)),
    }
    if last["n"] < BREADTH_MIN_NAMES or pd.isna(last["share"]):
        out.update(value=None, reason=f"only {int(last['n'])} names measurable on the latest session")
        return out
    if typical and last["n"] < BREADTH_COMPLETE_SHARE * typical:
        out.update(value=None,
                   reason=(f"the latest session measured {int(last['n'])} names against a "
                           f"typical {int(typical)} — it had not finished loading"))
        return out

    today = float(last["share"])
    w30, w90 = ok["share"].tail(30), ok["share"].tail(90)
    out.update(
        value=round(today, 4),
        range30={"lo": round(float(w30.min()), 4), "hi": round(float(w30.max()), 4)},
        range90={"lo": round(float(w90.min()), 4), "hi": round(float(w90.max()), 4)},
        # Share of measured sessions at or below today. Inclusive, so today
        # never ranks below zero.
        pct_rank=round(float((ok["share"] <= today).mean()), 4),
        history=[round(float(x), 4) for x in ok["share"].tail(20)],
    )
    return out
