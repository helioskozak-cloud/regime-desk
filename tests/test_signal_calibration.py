"""The engine's self-calibration — A1 and B8 in the owner's plan, 2026-09-16.

Each of these was checked by breaking the code first; a test that has never
failed has proved nothing about the code it covers.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scan"))

import signal_calibration as sc  # noqa: E402


def rows(n, horizon="20d", predicted=0.10, actual=0.03, alpha=-0.01):
    return [{"run_date": f"2026-0{1 + i % 8}-01", "ticker": f"T{i}", "horizon": horizon,
             "predicted_edge": predicted, "actual_return": actual, "regime_alpha": alpha}
            for i in range(n)]


def test_thin_history_is_unmeasured_not_perfect():
    """A calibration fitted on a handful of rows is the first mistake, twice.

    Returning a ratio of 1.0 here would say "this feed has no error" on the
    strength of a dozen observations — which is exactly the claim the whole
    module exists to stop the dashboard making.
    """
    assert sc.calibrate_horizon(rows(sc.MIN_RESOLVED - 1)) is None
    assert sc.calibrate_horizon(rows(sc.MIN_RESOLVED)) is not None


def test_ratio_is_realized_over_predicted():
    """The number that fixes the display: +10% posted, +3% delivered -> 0.30."""
    c = sc.calibrate_horizon(rows(100, predicted=0.10, actual=0.03))
    assert abs(c.ratio - 0.30) < 1e-9
    # And it is applied, not merely reported.
    assert abs(c.calibrate(0.50) - 0.15) < 1e-9


def test_an_overstating_feed_shrinks_and_an_honest_one_does_not():
    """Mutation guard: a hardcoded shrink would pass the test above alone."""
    honest = sc.calibrate_horizon(rows(100, predicted=0.05, actual=0.05))
    assert abs(honest.ratio - 1.0) < 1e-9
    assert abs(honest.calibrate(0.20) - 0.20) < 1e-9
    liar = sc.calibrate_horizon(rows(100, predicted=0.50, actual=0.05))
    assert liar.ratio < 0.15


def test_a_feed_that_understates_scales_up():
    """Calibration is symmetric. A ratio clamped at <= 1 would hide the case
    where the engine is too pessimistic, which is a different error and not a
    safer one."""
    c = sc.calibrate_horizon(rows(100, predicted=0.02, actual=0.06))
    assert c.ratio > 1.0
    assert abs(c.calibrate(0.10) - 0.30) < 1e-9


def test_a_non_positive_predicted_mean_cannot_scale_anything():
    """Dividing by a predicted mean of ~0 inverts signs at random. The honest
    answer is to leave the number alone rather than to publish a wild factor."""
    c = sc.calibrate_horizon(rows(100, predicted=0.0, actual=0.04))
    assert c.ratio == 1.0
    assert c.calibrate(0.10) == 0.10


def test_beat_rate_counts_alpha_not_return():
    """A rising tide lifts every raw return. Beating SPY is the question a book
    actually asks, and the two answers differ: these rows are all POSITIVE in
    absolute terms and all LOSE to the index."""
    c = sc.calibrate_horizon(rows(100, predicted=0.10, actual=0.03, alpha=-0.02))
    assert c.realized_mean > 0
    assert c.beat_rate == 0.0


def test_horizons_are_calibrated_separately():
    """One blended factor would flatter the short horizons and punish the long
    ones: measured, 5d runs at -0.16x and 120d at 0.39x."""
    data = (rows(80, horizon="5d", predicted=0.07, actual=-0.01)
            + rows(80, horizon="120d", predicted=0.50, actual=0.20))
    cals = sc.calibrate_all(data)
    assert set(cals) == {"5d", "120d"}
    assert cals["5d"].ratio < 0
    assert 0.3 < cals["120d"].ratio < 0.5


def test_a_horizon_with_too_little_history_is_absent_not_zeroed():
    """Absence is not a negative. A 5d entry reading 0.0 would be read as a
    horizon that delivers nothing, rather than one we cannot judge yet."""
    data = rows(80, horizon="20d") + rows(5, horizon="5d")
    cals = sc.calibrate_all(data)
    assert "20d" in cals
    assert "5d" not in cals


def test_correlation_reports_no_ranking_power_when_there_is_none():
    """The measured figure is ~0.00 at every horizon, which is the strongest
    single argument against using this to pick. A correlation that read 1.0
    because every predicted value is identical would bury it."""
    data = [{"horizon": "20d", "predicted_edge": 0.1 + (i % 7) * 0.01,
             "actual_return": (0.20 if i % 2 else -0.18), "regime_alpha": 0.0,
             "run_date": "2026-05-01"} for i in range(120)]
    c = sc.calibrate_horizon(data)
    assert abs(c.correlation) < 0.25


def test_the_downside_is_published_alongside_the_average():
    """A mean alone is how a screen full of +20% figures hides that the bottom
    decile lost a fifth of its value."""
    data = [{"horizon": "20d", "predicted_edge": 0.2,
             "actual_return": (-0.30 if i < 15 else 0.10), "regime_alpha": 0.0,
             "run_date": "2026-05-01"} for i in range(100)]
    c = sc.calibrate_horizon(data)
    assert c.realized_mean > 0
    assert c.realized_p10 < -0.2


def test_scorecard_carries_the_warning_and_the_span():
    sheet = sc.scorecard(rows(100, horizon="20d"))
    assert sheet["resolved"] == 100
    assert sheet["first_run"] and sheet["last_run"]
    assert "not for picking" in sheet["note"]
    assert "20d" in sheet["horizons"]


def test_scorecard_on_an_empty_log_says_nothing_rather_than_zero():
    sheet = sc.scorecard([])
    assert sheet["resolved"] == 0
    assert sheet["beat_rate"] is None
    assert sheet["horizons"] == {}
