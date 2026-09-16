"""B2 — shrinkage and false-discovery control. Checked by breaking the code."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scan"))

import selection as sel  # noqa: E402


def row(key, edge, spread=0.30, n=10):
    return {"key": key, "edge": edge, "spread": spread, "n_episodes": n}


# ── shrinkage ────────────────────────────────────────────────────────────────

def test_thin_evidence_is_pulled_harder_than_thick_evidence():
    """The engine's biggest edges rest on the FEWEST episodes — measured on the
    live feed, the top quartile averaged 8.9 episodes against 10.6 at the
    bottom. Shrinkage has to bite hardest exactly there."""
    thin = sel.shrink(raw=1.00, grand_mean=0.20, n_episodes=1)
    thick = sel.shrink(raw=1.00, grand_mean=0.20, n_episodes=100)
    assert thin < thick
    assert abs(thin - 0.2727) < 0.01, "one episode keeps almost nothing"
    assert thick > 0.90, "a hundred episodes keeps almost everything"


def test_at_the_half_life_a_row_keeps_half_its_distance():
    """SHRINK_K is defined as the episode count at which half survives; ten
    episodes is what a typical published row actually carries."""
    got = sel.shrink(raw=1.00, grand_mean=0.00, n_episodes=sel.SHRINK_K)
    assert abs(got - 0.50) < 1e-9


def test_shrinkage_pulls_toward_the_crowd_not_toward_zero():
    """A row at the population mean must not move at all. Shrinking toward zero
    instead would penalise a whole cohort for being uniformly good."""
    rows = [row("A", 0.50), row("B", 0.50), row("C", 0.50)]
    out = sel.shrink_all(rows)
    assert all(abs(r["shrunk"] - 0.50) < 1e-9 for r in out)


def test_a_below_average_row_is_pulled_UP():
    """Symmetry. A one-way haircut is a conservatism knob, not an estimator."""
    out = sel.shrink_all([row("HI", 1.0), row("LO", 0.0)])
    lo = next(r for r in out if r["key"] == "LO")
    assert lo["shrunk"] > 0.0


def test_a_row_with_no_edge_stays_unknown():
    out = sel.shrink_all([{"key": "X", "edge": None, "spread": 0.3, "n_episodes": 10}])
    assert out[0]["shrunk"] is None


# ── the sample size is episodes, not observations ────────────────────────────

def test_significance_uses_episodes_not_observations():
    """The feed reports ~24 observations and ~10 episodes for the same row.
    Analog days one session apart, measured over a 120-day forward window, are
    the same observation wearing different dates; using 24 would overstate
    significance by about 60%."""
    by_episodes = sel.t_stat(0.20, 0.30, 10)
    by_observations = sel.t_stat(0.20, 0.30, 24)
    assert by_observations > by_episodes * 1.5
    # PIN THE ACTUAL VALUE, not just the ordering. Comparing two calls only
    # proves the function responds to its argument — a version that quietly
    # scaled n up by the observation/episode ratio scaled BOTH calls and passed.
    # mean / (spread / sqrt(n)) = 0.20 / (0.30 / sqrt(10)) = 2.108
    assert abs(by_episodes - 0.20 / (0.30 / 10 ** 0.5)) < 1e-9


def test_a_single_episode_cannot_be_significant():
    assert sel.t_stat(5.0, 0.30, 1) is None
    assert sel.p_value(5.0, 0.30, 1) is None


def test_a_wider_spread_is_less_significant_at_the_same_mean():
    tight = sel.p_value(0.20, 0.10, 10)
    wide = sel.p_value(0.20, 0.80, 10)
    assert tight < wide


# ── false discovery control ──────────────────────────────────────────────────

def test_pure_noise_produces_no_survivors():
    """THE TEST THIS MODULE EXISTS FOR. 400 candidates whose p-values are
    uniform — exactly what you get when nothing is real. An uncorrected filter
    at p<0.05 would hand back about twenty names and call them signals."""
    pvals = {f"N{i}": (i + 0.5) / 400 for i in range(400)}
    naive = {k for k, p in pvals.items() if p < 0.05}
    assert len(naive) >= 15, "the uncorrected filter really does fire on noise"
    assert sel.benjamini_hochberg(pvals, q=0.10) == set()


def test_a_genuinely_strong_result_still_gets_through():
    """Control that passes nothing is not control, it is a switch that is off.
    One overwhelming p-value among 399 uniform ones must survive."""
    pvals = {f"N{i}": (i + 0.5) / 400 for i in range(399)}
    pvals["REAL"] = 1e-9
    kept = sel.benjamini_hochberg(pvals, q=0.10)
    assert "REAL" in kept


def test_the_procedure_keeps_the_run_not_just_the_minimum():
    """BH keeps everything up to the largest surviving index — the step that a
    naive implementation gets wrong by stopping at the first failure."""
    pvals = {"A": 1e-9, "B": 2e-9, "C": 3e-9, "D": 0.9, "E": 0.95}
    kept = sel.benjamini_hochberg(pvals, q=0.10)
    assert kept == {"A", "B", "C"}

    # THE CASE THAT SEPARATES BH FROM A LOOP THAT BREAKS ON FIRST FAILURE.
    # m=5, q=0.1 -> thresholds .02 .04 .06 .08 .10
    #   p1 0.010 <= .02  pass
    #   p2 0.050 >  .04  FAIL   <- a break here keeps only A
    #   p3 0.055 <= .06  pass
    #   p4 0.060 <= .08  pass
    #   p5 0.090 <= .10  pass   <- largest passing index is 5, so ALL survive
    # Stopping early is the classic wrong implementation and it survived the
    # first version of this test, where every passing p came before every
    # failing one.
    run = {"A": 0.010, "B": 0.050, "C": 0.055, "D": 0.060, "E": 0.090}
    assert sel.benjamini_hochberg(run, q=0.10) == {"A", "B", "C", "D", "E"}


def test_a_stricter_q_keeps_fewer():
    pvals = {f"N{i}": p for i, p in enumerate([0.001, 0.004, 0.01, 0.02, 0.2, 0.5])}
    assert len(sel.benjamini_hochberg(pvals, q=0.20)) >= \
           len(sel.benjamini_hochberg(pvals, q=0.01))


def test_an_empty_candidate_set_is_empty_not_an_error():
    assert sel.benjamini_hochberg({}, q=0.1) == set()


# ── the pipeline ─────────────────────────────────────────────────────────────

def test_select_reports_how_many_were_considered_not_only_what_survived():
    """"0 of 398 survived" is the most useful line this can print, and a
    payload carrying only survivors cannot say it."""
    rows = [row(f"T{i}", 0.20 + i * 0.001, spread=0.5, n=10) for i in range(50)]
    out = sel.select(rows)
    assert out["n_candidates"] == 50
    assert out["n_tested"] == 50
    assert out["n_survivors"] == len(out["survivors"])


def test_a_day_with_nothing_worth_buying_says_so():
    """Wide spreads on ten episodes: nothing here is distinguishable from luck,
    and the honest output is an empty set rather than a top three."""
    rows = [row(f"T{i}", 0.10, spread=2.0, n=10) for i in range(300)]
    out = sel.select(rows)
    assert out["n_survivors"] == 0


def test_a_row_that_cannot_be_tested_is_not_silently_kept():
    rows = [row("GOOD", 0.9, spread=0.05, n=40),
            {"key": "NOSPREAD", "edge": 5.0, "spread": None, "n_episodes": 40}]
    out = sel.select(rows)
    assert "NOSPREAD" not in out["survivors"]
    assert out["n_tested"] == 1
