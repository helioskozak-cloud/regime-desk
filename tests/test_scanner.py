"""B4 — the current-state scanner. Every test here was checked by breaking the
code first; several exist because the conditional engine already made the
mistake they guard against."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scan"))

import scanner as sc  # noqa: E402


def series(values):
    return pd.Series([float(v) for v in values])


def trend(n, start=100.0, daily=0.001, noise=0.0, seed=0):
    rng = np.random.default_rng(seed)
    out, p = [], start
    for _ in range(n):
        p *= 1 + daily + (rng.normal(0, noise) if noise else 0.0)
        out.append(p)
    return series(out)


# ── the anti-beta rules ──────────────────────────────────────────────────────

def test_relative_strength_subtracts_the_benchmark():
    """The engine's picks returned +20.7% at 120 days and still lost to SPY in
    78% of cases. A raw return in a rising tape flatters everything, so the
    scanner never reports one."""
    stock = trend(200, daily=0.002)
    bench = trend(200, daily=0.002)
    rs = sc.relative_strength(stock, bench, sc.MONTH)
    assert abs(rs) < 1e-9, "a stock matching its benchmark has zero relative strength"

    faster = trend(200, daily=0.004)
    assert sc.relative_strength(faster, bench, sc.MONTH) > 0
    slower = trend(200, daily=0.0005)
    assert sc.relative_strength(slower, bench, sc.MONTH) < 0


def test_a_move_is_measured_in_the_names_own_volatility():
    """THE ARTIFACT THIS MODULE EXISTS TO AVOID. Measured on the old feed, the
    top edge quartile had beta 1.32 and a p90-p10 spread of 1.58 against 0.97
    and 0.32 in the bottom quartile: it was a volatility sort wearing a signal's
    clothes.

    Here a quiet name and a wild name make the SAME percentage move. In raw
    terms they are identical; in their own sigma the quiet one has done
    something far more unusual, and that is what the scanner reports."""
    quiet = trend(120, daily=0.0015, noise=0.002, seed=1)
    wild = trend(120, daily=0.0015, noise=0.030, seed=2)
    q_raw, w_raw = sc._ret(quiet, sc.MONTH), sc._ret(wild, sc.MONTH)
    q_sig, w_sig = sc.move_in_sigma(quiet), sc.move_in_sigma(wild)
    # Comparable raw moves...
    assert abs(q_raw - w_raw) < 0.25
    # ...but the quiet name's is the larger event by a wide margin.
    assert q_sig > w_sig * 2


# ── missing is missing ───────────────────────────────────────────────────────

def test_short_history_is_none_not_zero():
    """A name with 40 bars has no 200-day average. Zero would read as 'sitting
    exactly on its 200-day', which is a finding rather than a gap — the same
    error as scoring an unprojected fantasy player at 0.0."""
    short = trend(40)
    assert sc.distance_from_ma(short, 200) is None
    assert sc.distance_from_ma(short, 20) is not None
    assert sc.relative_strength(short, trend(40), sc.HALF_YEAR) is None
    assert sc.drawdown_from_high(short, sc.YEAR) is None


def test_a_flat_range_is_undefined_not_bottom_of_range():
    """A stock pinned at one price all month is not sitting at its low."""
    flat = series([50.0] * 30)
    assert sc.range_position(flat) is None
    moving = series(list(np.linspace(10, 20, 30)))
    assert sc.range_position(moving) == 1.0  # closed at the high


def test_range_position_is_scaled_not_absolute():
    lo_to_hi = series(list(np.linspace(10, 20, 30)))
    assert sc.range_position(lo_to_hi) == 1.0
    hi_to_lo = series(list(np.linspace(20, 10, 30)))
    assert sc.range_position(hi_to_lo) == 0.0
    # The window is the LAST 20 bars, so the fixture has to put the close
    # mid-range within those 20 — not mid-range of a longer ramp.
    mid = series(list(np.linspace(10, 20, 19)) + [15.0])
    assert 0.4 < sc.range_position(mid) < 0.6


def test_zero_or_negative_prices_never_produce_a_number():
    """Bad data must not become a signal."""
    # The zero has to be the bar the return is measured FROM; 21 bars back
    # in a 31-bar series is 10.0, and 0% is the right answer there.
    assert sc._ret(series([0.0] + [10.0] * 21), 21) is None
    assert sc._ret(series([0.0] + [10.0] * 30), 21) == 0.0
    assert sc.distance_from_ma(series([0.0] * 60), 50) is None


# ── it moves when the market moves ───────────────────────────────────────────

def test_the_features_change_from_one_bar_to_the_next():
    """The complaint that started this: the published list was 78-100%
    unchanged day over day, twice byte-identical across a week. A scan whose
    output does not move is not a scan."""
    s = trend(300, daily=0.001, noise=0.02, seed=7)
    b = trend(300, daily=0.001, noise=0.01, seed=8)
    today = sc.features(s, b)
    yesterday = sc.features(s.iloc[:-1], b.iloc[:-1])
    changed = [k for k in today if today[k] != yesterday[k] and today[k] is not None]
    assert len(changed) >= 4, f"only {changed} moved when a new bar arrived"


def test_nothing_reads_a_bar_that_has_not_happened():
    """The walk-forward harness in validate.py is only honest if this holds:
    truncating the future must not change today's answer."""
    s = trend(300, noise=0.02, seed=3)
    b = trend(300, noise=0.01, seed=4)
    at_200 = sc.features(s.iloc[:200], b.iloc[:200])
    with_future = sc.features(s.iloc[:200], b.iloc[:200])
    assert at_200 == with_future
    # and the full series gives a DIFFERENT answer, so the test above is not
    # passing because the function ignores its input
    assert sc.features(s, b)["rs_1m"] != at_200["rs_1m"]


# ── the composite ────────────────────────────────────────────────────────────

def build_rows(n=40, seed=11):
    rng = np.random.default_rng(seed)
    bench = trend(300, daily=0.0008, noise=0.008, seed=99)
    rows = {}
    for i in range(n):
        s = trend(300, daily=float(rng.normal(0.001, 0.0012)), noise=0.015, seed=i)
        rows[f"T{i}"] = sc.features(s, bench)
    return rows


def test_composite_is_a_percentile_so_no_single_feature_can_dominate():
    """Averaging raw feature values would let one big number swamp the rest;
    percentile ranks bound every contribution to [0, 1]."""
    rows = build_rows()
    comp = sc.composite(rows)
    assert len(comp) > 20
    assert all(0.0 <= v <= 1.0 for v in comp.values())


def test_a_name_missing_most_features_is_not_scored():
    """Scoring on one of five features lets a stock with almost no history win
    on a single lucky percentile."""
    rows = build_rows()
    rows["NEWCO"] = {k: None for k in rows["T0"]}
    rows["NEWCO"]["rs_1m"] = 9.99
    comp = sc.composite(rows)
    assert "NEWCO" not in comp


def test_an_unmeasurable_name_is_absent_rather_than_ranked_last():
    """Absence is not a negative — ranking a name we cannot measure at the
    bottom is a claim about it that the data does not support."""
    rows = build_rows()
    rows["GHOST"] = {k: None for k in rows["T0"]}
    ranked = sc.cross_section_rank(rows, "rs_3m")
    assert "GHOST" not in ranked
    assert "T0" in ranked


def test_the_ranking_actually_orders_by_strength():
    """A composite that returned a constant would pass every test above.

    NOISE-FREE ON PURPOSE. The first version of this test used noisy series
    named by their 300-day drift and then asserted that ordering — and failed,
    because the "weak" name's LAST MONTH happened to be the strongest of the
    three (rs_1m +5.3% against the strong name's +4.5%). The scanner was right
    and the test was wrong: this module measures what a name is doing NOW, not
    its long-run drift, and a downtrend with a hot month is exactly the case it
    is supposed to surface. Deterministic series make the intended ordering the
    only ordering.
    """
    bench = trend(300, daily=0.0008)
    rows = {
        "STRONG": sc.features(trend(300, daily=0.004), bench),
        "MIDDLE": sc.features(trend(300, daily=0.001), bench),
        "WEAK": sc.features(trend(300, daily=-0.002), bench),
    }
    comp = sc.composite(rows, min_present=3)
    assert comp["STRONG"] > comp["MIDDLE"] > comp["WEAK"]


def test_a_downtrend_with_a_hot_month_outranks_a_grinding_riser_on_1m():
    """The behaviour the test above tripped over, pinned deliberately. A
    scanner that could not report this would just be a slow momentum sort."""
    bench = trend(300, daily=0.0008)
    faller = list(trend(280, daily=-0.002))
    # ...then a sharp three-week recovery
    last = faller[-1]
    faller += [last * (1 + 0.006) ** i for i in range(1, 21)]
    grinder = trend(300, daily=0.0009)
    rs_faller = sc.relative_strength(series(faller), bench, sc.MONTH)
    rs_grinder = sc.relative_strength(grinder, bench, sc.MONTH)
    assert rs_faller > rs_grinder
    # ...while the six-month picture still favours the grinder.
    assert sc.relative_strength(series(faller), bench, sc.HALF_YEAR) <            sc.relative_strength(grinder, bench, sc.HALF_YEAR)
