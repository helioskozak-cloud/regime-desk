"""The regime rules table, and the explainer that walks it.

2026-10-07 (owner, Q39 = a): the "Neutral" fallback was split into Elevated
Volatility, Calm Uptrend, Drifting Lower and Range. The old ladder stays below
as the reference, and the tests now prove the split touched NOTHING else: every
state the old ladder labelled anything but Neutral keeps that label, and every
old-Neutral state lands in exactly one of the four new ones.

The classifier was a ladder of if-statements until 2026-09-14, when it became a
table so the Regime Analysis card could explain its own label. That refactor is
only safe if it is EXACTLY the old ladder: the regime streak is computed by
re-classifying every past session, so a label that shifts on one edge case
silently rewrites history and resets the streak.

So the old functions are kept here, verbatim, as the reference, and the new
ones are checked against them over a grid that straddles every threshold.
"""
import itertools

import snapshot_builder as sb


# ── the reference: the pre-2026-09-14 functions, copied verbatim ─────────────

def _old_regime(spy):
    r20 = spy.get("ret_20d", 0)
    dd = spy.get("drawdown_60d", 0)
    vol = spy.get("vol_20d", 0.015)
    if vol > 0.025:
        return "High Volatility"
    if dd < -0.15:
        return "Deep Correction"
    if dd < -0.08 and r20 < 0:
        return "Correction"
    if dd < -0.05 and r20 > 0:
        return "Recovery"
    if r20 > 0.05:
        return "Bull Trend"
    if r20 < -0.05:
        return "Pullback"
    return "Neutral"


# Every threshold, plus a hair either side of it, plus exactly on it. Exactly-on
# is where a > that became a >= would hide.
EPS = 1e-6
R20 = sorted({x + d for x in (-0.05, -0.01, 0.0, 0.01, 0.05)
              for d in (-EPS, 0.0, EPS)} | {-0.3, 0.3})
DD = sorted({x + d for x in (-0.15, -0.08, -0.05)
             for d in (-EPS, 0.0, EPS)} | {0.0, -0.4})
VOL = sorted({x + d for x in (0.02, 0.025, 0.22 / 252 ** 0.5)
              for d in (-EPS, 0.0, EPS)} | {0.005, 0.015, 0.05})


def _grid():
    for r20, dd, vol in itertools.product(R20, DD, VOL):
        yield {"ret_20d": r20, "drawdown_60d": dd, "vol_20d": vol}


NEW_FROM_NEUTRAL = {"Elevated Volatility", "Calm Uptrend", "Drifting Lower", "Range"}


def _new_regime(spy):
    """The old ladder with only its fallback split, written out by hand."""
    old = _old_regime(spy)
    if old != "Neutral":
        return old
    r20 = spy.get("ret_20d", 0)
    vol = spy.get("vol_20d", 0.015)
    if vol > 0.22 / 252 ** 0.5:
        return "Elevated Volatility"
    if r20 > 0.01:
        return "Calm Uptrend"
    if r20 < -0.01:
        return "Drifting Lower"
    return "Range"


def test_only_the_old_neutral_states_are_relabelled():
    for s in _grid():
        old, new = _old_regime(s), sb._classify_regime(s)
        if old == "Neutral":
            assert new in NEW_FROM_NEUTRAL, (s, new)
        else:
            assert new == old, (s, old, new)


def test_the_table_matches_the_hand_written_split():
    mismatches = [s for s in _grid() if sb._classify_regime(s) != _new_regime(s)]
    assert not mismatches, f"{len(mismatches)} states differ, e.g. {mismatches[:3]}"


def test_missing_keys_default_exactly_as_before():
    """A history row missing a key must classify the same, or the streak moves."""
    for partial in ({}, {"ret_20d": -0.06}, {"vol_20d": 0.03},
                    {"drawdown_60d": -0.09, "ret_20d": -0.01}):
        assert sb._classify_regime(partial) == _new_regime(partial), partial


def test_the_grid_actually_reaches_every_label():
    """Without this the equivalence test could pass by never visiting a branch."""
    seen = {sb._classify_regime(s) for s in _grid()}
    assert seen == {label for label, _ in sb.REGIME_RULES} | {sb.REGIME_FALLBACK}


# ── the explainer ────────────────────────────────────────────────────────────

def test_the_fired_rule_is_the_published_label():
    for s in _grid():
        e = sb._explain_rules(s, sb.REGIME_RULES, sb.REGIME_FALLBACK)
        fired = [r["result"] for r in e["rules"] if r["fired"]]
        label = sb._classify_regime(s)
        if label == sb.REGIME_FALLBACK:
            assert fired == [] and e["fell_through"], s
        else:
            assert fired == [label] and not e["fell_through"], s


def test_at_most_one_rule_fires():
    for s in _grid():
        e = sb._explain_rules(s, sb.REGIME_RULES, sb.REGIME_FALLBACK)
        assert sum(r["fired"] for r in e["rules"]) <= 1, s


def test_a_matching_rule_below_the_winner_is_shown_as_shadowed():
    """Vol 3%/day AND a 20% drawdown: High Volatility wins, Deep Correction is
    true as well and sits underneath. That is the label waiting if vol calms,
    and hiding it would make the card look more certain than the rules are."""
    s = {"ret_20d": -0.02, "drawdown_60d": -0.20, "vol_20d": 0.03}
    e = sb._explain_rules(s, sb.REGIME_RULES, sb.REGIME_FALLBACK)
    by = {r["result"]: r for r in e["rules"]}
    assert by["High Volatility"]["fired"]
    assert by["Deep Correction"]["shadowed"]
    assert not by["Deep Correction"]["fired"]


def test_each_condition_reports_the_value_it_was_tested_on():
    s = {"ret_20d": -0.0226, "drawdown_60d": -0.0245, "vol_20d": 0.0057}
    e = sb._explain_rules(s, sb.REGIME_RULES, sb.REGIME_FALLBACK)
    pull = next(r for r in e["rules"] if r["result"] == "Pullback")
    (c,) = pull["conditions"]
    assert c["key"] == "ret_20d" and c["value"] == -0.0226
    assert c["threshold"] == -0.05 and c["met"] is False


def test_an_unknown_operator_is_loud():
    try:
        sb._holds(1.0, ">=", 0.5)
    except ValueError:
        return
    raise AssertionError("an unrecognised operator must raise, not evaluate False")
