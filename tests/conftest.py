"""Shared fixtures.

Every test here builds a snapshot against a throwaway data directory. Nothing
touches the network (snapshot_builder does no network I/O), nothing sleeps, and
nothing reads or writes the real data/ or docs/ trees.
"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build"))

import snapshot_builder  # noqa: E402


# A minimal but valid market_signals.csv: two tickers, two sectors, n_obs above
# the >=4 cutoff that _load_signals_csv applies.
SIGNALS_CSV = (
    "ticker,edge,horizon,p10,p25,p50,p75,p90,hit_rate,n_obs,sector,name\n"
    "AAA,0.12,20d,-0.04,-0.01,0.03,0.08,0.15,0.61,12,Technology,Alpha Corp\n"
    "BBB,0.02,20d,-0.06,-0.02,0.01,0.05,0.11,0.48,9,Energy,Beta Inc\n"
)

SPY_STATE = {
    "ret_5d": 0.004, "ret_20d": 0.061, "vol_20d": 0.011, "drawdown_60d": -0.02,
    "history": [{"ret_5d": 0.004, "ret_20d": 0.061,
                 "vol_20d": 0.011, "drawdown_60d": -0.02}],
}

# Every input snapshot_builder knows about, keyed by filename, with content
# valid enough to load. Tests delete or corrupt individual entries.
FULL_INPUTS = {
    "market_signals.csv": SIGNALS_CSV,
    "spy_state.json": SPY_STATE,
    "theme_summary.csv": "sector,count,avg_edge,max_edge,horizon\nTechnology,2,0.07,0.12,20d\n",
    "cross_asset.json": {"signals": [{"name": "credit"}], "risks": [{"name": "rates"}]},
    "enrichment.json": {"AAA": {"avg_volume": 1000, "market_cap": 2e9}},
    "price_data.json": {"AAA": {"price": 10.0, "change_pct": 1.2,
                                "week_closes": [9.8, 9.9, 10.0]}},
    "stock_scores.csv": "ticker,persistence,avg_regime_alpha,resolved_signals,hit_rate\nAAA,3,0.02,7,0.55\n",
    "portfolio.json": {"book": {"name": "Book", "version": "v2", "cash": 1000.0,
                                "holdings": {}, "history": [], "transactions": []}},
    "portfolio_v1.json": {"book": {"name": "Book v1", "version": "v1", "cash": 500.0,
                                   "holdings": {}, "history": [], "transactions": []}},
    "bubble_watch.json": {"years": [{"year": 1999, "doubled": 10, "halved": 2}]},
    "econ.json": {"series": {"CPI": [1, 2, 3]}},
    "watchlist.txt": "AAA\n# a comment\nZZZ\n",
}


def _write(data_dir: Path, name: str, content) -> None:
    path = data_dir / name
    if isinstance(content, (dict, list)):
        path.write_text(json.dumps(content), encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """A fully-populated data/ directory that snapshot_builder reads from.

    Points the module's DATA constant at a tmp dir, so no test can reach the
    repository's real data/.
    """
    d = tmp_path / "data"
    d.mkdir()
    for name, content in FULL_INPUTS.items():
        _write(d, name, content)
    monkeypatch.setattr(snapshot_builder, "DATA", d)
    return d


@pytest.fixture
def write_input():
    """Write (or overwrite) one input inside a data dir."""
    return _write
