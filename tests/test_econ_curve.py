"""build_curve()'s failure behaviour, with a fake fetcher — no network.

The contract tests next door assert the SHAPE of what got published. These
assert how the builder behaves when FRED is partly or wholly unavailable,
which is the case that decides whether a bad day publishes a broken curve or
simply publishes less of one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scan"))

import econ_scan  # noqa: E402


# Fixtures are anchored to the present, not a hardcoded date: the retention
# window is measured from today, so a fixed 2026 date would silently fall out
# of the window as time passes and start testing something else.
RECENT = pd.Timestamp.today().normalize() - pd.Timedelta(days=20)


def series(vals, start=None):
    idx = pd.bdate_range(start if start is not None else RECENT, periods=len(vals))
    return pd.Series(vals, index=idx, dtype="float64")


def fetcher(mapping):
    """A fetch(sid) that returns only what mapping provides; None otherwise."""
    return lambda sid: mapping.get(sid)


def full(n=30):
    """Every tenor present, each rising with maturity so order is checkable."""
    return {sid: series([1.0 + i * 0.5 + j * 0.01 for j in range(n)])
            for i, sid in enumerate(econ_scan.CURVE)}


def test_builds_every_tenor_when_all_are_available():
    c = econ_scan.build_curve(fetcher(full()))
    assert c is not None
    assert [p["sid"] for p in c["points"]] == list(econ_scan.CURVE)
    assert [p["years"] for p in c["points"]] == sorted(p["years"] for p in c["points"])
    assert set(c["history"]["values"]) == set(econ_scan.CURVE)


def test_a_missing_tenor_drops_out_without_failing_the_build():
    m = full()
    del m["DGS7"]
    c = econ_scan.build_curve(fetcher(m))
    assert c is not None, "one absent tenor must not lose the whole curve"
    sids = {p["sid"] for p in c["points"]}
    assert "DGS7" not in sids
    assert "DGS10" in sids, "the other tenors must survive"
    assert "DGS7" not in c["history"]["values"]


def test_an_empty_series_is_treated_as_absent():
    m = full()
    m["DGS2"] = pd.Series(dtype="float64")
    c = econ_scan.build_curve(fetcher(m))
    assert "DGS2" not in {p["sid"] for p in c["points"]}


def test_returns_none_when_nothing_can_be_fetched():
    """A total FRED outage must NOT publish an empty curve — main() keeps the
    previous one instead. Returning an empty dict here would overwrite a good
    curve with nothing."""
    assert econ_scan.build_curve(fetcher({})) is None


def test_ragged_histories_are_aligned_and_gaps_left_null():
    """The tenors do not all start on the same day. Values must be positioned
    against the union index, with genuine gaps as null — never forward-filled,
    because a filled yield becomes a zero yield CHANGE downstream."""
    m = full(n=10)
    late = series([5.0, 5.1, 5.2], start=RECENT + pd.Timedelta(days=7))
    m["DGS30"] = late                                          # starts late, ends early
    c = econ_scan.build_curve(fetcher(m))
    h = c["history"]
    n = len(h["dates"])
    assert all(len(v) == n for v in h["values"].values())
    vals = h["values"]["DGS30"]
    assert vals[0] is None, "a tenor with no early data must be null, not filled"
    assert vals[-1] is None, "and null after its data ends, not carried forward"
    assert [v for v in vals if v is not None] == [5.0, 5.1, 5.2]
    # and they must land on DGS30's own dates, not merely be present somewhere
    got = {d: v for d, v in zip(h["dates"], vals) if v is not None}
    assert got == {d.date().isoformat(): v for d, v in late.items()}


def test_history_dates_are_ascending_and_unique():
    """Pins the ordering invariant directly. Note: mutating away the explicit
    sort in build_curve does NOT fail this, because DatetimeIndex.union already
    returns sorted — that mutant is equivalent, verified rather than assumed.
    The assertion is here so the PROPERTY is pinned regardless of how the index
    comes to be built, since consumers diff these dates to get yield changes."""
    m = full(n=10)
    m["DGS30"] = series([5.0, 5.1], start=RECENT + pd.Timedelta(days=3))
    m["DGS1MO"] = series([1.0, 1.1], start=RECENT - pd.Timedelta(days=10))
    d = econ_scan.build_curve(fetcher(m))["history"]["dates"]
    assert d == sorted(d), "history dates are not ascending"
    assert len(set(d)) == len(d), "history dates contain duplicates"


def test_stale_tenors_are_named_not_silently_mixed():
    """A tenor stuck a day behind still belongs on the curve, but the consumer
    is told which one, so 'as_of' is never quietly wrong for part of the curve."""
    m = full(n=10)
    m["DGS20"] = m["DGS20"].iloc[:-1]           # one day behind everyone else
    c = econ_scan.build_curve(fetcher(m))
    assert c["stale_tenors"] == ["20Y"]
    assert c["as_of"] == max(p["date"] for p in c["points"])


def test_as_of_is_the_newest_observation_not_todays_date():
    """FRED publishes with a lag; the curve must date itself by its data."""
    m = full(n=5)
    c = econ_scan.build_curve(fetcher(m))
    newest = max(s.index[-1].date().isoformat() for s in m.values())
    assert c["as_of"] == newest


def test_history_is_trimmed_to_the_retention_window():
    """Five years in, three years out. Without the trim, econ.json grows without
    bound on a file that is committed by CI every day."""
    idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=5 * 261)
    long_hist = {sid: pd.Series([1.0] * len(idx), index=idx, dtype="float64")
                 for sid in econ_scan.CURVE}
    c = econ_scan.build_curve(fetcher(long_hist))
    first = pd.Timestamp(c["history"]["dates"][0])
    cutoff = pd.Timestamp.today() - pd.Timedelta(days=365 * econ_scan.CURVE_HISTORY_YEARS)
    assert first >= cutoff - pd.Timedelta(days=7), (
        f"history starts {first.date()}, older than the "
        f"{econ_scan.CURVE_HISTORY_YEARS}y retention window")
    assert len(c["history"]["dates"]) < len(idx), "nothing was trimmed at all"


def test_data_entirely_older_than_the_window_is_unbuildable():
    """Points with no history would pass a 'curve exists' check and fail the
    alignment contract. Found by a test that was wrong for a different reason."""
    idx = pd.bdate_range("2015-01-01", periods=200)
    stale = {sid: pd.Series([1.0] * len(idx), index=idx, dtype="float64")
             for sid in econ_scan.CURVE}
    assert econ_scan.build_curve(fetcher(stale)) is None
