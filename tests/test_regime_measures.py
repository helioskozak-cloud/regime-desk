"""Breadth, Persistence and Reversal: the Regime card's three measured tiles.

Until 2026-09-14 two of these were a hardcoded 0.5 and the third a four-step
lookup shown as a percentage. The assertions below are about the specific ways
a replacement measurement goes quietly wrong: a partial session read as a real
move, a common label read as a sticky one, overlapping days read as independent
evidence, a flat window read as a reversal, and a not-measured value read as a
middling one.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scan"))
import regime_measures as rm  # noqa: E402


# ── breadth ─────────────────────────────────────────────────────────────────

def _prices(n_names=400, n_days=400, seed=0, up_names=None):
    """Synthetic closes. `up_names` of them trend up at the end, the rest down."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2024-01-01", periods=n_days)
    data = {}
    for i in range(n_names):
        walk = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n_days)))
        data[f"T{i}"] = walk
    df = pd.DataFrame(data, index=idx)
    if up_names is not None:
        # Last 30 sessions: first `up_names` columns rise 1%/day, the rest fall.
        tail = np.arange(1, 31)
        for i, c in enumerate(df.columns):
            base = df[c].iloc[-31]
            step = 1.01 if i < up_names else 0.99
            df.iloc[-30:, df.columns.get_loc(c)] = base * step ** tail
    return df


def test_breadth_counts_names_above_their_own_50_day_average():
    px = _prices(up_names=300)  # 300 of 400 rising hard into the last session
    b = rm.summarize_breadth(rm.breadth_series(px))
    assert b["value"] == pytest.approx(0.75, abs=0.001)
    assert b["n"] == 400


def test_spy_is_not_counted_in_its_own_breadth():
    px = _prices(up_names=300)
    px["SPY"] = px.iloc[:, 0]
    assert rm.breadth_series(px)["n"].iloc[-1] == 400


def test_a_name_without_50_sessions_of_history_is_not_counted():
    px = _prices(up_names=300)
    px.iloc[:-20, 0] = np.nan  # an IPO 20 sessions ago
    assert rm.breadth_series(px)["n"].iloc[-1] == 399


def test_too_few_names_is_not_measured_rather_than_a_number():
    px = _prices(n_names=rm.BREADTH_MIN_NAMES - 1, up_names=100)
    b = rm.summarize_breadth(rm.breadth_series(px))
    assert b["value"] is None and "names" in b["reason"]


def test_a_half_loaded_last_session_is_withheld_not_read_as_a_move():
    """The day's closes arrive ticker by ticker. A snapshot taken mid-load would
    measure breadth on whichever names happened to be in, and print it as the
    market's."""
    px = _prices(n_names=800, up_names=400)
    px.iloc[-1, 400:] = np.nan  # half the universe has no close yet
    b = rm.summarize_breadth(rm.breadth_series(px))
    assert b["value"] is None
    assert "had not finished loading" in b["reason"]


def test_ranges_and_percentile_are_on_measured_sessions_only():
    px = _prices(up_names=300)
    b = rm.summarize_breadth(rm.breadth_series(px))
    assert b["range30"]["lo"] <= b["value"] <= b["range30"]["hi"]
    assert b["range90"]["lo"] <= b["range30"]["lo"]
    assert 0 < b["pct_rank"] <= 1
    # The first 49 sessions have no 50-day average and must not be ranked.
    assert b["days"] == 400 - (rm.BREADTH_MA - 1)


def test_percentile_is_inclusive_so_the_highest_day_ranks_at_the_top():
    px = _prices(up_names=400)  # every name rising: today is the broadest day
    b = rm.summarize_breadth(rm.breadth_series(px))
    assert b["value"] == 1.0 and b["pct_rank"] == 1.0


# ── persistence ─────────────────────────────────────────────────────────────

def _labels(seq):
    return pd.Series(list(seq))


def test_persistence_counts_sessions_still_labelled_the_same_later():
    # 60 A, then 30 B, then 60 A. Today is A.
    labs = _labels("A" * 60 + "B" * 30 + "A" * 60)
    p = rm.persistence(labs, horizon=20)
    # A at i with i+20 in range: indices 0..59 (i+20 = 20..79) and 90..129.
    # Held when labs[i+20] == A: 0..39 (->20..59) and 90..129 (->110..149) = 40+40.
    assert p["days"] == 100
    assert p["held"] == 80
    assert p["value"] is None  # only 2 spells: withheld, below the minimum
    assert "2 spells" in p["reason"]


def test_a_rate_resting_on_few_spells_is_withheld_even_with_many_days():
    """Two long spells are nearer two observations than hundreds of days."""
    labs = _labels("A" * 300 + "B" * 50 + "A" * 300)
    p = rm.persistence(labs)
    assert p["days"] >= rm.PERSIST_MIN_DAYS
    assert p["spells"] == 2 and p["value"] is None


def test_persistence_carries_the_base_rate_a_common_label_gets_for_free():
    """If a label covers most sessions, a day with it keeps it for no reason
    beyond how common it is. The base rate is what the rate must beat."""
    rng = np.random.default_rng(1)
    labs = _labels(rng.choice(["A", "B"], size=2000, p=[0.8, 0.2]))
    labs.iloc[-1] = "A"
    p = rm.persistence(labs)
    assert p["value"] is not None
    # Independent draws: A twenty sessions on is ~80% whatever today is.
    assert p["base_rate"] == pytest.approx(0.8, abs=0.03)
    assert abs(p["value"] - p["base_rate"]) < 0.05


def test_the_running_spell_is_excluded_from_the_typical_spell_length():
    # Finished A spells: 5 and 7, median 6. With the running 100-session spell
    # wrongly included the median becomes 7. (An earlier fixture used three
    # equal spells, where both come out 5 — and the mutation survived.)
    labs = _labels("A" * 5 + "B" + "A" * 7 + "B" + "A" * 100)
    p = rm.persistence(labs, horizon=3)
    assert p["median_spell"] == 6.0  # not dragged toward the 100 still running
    assert p["streak"] == 100


def test_streak_counts_the_whole_history_not_a_20_session_window():
    """The builder used to count from the last 20 rows, so every regime older
    than 20 sessions was published as a 20-day streak."""
    assert rm.regime_streak(_labels("B" + "A" * 57)) == 57
    assert rm.regime_streak(_labels([])) is None


# ── reversal ────────────────────────────────────────────────────────────────

def _spy_frame(closes, start="2023-01-02"):
    closes = pd.Series(closes, dtype=float)
    return pd.DataFrame({
        "date": pd.bdate_range(start, periods=len(closes)),
        "close": closes.values,
        "return_20": closes.pct_change(20).values,
    }).dropna().reset_index(drop=True)


def test_a_flip_is_the_next_window_going_the_other_way():
    assert rm._flip(-0.02, 0.01) is True
    assert rm._flip(0.03, 0.01) is False
    assert rm._flip(0.0, 0.01) is None    # no trend to reverse
    assert rm._flip(-0.02, 0.0) is None   # no move to call a reversal
    assert rm._flip(float("nan"), 0.01) is None


def test_reversal_counts_on_the_analog_days_and_on_every_day():
    # A zigzag: 20 sessions up, 20 down, repeated. Every full window reverses.
    closes = []
    level = 100.0
    for k in range(40):  # 40 legs -> 38 turning points with a finished window
        for _ in range(20):
            level *= 1.005 if k % 2 == 0 else 0.995
            closes.append(level)
    spy = _spy_frame(closes)
    # Take 30 analog days that are all exactly at a turn.
    turns = spy.iloc[[i for i in range(0, len(spy) - 20) if (i + 20) % 20 == 0][:30]]
    r = rm.reversal(spy, turns)
    assert r["analogs"] == 30 and r["reversed"] == 30 and r["value"] == 1.0
    assert r["base_rate"] is not None and r["base_days"] > r["analogs"]


def test_analog_days_without_a_finished_forward_window_are_not_counted():
    closes = list(100 * np.exp(np.cumsum(np.random.default_rng(3).normal(0, 0.01, 300))))
    spy = _spy_frame(closes)
    recent = spy.tail(30)  # the last 30 sessions have no 20-session future yet
    r = rm.reversal(spy, recent)
    assert r["analogs"] == 10          # only the first 10 of them do
    assert r["value"] is None          # below REVERSAL_MIN_ANALOGS
    assert "finished" in r["reason"]


def test_adjacent_analog_days_collapse_into_one_episode():
    """Neighbouring analog days share most of their forward window. Counting
    them as separate evidence would overstate how sure the rate is."""
    closes = list(100 * np.exp(np.cumsum(np.random.default_rng(4).normal(0, 0.01, 600))))
    spy = _spy_frame(closes)
    cluster_a = spy.iloc[100:115]
    cluster_b = spy.iloc[300:315]
    r = rm.reversal(spy, pd.concat([cluster_a, cluster_b]))
    assert r["analogs"] == 30 and r["episodes"] == 2


# ── analog days: moved verbatim out of run_scan, and must stay identical ────

def _old_inline_analogs(spy, SIMILAR_DAY_COUNT, EXCLUDE_RECENT_DAYS):
    """The block as it stood in ci_scan.run_scan before 2026-09-14, verbatim."""
    spy = spy.copy()
    today = spy.iloc[-1]
    current_vector = today[["return_5", "return_20", "volatility", "drawdown"]].values.astype(float)
    FEATURES = ["return_5", "return_20", "volatility", "drawdown"]
    feature_mean = spy[FEATURES].mean()
    feature_std  = spy[FEATURES].std().replace(0, 1)
    spy_norm     = (spy[FEATURES] - feature_mean) / feature_std
    current_norm = (pd.Series(dict(zip(FEATURES, current_vector))) - feature_mean) / feature_std
    spy["distance"] = np.linalg.norm(spy_norm.values - current_norm.values, axis=1)
    historical = spy.iloc[:-EXCLUDE_RECENT_DAYS]
    return historical.nsmallest(SIMILAR_DAY_COUNT, "distance")


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_analog_days_are_exactly_the_days_run_scan_used_to_pick(seed):
    """The stock signals are conditioned on these days. If the move changed a
    single one, every published edge would change with it."""
    rng = np.random.default_rng(seed)
    n = 700
    closes = pd.Series(100 * np.exp(np.cumsum(rng.normal(0.0003, 0.011, n))))
    ret = closes.pct_change()
    spy = pd.DataFrame({
        "date": pd.bdate_range("2023-01-02", periods=n),
        "close": closes,
        "return_5": closes.pct_change(5),
        "return_20": closes.pct_change(20),
        "volatility": ret.rolling(20).std(),
        "drawdown": closes / closes.rolling(60, min_periods=1).max() - 1,
    }).dropna().reset_index(drop=True)
    old = _old_inline_analogs(spy, 30, 30)
    new = rm.analog_days(spy, 30, 30)
    assert list(old["date"]) == list(new["date"])
    assert np.allclose(old["distance"].values, new["distance"].values)
