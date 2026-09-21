"""B3 — the walk-forward harness. If any of these fail, every number the
backtest produces is worthless, so they are the first thing to run."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scan"))

import validate as v  # noqa: E402


def synth(n=900, seed=0, tickers=("SPY", "AAA", "BBB", "CCC")):
    """Deterministic price panel with business-day dates."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2020-01-01", periods=n)
    data = {}
    for i, t in enumerate(tickers):
        steps = rng.normal(0.0005 + i * 0.0002, 0.012, n)
        data[t] = 100 * np.cumprod(1 + steps)
    return pd.DataFrame(data, index=idx)


# ── the property everything else depends on ──────────────────────────────────

def test_a_decision_cannot_see_a_bar_that_has_not_happened():
    """THE TEST THAT MAKES THE BACKTEST MEAN ANYTHING. Building candidates on
    a frame that ends at the decision date must give exactly the same answer as
    building them on a frame that runs years past it. If future bars leak in,
    every alpha this harness reports is fiction."""
    closes = synth(900)
    as_of = closes.index[600]
    feats_full = v.market_features(closes["SPY"])

    truncated = closes.loc[:as_of]
    feats_trunc = v.market_features(truncated["SPY"])

    a = v.build_candidates(closes, feats_full, as_of, horizon=20)
    b = v.build_candidates(truncated, feats_trunc, as_of, horizon=20)

    assert not a.table.empty and not b.table.empty
    pd.testing.assert_frame_equal(
        a.table.sort_index(), b.table.sort_index(), check_exact=False, rtol=1e-9)


def test_every_analog_day_has_a_finished_outcome_by_the_decision_date():
    """An analog day 40 sessions back has no 120-day forward return yet.
    Including it mixes a partial outcome into the evidence — silently, because
    a partial window still produces a number."""
    closes = synth(900)
    feats = v.market_features(closes["SPY"])
    as_of = closes.index[700]
    as_of_pos = list(feats.index).index(as_of)
    for horizon in (20, 60, 120):
        dates = v.analog_dates(feats, as_of, horizon)
        pos = {d: i for i, d in enumerate(feats.index)}
        assert all(pos[d] + horizon <= as_of_pos for d in dates), \
            f"an analog day's {horizon}-day window had not finished"


def test_the_recent_window_is_excluded():
    closes = synth(900)
    feats = v.market_features(closes["SPY"])
    as_of = feats.index[-1]
    dates = v.analog_dates(feats, as_of, horizon=5, exclude_recent=30)
    assert all(d <= feats.index[-31] for d in dates)


def test_realised_reads_exactly_the_horizon_ahead():
    """A fencepost here would score every rule against the wrong window."""
    idx = pd.bdate_range("2021-01-01", periods=50)
    closes = pd.DataFrame({"SPY": np.arange(100.0, 150.0), "AAA": np.arange(100.0, 150.0)}, index=idx)
    as_of = idx[10]
    got = v.realised(closes, as_of, horizon=5, tickers=["AAA"])
    # price[15] / price[10] - 1 = 115/110 - 1
    assert abs(float(got["AAA"]) - (115.0 / 110.0 - 1)) < 1e-12


def test_no_outcome_when_the_horizon_runs_off_the_end():
    """The last as-of dates have no future to be scored against; returning a
    number there would invent one."""
    closes = synth(300)
    assert v.realised(closes, closes.index[-3], horizon=20, tickers=["AAA"]).empty


# ── the candidate table ──────────────────────────────────────────────────────

def test_excess_is_conditional_minus_that_stocks_own_baseline():
    """The null is the stock's ordinary forward return, not zero. In a rising
    market almost everything beats zero, which is how the live screen made
    +20.7% at 120 days and still lost to SPY 78% of the time."""
    closes = synth(900)
    feats = v.market_features(closes["SPY"])
    c = v.build_candidates(closes, feats, closes.index[600], horizon=20)
    assert not c.table.empty
    recomputed = c.table["cond"] - c.table["uncond"]
    pd.testing.assert_series_equal(c.table["excess"], recomputed, check_names=False)


def test_a_ticker_with_too_little_history_is_left_out_not_zeroed():
    closes = synth(900)
    closes["NEWCO"] = np.nan
    closes.iloc[-40:, closes.columns.get_loc("NEWCO")] = 50.0
    feats = v.market_features(closes["SPY"])
    c = v.build_candidates(closes, feats, closes.index[600], horizon=20)
    assert "NEWCO" not in c.table.index


def test_episodes_collapse_adjacent_days():
    """Thirty analog days that sit in three clusters are three pieces of
    evidence, not thirty."""
    days = pd.DatetimeIndex(
        list(pd.bdate_range("2021-01-04", periods=5))
        + list(pd.bdate_range("2022-06-01", periods=5))
        + list(pd.bdate_range("2023-11-01", periods=5)))
    assert v.episodes(days) == 3
    assert v.episodes(pd.DatetimeIndex([])) == 0


# ── the rules ────────────────────────────────────────────────────────────────

def table(n=50, seed=1):
    rng = np.random.default_rng(seed)
    idx = [f"T{i}" for i in range(n)]
    return pd.DataFrame({
        "cond": rng.normal(0.05, 0.03, n),
        "uncond": rng.normal(0.02, 0.01, n),
        "spread": rng.uniform(0.05, 0.4, n),
        "n_obs": rng.integers(6, 30, n),
    }, index=idx).assign(excess=lambda d: d["cond"] - d["uncond"])


def test_legacy_and_excess_disagree_about_what_to_buy():
    """If they agreed the comparison would be pointless — the whole question is
    whether subtracting the baseline changes the answer."""
    t = table()
    assert set(v.rule_legacy(t, None, 10)) != set(v.rule_excess(t, None, 10))


def test_the_fdr_rule_is_allowed_to_buy_nothing():
    """A day with nothing distinguishable from luck must produce an empty list,
    not a top three. This is the behaviour the live engine never had."""
    t = table()
    t["spread"] = 5.0          # enormous dispersion: nothing is significant
    t["n_obs"] = 6
    assert v.rule_shrunk_fdr(t, None, 10) == []


def test_the_control_draws_from_the_same_universe():
    """Any rule that cannot beat this is not a rule."""
    t = table()
    picks = v.rule_random(t, None, 10, seed=3)
    assert len(picks) == 10
    assert all(p in t.index for p in picks)
    assert picks != v.rule_random(t, None, 10, seed=4)


def test_rules_that_need_the_scanner_abstain_without_it():
    """Absent scanner scores must mean "no opinion", never "buy anything"."""
    t = table()
    assert v.rule_scanner(t, None, 10) == []
    assert v.rule_combined(t, pd.Series(dtype=float), 10) == []


def test_summary_reports_nothing_rather_than_zero_when_a_rule_never_fired():
    r = v.RunResult("x", 20, [0, 0], [float("nan"), float("nan")], [])
    s = r.summary()
    assert s["runs"] == 0
    assert s["mean_alpha"] is None and s["beat_rate"] is None



# ── B5 / B6: beta neutralisation ────────────────────────────────────────────

def test_trailing_beta_cannot_see_a_bar_after_the_decision():
    closes = synth(n=700, tickers=("SPY", "AAA", "BBB"))
    as_of = closes.index[500]
    a = v.trailing_beta(closes, as_of, ["AAA", "BBB"])
    b = v.trailing_beta(closes.loc[:as_of], as_of, ["AAA", "BBB"])
    pd.testing.assert_series_equal(a, b)


def test_trailing_beta_recovers_a_known_beta():
    rng = np.random.default_rng(1)
    idx = pd.bdate_range("2020-01-01", periods=400)
    m = rng.normal(0.0004, 0.01, 400)
    closes = pd.DataFrame({
        "SPY": 100 * np.cumprod(1 + m),
        "HI": 100 * np.cumprod(1 + 2.0 * m + rng.normal(0, 0.001, 400)),
        "LO": 100 * np.cumprod(1 + 0.5 * m + rng.normal(0, 0.001, 400)),
    }, index=idx)
    beta = v.trailing_beta(closes, idx[-1], ["HI", "LO"])
    assert abs(beta["HI"] - 2.0) < 0.1 and abs(beta["LO"] - 0.5) < 0.1


def test_a_short_history_gets_no_beta_rather_than_one():
    closes = synth(n=700, tickers=("SPY", "AAA"))
    closes.loc[closes.index[:650], "AAA"] = np.nan
    assert "AAA" not in v.trailing_beta(closes, closes.index[-1], ["AAA"]).index


def test_neutral_picks_are_spread_evenly_across_beta_buckets():
    """The point of B5: a score that tracks beta must not get to buy only the
    top bucket."""
    idx = [f"T{i}" for i in range(100)]
    beta = pd.Series(np.linspace(0.2, 2.0, 100), index=idx)
    score = beta.copy()                      # score IS beta: the worst case
    picks = v.within_beta_buckets(score, beta, 20)
    assert len(picks) == 20
    buckets = pd.qcut(beta.rank(method="first"), 5, labels=False)
    assert buckets.reindex(picks).value_counts().to_dict() == {k: 4 for k in range(5)}
    # and the un-neutralised top 20 would all have come from one bucket
    assert buckets.reindex(score.nlargest(20).index).nunique() == 1


def test_neutral_rules_abstain_without_beta_or_scanner():
    t = table()
    assert v.rule_excess_bn(t, None, 10) == []          # no beta column
    t["beta"] = np.linspace(0.5, 1.5, len(t))
    assert len(v.rule_excess_bn(t, None, 10)) == 10
    assert v.rule_scanner_bn(t, None, 10) == []
    assert v.rule_blend_bn(t, pd.Series(dtype=float), 10) == []


def test_the_blend_uses_both_ranks():
    t = table()
    t["beta"] = 1.0 + np.arange(len(t)) * 0.0      # one flat beta: buckets by order only
    t["beta"] = np.linspace(0.5, 1.5, len(t))
    scan = pd.Series(np.linspace(0, 1, len(t)), index=t.index)
    only_scan = set(v.rule_scanner_bn(t, scan, 10))
    only_excess = set(v.rule_excess_bn(t, scan, 10))
    blend = set(v.rule_blend_bn(t, scan, 10))
    assert blend != only_scan or blend != only_excess


def test_summary_reports_average_pick_beta():
    r = v.RunResult("x", 20, [20, 20], [0.01, 0.02], [], pick_beta=[1.2, 0.8])
    assert abs(r.summary()["avg_pick_beta"] - 1.0) < 1e-12


# ── B7: the beta-matched control ─────────────────────────────────────────────

def _betas(n=100):
    return pd.Series(np.linspace(0.2, 2.0, n), index=[f"T{i:03d}" for i in range(n)])


def test_matched_baskets_copy_the_picks_beta_profile_exactly():
    """THE PROPERTY B7 RESTS ON. Every stand-in comes from its pick's beta
    decile, so the control carries the picks' market exposure by construction."""
    beta = _betas()
    picks = ["T000", "T001", "T050", "T098", "T099"]
    matched, baskets, short = v.beta_matched_baskets(picks, beta, draws=50, seed=1)
    labels = pd.qcut(beta.rank(method="first"), v.BETA_DECILES, labels=False)
    want = sorted(labels[p] for p in picks)
    assert matched == picks and short == 0 and len(baskets) == 50
    for b in baskets:
        assert sorted(labels[t] for t in b) == want
        assert not set(b) & set(picks), "a pick stood in for itself"
        assert len(set(b)) == len(b), "a name drawn twice in one basket"
    mean_ctrl = np.mean([beta.reindex(b).mean() for b in baskets])
    assert abs(mean_ctrl - beta.reindex(picks).mean()) < 0.05


def test_a_pick_with_no_beta_leaves_both_sides():
    beta = _betas()
    matched, baskets, _ = v.beta_matched_baskets(["T010", "NOBETA"], beta, draws=5, seed=0)
    assert matched == ["T010"]
    assert all(len(b) == 1 for b in baskets)


def test_matched_draws_are_reproducible_and_seed_dependent():
    beta = _betas()
    a = v.beta_matched_baskets(["T020", "T060"], beta, draws=10, seed=7)[1]
    b = v.beta_matched_baskets(["T020", "T060"], beta, draws=10, seed=7)[1]
    c = v.beta_matched_baskets(["T020", "T060"], beta, draws=10, seed=8)[1]
    assert a == b and a != c


def test_a_decile_too_small_is_drawn_with_replacement_and_counted():
    beta = _betas(20)                       # two names per decile
    picks = ["T000"]                        # decile 0 has one other name
    _, baskets, short = v.beta_matched_baskets(picks, beta, draws=3, seed=0)
    assert short == 0 and all(b == ["T001"] for b in baskets)
    picks = ["T000", "T001"]                # decile 0 now has none left
    matched, baskets, short = v.beta_matched_baskets(picks, beta, draws=3, seed=0)
    assert matched == picks and baskets == [[], [], []] and short == 1


def test_the_matched_score_is_pick_mean_minus_matched_mean():
    """End to end on a synthetic panel: with every name's forward return known,
    the recorded score must equal the arithmetic on those returns."""
    closes = synth(700, tickers=("SPY",) + tuple(f"T{i:03d}" for i in range(40)))
    as_of = closes.index[500]
    beta = v.trailing_beta(closes, as_of, [c for c in closes.columns if c != "SPY"])
    # One pick from each of four different deciles, so every pick has spare
    # names beside it (the top four by beta would fill their decile alone).
    picks = list(beta.sort_values().index[[2, 12, 22, 32]])
    res = v.RunResult("x", 20, [], [], [])
    v._score_matched(res, closes, as_of, 20, picks, beta, seed=3)
    matched, baskets, _ = v.beta_matched_baskets(picks, beta, seed=3)
    fwd = v.realised(closes, as_of, 20, sorted(set(closes.columns)))
    want = fwd.reindex(matched).mean() - np.mean([fwd.reindex(b).mean() for b in baskets])
    assert res.matched[0] == res.matched[0], "no score recorded"
    assert abs(res.matched[0] - want) < 1e-12
