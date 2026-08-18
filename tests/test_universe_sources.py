"""The universe, the theme map, and which is which.

Two failures found on 2026-08-18, both of the same shape — a derived artifact
being treated as a source of truth:

1. `etf_holdings_scan.py` walked `data/sector_map.json` as if it were the
   universe. It is not: it is a hand-maintained ticker -> THEME labelling that
   covers 1,380 of the 1,755 tickers in `scan/universe_ci.csv`. The 375 it omits
   are almost entirely ETFs, because nobody assigns a theme to QQQ. So the fund
   look-through scan never looked inside QQQ, SPY, IVV, ITOT, VOO or VTI, and
   spent its nightly budget classifying individual stocks as "not a fund".

2. `data/sector_map.json` is exported from the `_SECTOR_MAP` literal in
   api_server.py by a script whose docstring said to run it manually. It was
   correct only because someone remembered. It is now regenerated in the daily
   workflow; this file asserts the two agree so a local edit fails fast rather
   than shipping a stale map to finvisible.

CI does not run pytest, so these are a local guard rather than a gate. Worth
having anyway: they turn "someone remembered" into "someone is told".
"""
from __future__ import annotations

import ast
import csv
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UNIVERSE_CSV = ROOT / "scan" / "universe_ci.csv"
SECTOR_MAP_JSON = ROOT / "data" / "sector_map.json"
API_SERVER = ROOT / "api_server.py"


def _universe() -> set[str]:
    with UNIVERSE_CSV.open(encoding="utf-8", newline="") as fh:
        return {str(r["ticker"]).upper().strip()
                for r in csv.DictReader(fh) if r.get("ticker")}


def _sector_map_json() -> dict:
    return json.loads(SECTOR_MAP_JSON.read_text(encoding="utf-8"))


def _sector_map_literal() -> dict:
    src = API_SERVER.read_text(encoding="utf-8")
    m = re.search(r"_SECTOR_MAP\s*=\s*(\{.*?\n\})", src, re.DOTALL)
    assert m, "_SECTOR_MAP literal not found in api_server.py"
    return ast.literal_eval(m.group(1))


# ── the published map must match its source ─────────────────────────────────

def test_the_published_sector_map_matches_the_literal_it_is_exported_from():
    """If this fails, someone edited _SECTOR_MAP and did not re-export — and
    finvisible is fetching a stale classification."""
    assert _sector_map_json() == _sector_map_literal(), (
        "data/sector_map.json is out of date with api_server.py's _SECTOR_MAP. "
        "Run: python scripts/export_sector_map.py")


def test_the_export_runs_in_the_daily_workflow():
    """The export used to be documented as a manual step. A published artifact
    that is correct because someone remembered is the same failure mode as a
    cache key nobody bumps."""
    wf = (ROOT / ".github" / "workflows" / "daily.yml").read_text(encoding="utf-8")
    assert "scripts/export_sector_map.py" in wf, (
        "sector_map.json is no longer regenerated in CI — it will drift from "
        "the literal the moment someone edits api_server.py")


# ── the theme map is a subset, not a second universe ────────────────────────

def test_the_theme_map_never_contains_a_ticker_the_universe_does_not():
    """A themed ticker that is not screened would be a genuine second universe
    drifting on its own. Currently zero, and it should stay that way."""
    stray = {k.upper() for k in _sector_map_json()} - _universe()
    assert not stray, f"themed but not in universe_ci.csv: {sorted(stray)[:20]}"


def test_the_theme_map_is_known_to_be_incomplete():
    """The inverse is EXPECTED — ETFs have no theme. This asserts the gap is
    still the shape we think it is, so a future reader does not mistake the
    theme map for the universe the way the ETF scan did."""
    unthemed = _universe() - {k.upper() for k in _sector_map_json()}
    assert unthemed, "the theme map now covers everything — update this test"
    assert len(unthemed) < len(_universe()) / 2


# ── the scan reads the universe, not the labelling ──────────────────────────

def test_the_etf_scan_reads_the_universe_csv():
    src = (ROOT / "scan" / "etf_holdings_scan.py").read_text(encoding="utf-8")
    assert "universe_ci.csv" in src, (
        "etf_holdings_scan.py is not reading the universe — if it walks "
        "sector_map.json again it will silently stop seeing every ETF")


@pytest.mark.parametrize("ticker", ["QQQ", "SPY", "IVV", "ITOT", "VOO", "VTI"])
def test_the_big_index_etfs_are_in_scope_for_look_through(ticker):
    """The specific tickers whose absence made the fund look-through useless on
    a real advisory book."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "etf_holdings_scan", ROOT / "scan" / "etf_holdings_scan.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert ticker in mod.load_universe()
