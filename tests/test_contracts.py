"""The published data contracts, asserted here because nothing else asserts them.

regime-desk is the suite's database. `data/` on `main` is served over
raw.githubusercontent to two independent consumers that this repo cannot see:

    PAPA        scan/universe_ci.csv, data/market_signals.csv,
                data/stock_scores.csv, data/cross_asset.json
    finvisible  data/market_signals.csv, data/sector_map.json,
                data/theme_summary.csv, data/signal_log.csv,
                data/stock_scores.csv, data/etf_holdings.json,
                data/econ.json  (the Treasury curve, for the fixed-income panel)
    sim-desk    data/sector_map.json

They read DIFFERENT columns of the same files. finvisible needs `hit_alpha` and
`hit_self` out of market_signals; PAPA needs `persistence` out of stock_scores;
both need the eight in COMMON below. Until this file existed, renaming a column in ci_scan.py left
this repo's tests green, committed on the daily run, and broke both consumers —
differently, and without either failure naming the cause.

The failure modes are not symmetric, which is why this is worth more than it
looks:

  * PAPA fails LOUDLY. sync_inputs.py refuses to run on a partial input set,
    because "a missing market_signals.csv looks exactly like 'no signals today',
    which would sell the book down rather than do nothing."
  * finvisible degrades QUIETLY to "feed unavailable". Correct for a missing
    file, wrong for a renamed column — the advisor sees a blank panel and no
    reason.

So: every column a downstream consumer reads is named here, with the consumer in
the assertion message. If you are deleting one of these, you are changing an
interface, and the test is the place that says so.

Kept deliberately cheap — it reads the committed artifacts, has no network, and
runs in well under a second, so it can gate CI whenever pytest is added to the
workflow.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# ── who reads what ──────────────────────────────────────────────────────────
# Traced from the consumers' source on 2026-08-18. See ARCHITECTURE.md §4.

SIGNALS_COMMON = ["ticker", "edge", "hit_rate", "n_obs", "horizon",
                  "sector", "p10", "p90"]
# NOT "conf". PAPA writes that column itself, in _attach_confidence(), from
# edge/hit_rate/n_obs plus persistence out of stock_scores.csv. The first draft
# of this file listed it as a read because it was derived by grepping quoted
# column names in portfolio_manager.py — which catches what a consumer CREATES
# as readily as what it consumes. The test failed on its first run and was
# right to: the contract was wrong, not the data.
SIGNALS_PAPA_ONLY: list[str] = []
SIGNALS_FINVISIBLE_ONLY = ["hit_alpha", "hit_self"]   # the Hit trio

CONTRACTS = {
    "data/market_signals.csv": {
        "PAPA": SIGNALS_COMMON + SIGNALS_PAPA_ONLY,
        "finvisible": SIGNALS_COMMON + SIGNALS_FINVISIBLE_ONLY,
    },
    "data/stock_scores.csv": {
        "PAPA": ["ticker", "persistence"],
        "finvisible": ["ticker", "persistence", "hit_rate"],
    },
    "data/theme_summary.csv": {
        "finvisible": ["sector", "count", "avg_edge", "max_edge", "horizon"],
    },
    "scan/universe_ci.csv": {
        "PAPA": ["ticker", "name", "sector"],
        "regime-desk/etf_holdings_scan": ["ticker"],
    },
}

JSON_CONTRACTS = {
    "data/cross_asset.json": {"PAPA": ["signals", "risks"]},
    "data/etf_holdings.json": {"finvisible": ["meta", "funds"]},
    # finvisible's fixed-income panel reads the Treasury curve: the `points`
    # cross-section for the curve chart, and the DAILY `history` to regress a
    # bond fund's returns against yield changes and get an empirical duration.
    # A top-level key check is not enough for this one — see the shape test
    # below, because the history arrays have to stay index-aligned or the
    # regression silently pairs a fund return with the wrong day's yield.
    "data/econ.json": {"finvisible": ["as_of", "curve"]},
}


def _columns(rel: str) -> list[str]:
    path = ROOT / rel
    assert path.exists(), f"{rel} is published and consumed, but is not here"
    with path.open(encoding="utf-8", newline="") as fh:
        header = next(csv.reader(fh), [])
    return [h.strip() for h in header]


def _cases():
    for rel, consumers in CONTRACTS.items():
        for who, cols in consumers.items():
            for col in cols:
                yield rel, who, col


@pytest.mark.parametrize("rel,who,col", list(_cases()),
                         ids=lambda v: str(v).replace("/", "_"))
def test_published_column_exists(rel, who, col):
    """Named one column at a time so a failure says exactly what broke and for
    whom, rather than dumping a set difference."""
    cols = _columns(rel)
    assert col in cols, (
        f"{rel} no longer has column {col!r}, which {who} reads. "
        f"That is an interface change: fix the producer, or update {who} and "
        f"this contract together. Present columns: {cols}")


@pytest.mark.parametrize("rel,consumers", list(JSON_CONTRACTS.items()))
def test_published_json_keys_exist(rel, consumers):
    path = ROOT / rel
    assert path.exists(), f"{rel} is consumed but missing"
    obj = json.loads(path.read_text(encoding="utf-8"))
    for who, keys in consumers.items():
        for k in keys:
            assert k in obj, f"{rel} lost top-level key {k!r}, read by {who}"


def test_sector_map_is_a_flat_ticker_to_string_map():
    """finvisible and sim-desk both treat it as {TICKER: theme}. A nested shape
    would break both without either noticing it had changed."""
    obj = json.loads((DATA / "sector_map.json").read_text(encoding="utf-8"))
    assert isinstance(obj, dict) and obj
    bad = [k for k, v in obj.items() if not isinstance(v, str)]
    assert not bad, f"non-string theme values: {bad[:10]}"


def test_market_signals_is_not_empty():
    """An empty file parses fine and reads downstream as 'no signals today'.
    PAPA's own note: that would sell the book down rather than do nothing."""
    with (DATA / "market_signals.csv").open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows, "market_signals.csv has a header and no rows"


def test_every_contract_file_is_actually_published():
    """A contract naming a file this repo does not publish is a stale contract."""
    for rel in list(CONTRACTS) + list(JSON_CONTRACTS):
        assert (ROOT / rel).exists(), f"{rel} is in the contract but not in the repo"


def test_the_contract_covers_every_file_a_consumer_fetches():
    """Guards the guard: if a new artifact starts being consumed, it should be
    added here. This list is the one place that has to be kept honest by hand,
    so it is asserted against the repo rather than left as a comment."""
    consumed = {
        "scan/universe_ci.csv", "data/market_signals.csv", "data/stock_scores.csv",
        "data/cross_asset.json", "data/sector_map.json", "data/theme_summary.csv",
        "data/signal_log.csv", "data/etf_holdings.json", "data/econ.json",
    }
    covered = set(CONTRACTS) | set(JSON_CONTRACTS) | {"data/sector_map.json",
                                                      "data/signal_log.csv"}
    missing = consumed - covered
    assert not missing, f"consumed downstream but not under contract: {sorted(missing)}"


# ── the Treasury curve block ────────────────────────────────────────────────
# Added 2026-08-26 with the fixed-income panel. finvisible consumes this and,
# per the note at the top of this file, degrades QUIETLY — so a shape change
# here shows up as a blank panel with no stated reason, not as an error.

def _curve():
    obj = json.loads((ROOT / "data/econ.json").read_text(encoding="utf-8"))
    assert "curve" in obj, "data/econ.json lost its curve block, read by finvisible"
    return obj["curve"]


def test_curve_points_carry_every_field_finvisible_plots():
    for p in _curve()["points"]:
        for k in ("sid", "label", "years", "yield"):
            assert k in p, f"curve point {p.get('sid', p)} is missing {k!r}"
        assert isinstance(p["years"], (int, float)) and p["years"] > 0
        assert isinstance(p["yield"], (int, float))


def test_curve_tenors_are_ordered_short_to_long():
    """finvisible plots points in array order without sorting. Out-of-order
    tenors would draw a curve that zig-zags rather than one that is wrong in an
    obvious way, which is worse."""
    yrs = [p["years"] for p in _curve()["points"]]
    assert yrs == sorted(yrs), f"curve tenors are not ascending: {yrs}"
    assert len(set(yrs)) == len(yrs), f"curve has duplicate maturities: {yrs}"


def test_curve_history_is_index_aligned():
    """THE assertion that matters. Every tenor's value array is positionally
    zipped against `dates` to build the yield-change series the duration
    regression consumes. One short array shifts a fund's returns against the
    wrong days and produces a confident, wrong duration."""
    h = _curve()["history"]
    n = len(h["dates"])
    assert n > 0, "curve history has no dates"
    for sid, vals in h["values"].items():
        assert len(vals) == n, (
            f"curve history {sid} has {len(vals)} values against {n} dates — "
            f"positional zip would misalign every observation after the gap")


def test_curve_history_dates_are_unique_and_ascending():
    d = _curve()["history"]["dates"]
    assert d == sorted(d), "curve history dates are not ascending"
    assert len(set(d)) == len(d), "curve history has duplicate dates"


def test_curve_history_covers_every_published_tenor():
    c = _curve()
    pts = {p["sid"] for p in c["points"]}
    hist = set(c["history"]["values"])
    assert pts <= hist, f"tenors on the curve with no history: {pts - hist}"


def test_curve_gaps_are_null_not_forward_filled():
    """A forward-filled yield becomes a ZERO yield CHANGE, which is what the
    regression actually eats — it would quietly bias every duration toward
    zero. Missing observations must stay null."""
    for sid, vals in _curve()["history"]["values"].items():
        for v in vals:
            assert v is None or isinstance(v, (int, float)), (
                f"curve history {sid} holds a non-numeric, non-null value: {v!r}")
