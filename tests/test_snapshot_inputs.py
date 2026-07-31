"""What a build does when its inputs are not all there.

The bug under test: build_snapshot() used to swallow every input failure with a
print and return a near-empty snapshot, so a run that lost inputs exited 0 and
published a thinner dashboard than it should have. These tests pin down the two
behaviours that replaced it — refuse on a REQUIRED input, announce loudly on an
EXPECTED one — and the silence that opt-in inputs still deserve.

No network, no sleeps: snapshot_builder does only local file I/O, and every
test runs against a tmp_path data dir via the `data_dir` fixture.
"""
import json

import pytest

import snapshot_builder
from snapshot_builder import (
    EXPECTED,
    INPUT_CRITICALITY,
    OPT_IN,
    REQUIRED,
    SnapshotInputError,
    _InputLedger,
    _load_signals_csv,
    build_snapshot,
    inject_snapshot,
)


def annotations(capsys, title=None):
    """GitHub Actions ::error:: lines emitted during the build."""
    lines = [ln for ln in capsys.readouterr().out.splitlines()
             if ln.startswith("::error")]
    if title:
        lines = [ln for ln in lines if f"title={title}" in ln]
    return lines


# ── the healthy case ─────────────────────────────────────────────────────────

def test_full_inputs_build_clean_with_no_annotation(data_dir, capsys):
    snap = build_snapshot()

    assert [s["ticker"] for s in snap["stocks"]] == ["AAA", "BBB"]
    assert snap["spy"]["regime"] == "Bull Trend"       # ret_20d 0.061 > 0.05
    assert snap["themes"] and snap["econ"] and snap["bubble_watch"]
    assert snap["watchlist"] == ["AAA", "ZZZ"]         # comment line dropped
    assert annotations(capsys) == []


# ── REQUIRED inputs: refuse ──────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["market_signals.csv", "spy_state.json"])
def test_missing_required_input_refuses_the_build(data_dir, capsys, name):
    (data_dir / name).unlink()

    with pytest.raises(SnapshotInputError) as excinfo:
        build_snapshot()

    assert name in str(excinfo.value)
    refused = annotations(capsys, "Snapshot refused")
    assert len(refused) == 1
    assert name in refused[0]


@pytest.mark.parametrize("name,content", [
    ("market_signals.csv", "ticker,name\nAAA,Alpha Corp\n"),   # schema changed
    ("market_signals.csv", "ticker,edge,horizon\n"),           # header only
    ("spy_state.json", "{not json"),
])
def test_unreadable_required_input_refuses_the_build(data_dir, write_input,
                                                     capsys, name, content):
    write_input(data_dir, name, content)

    with pytest.raises(SnapshotInputError):
        build_snapshot()

    assert annotations(capsys, "Snapshot refused")


def test_truncated_signals_csv_counts_as_missing(data_dir, write_input, capsys):
    """The size floor exists because a half-written CSV parses as valid."""
    write_input(data_dir, "market_signals.csv", "ticker,edge,horizon\nAAA,0.1,20d\n")
    assert (data_dir / "market_signals.csv").stat().st_size < 100

    with pytest.raises(SnapshotInputError) as excinfo:
        build_snapshot()
    assert "truncated" in str(excinfo.value)


def test_refusal_names_every_missing_required_input_not_just_the_first(
        data_dir, capsys):
    (data_dir / "market_signals.csv").unlink()
    (data_dir / "spy_state.json").unlink()

    with pytest.raises(SnapshotInputError) as excinfo:
        build_snapshot()

    message = str(excinfo.value)
    assert "market_signals.csv" in message and "spy_state.json" in message


# ── EXPECTED inputs: proceed, but loudly ─────────────────────────────────────

EXPECTED_INPUTS = [n for n, c in INPUT_CRITICALITY.items() if c == EXPECTED]


@pytest.mark.parametrize("name", EXPECTED_INPUTS)
def test_missing_expected_input_still_builds_but_annotates(data_dir, capsys, name):
    (data_dir / name).unlink()

    snap = build_snapshot()                     # does not raise

    assert snap["stocks"], "the rest of the snapshot must still be built"
    degraded = annotations(capsys, "Snapshot degraded")
    assert len(degraded) == 1
    assert name in degraded[0]


def test_corrupt_expected_input_annotates_with_the_exception_type(data_dir,
                                                                  write_input,
                                                                  capsys):
    write_input(data_dir, "enrichment.json", "{ this is not json")

    snap = build_snapshot()

    assert snap["stocks"]
    degraded = annotations(capsys, "Snapshot degraded")
    assert len(degraded) == 1
    assert "enrichment.json" in degraded[0]
    assert "JSONDecodeError" in degraded[0]


def test_one_annotation_lists_the_whole_degraded_set(data_dir, capsys):
    """The original bug was N quiet prints; the fix is one loud summary."""
    for name in ("enrichment.json", "price_data.json", "econ.json"):
        (data_dir / name).unlink()

    build_snapshot()

    degraded = annotations(capsys, "Snapshot degraded")
    assert len(degraded) == 1
    for name in ("enrichment.json", "price_data.json", "econ.json"):
        assert name in degraded[0]
    assert "3 input(s)" in degraded[0]


def test_degraded_annotation_says_the_page_did_update(data_dir, capsys):
    """Must not be mistaken for _report_frozen's "page did not change"."""
    (data_dir / "econ.json").unlink()
    build_snapshot()
    assert "not a frozen build" in annotations(capsys, "Snapshot degraded")[0]


# ── OPT_IN inputs: silence ───────────────────────────────────────────────────

OPT_IN_INPUTS = [n for n, c in INPUT_CRITICALITY.items() if c == OPT_IN]


@pytest.mark.parametrize("name", OPT_IN_INPUTS)
def test_absent_opt_in_input_is_not_a_fault(data_dir, capsys, name):
    """ticker_cache.json is gitignored and portfolio_v2.json does not exist yet;
    if either coloured a run red, every clean build would be red."""
    assert not (data_dir / name).exists()

    build_snapshot()

    assert annotations(capsys) == []


def test_present_but_corrupt_opt_in_input_is_still_not_fatal(data_dir,
                                                            write_input, capsys):
    write_input(data_dir, "ticker_cache.json", "{ broken")
    build_snapshot()
    assert annotations(capsys, "Snapshot refused") == []


# ── the ledger itself ────────────────────────────────────────────────────────

def test_ledger_prefers_refusal_over_degradation_when_both_apply(capsys):
    """A required failure must not be downgraded to a "degraded" annotation
    just because optional ones are also present."""
    ledger = _InputLedger()
    ledger.missing("econ.json")
    ledger.missing("market_signals.csv")

    with pytest.raises(SnapshotInputError):
        ledger.finish()

    out = capsys.readouterr().out
    assert "title=Snapshot refused" in out
    assert "title=Snapshot degraded" not in out


def test_ledger_is_silent_when_nothing_failed(capsys):
    _InputLedger().finish()
    assert "::error" not in capsys.readouterr().out


def test_unknown_input_name_defaults_to_expected_not_ignored():
    """A newly-added input nobody classified should still be announced."""
    ledger = _InputLedger()
    ledger.missing("some_new_feed.json")
    assert ledger.degraded


def test_caller_can_pass_its_own_ledger(data_dir):
    ledger = _InputLedger()
    (data_dir / "econ.json").unlink()

    build_snapshot(ledger=ledger)

    assert [name for name, _, _ in ledger.problems] == ["econ.json"]


# ── regressions in the code the change makes load-bearing ────────────────────

def test_signals_csv_schema_change_raises_a_useful_error(tmp_path):
    """Used to return a 2-tuple into a 3-value unpack, so the real cause was
    hidden behind "not enough values to unpack"."""
    path = tmp_path / "signals.csv"
    path.write_text("ticker,name\nAAA,Alpha Corp\n", encoding="utf-8")

    with pytest.raises(ValueError) as excinfo:
        _load_signals_csv(path)

    message = str(excinfo.value)
    assert "missing columns" in message
    assert "edge" in message and "horizon" in message


def test_signals_csv_returns_three_values_on_success(tmp_path):
    from conftest import SIGNALS_CSV
    path = tmp_path / "signals.csv"
    path.write_text(SIGNALS_CSV, encoding="utf-8")

    stocks, sectors, all_signals = _load_signals_csv(path)

    assert len(stocks) == 2
    assert {s["name"] for s in sectors} == {"Technology", "Energy"}
    assert len(all_signals) == 2


def test_watchlist_failure_does_not_raise_nameerror(data_dir, monkeypatch, capsys):
    """The old except clause referenced `sectors`, unbound whenever the signals
    CSV had not loaded — so a watchlist read error crashed the whole build."""
    target = data_dir / "watchlist.txt"

    original = snapshot_builder.Path.read_text

    def boom(self, *args, **kwargs):
        if self == target:
            raise OSError("disk gremlin")
        return original(self, *args, **kwargs)

    monkeypatch.setattr(snapshot_builder.Path, "read_text", boom)

    snap = build_snapshot()          # must not raise NameError

    assert snap["stocks"]
    degraded = annotations(capsys, "Snapshot degraded")
    assert "watchlist.txt" in degraded[0]
    assert "OSError" in degraded[0]


# ── injection safety ─────────────────────────────────────────────────────────

def test_inject_snapshot_replaces_the_block():
    html = "before\nwindow.SNAPSHOT = {\n  \"old\": 1\n};\nafter\n"
    out = inject_snapshot(html, {"new": 2})
    assert '"new": 2' in out and '"old"' not in out
    assert out.startswith("before") and out.rstrip().endswith("after")


def test_inject_snapshot_leaves_html_untouched_without_the_marker():
    html = "<html>no marker here</html>"
    assert inject_snapshot(html, {"a": 1}) == html


def test_required_snapshot_is_never_injected_over_a_good_one(data_dir):
    """The point of refusing: docs/index.html keeps its previous data rather
    than being overwritten with empty tables."""
    good = json.dumps({"stocks": [{"ticker": "AAA"}]}, indent=2)
    html = "x\nwindow.SNAPSHOT = " + good + "\n;\n};\ny\n"
    (data_dir / "market_signals.csv").unlink()

    with pytest.raises(SnapshotInputError):
        snap = build_snapshot()
        inject_snapshot(html, snap)          # never reached

    assert "AAA" in html
