"""The regime rules table, and the explainer that walks it.

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


def _old_reversal(spy):
    vol = spy.get("vol_20d", 0.015)
    r20 = spy.get("ret_20d", 0)
    if vol > 0.025 and r20 < 0:
        return 0.7
    if vol > 0.02:
        return 0.5
    if abs(r20) < 0.01:
        return 0.35
    return 0.25


# Every threshold, plus a hair either side of it, plus exactly on it. Exactly-on
# is where a > that became a >= would hide.
EPS = 1e-6
R20 = sorted({x + d for x in (-0.05, -0.01, 0.0, 0.01, 0.05)
              for d in (-EPS, 0.0, EPS)} | {-0.3, 0.3})
DD = sorted({x + d for x in (-0.15, -0.08, -0.05)
             for d in (-EPS, 0.0, EPS)} | {0.0, -0.4})
VOL = sorted({x + d for x in (0.02, 0.025)
              for d in (-EPS, 0.0, EPS)} | {0.005, 0.015, 0.05})


def _grid():
    for r20, dd, vol in itertools.product(R20, DD, VOL):
        yield {"ret_20d": r20, "drawdown_60d": dd, "vol_20d": vol}


def test_the_table_labels_every_state_exactly_as_the_old_ladder():
    mismatches = [s for s in _grid() if sb._classify_regime(s) != _old_regime(s)]
    assert not mismatches, f"{len(mismatches)} states relabelled, e.g. {mismatches[:3]}"


def test_reversal_risk_is_unchanged_on_every_state():
    mismatches = [s for s in _grid()
                  if sb._classify_reversal_risk(s) != _old_reversal(s)]
    assert not mismatches, f"{len(mismatches)} states changed, e.g. {mismatches[:3]}"


def test_missing_keys_default_exactly_as_before():
    """A history row missing a key must classify the same, or the streak moves."""
    for partial in ({}, {"ret_20d": -0.06}, {"vol_20d": 0.03},
                    {"drawdown_60d": -0.09, "ret_20d": -0.01}):
        assert sb._classify_regime(partial) == _old_regime(partial), partial
        assert sb._classify_reversal_risk(partial) == _old_reversal(partial), partial


def test_the_grid_actually_reaches_every_label():
    """Without this the equivalence test could pass by never visiting a branch."""
    seen = {sb._classify_regime(s) for s in _grid()}
    assert seen == {label for label, _ in sb.REGIME_RULES} | {sb.REGIME_FALLBACK}
    seen_rr = {sb._classify_reversal_risk(s) for s in _grid()}
    assert seen_rr == {v for v, _ in sb.REVERSAL_RULES} | {sb.REVERSAL_FALLBACK}


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
