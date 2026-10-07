"""scan/earnings_scan.py: the universe earnings calendar (2026-10-07, Q35 = b)."""
import datetime
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scan"))
import earnings_scan as es  # noqa: E402


def test_window_is_monday_this_week_to_friday_next_weekdays_only():
    days = es.window(datetime.date(2026, 10, 7))                     # a Wednesday
    assert days[0] == datetime.date(2026, 10, 5) and days[-1] == datetime.date(2026, 10, 16)
    assert len(days) == 10 and all(d.weekday() < 5 for d in days)
    assert es.window(datetime.date(2026, 10, 11))[0] == datetime.date(2026, 10, 5)   # Sunday


def test_money_reads_nasdaq_strings():
    assert es.money("$2.29") == 2.29
    assert es.money("($0.08)") == -0.08
    assert es.money("$171,498,619,000") == 171_498_619_000
    assert es.money("N/A") is None and es.money("") is None and es.money(None) is None


def test_keep_drops_names_outside_the_universe_and_maps_timing():
    meta = {"PEP": ("PepsiCo", "Consumer Staples"), "BRK-B": ("nan", "Financials")}
    raw = [{"symbol": "PEP", "time": "time-pre-market", "epsForecast": "$2.29", "noOfEsts": "7",
            "lastYearEPS": "$2.29", "marketCap": "$171,498,619,000", "fiscalQuarterEnding": "Sep/2026"},
           {"symbol": "BRK/B", "name": "Berkshire Hathaway", "time": "time-after-hours", "epsForecast": "", "noOfEsts": "N/A"},
           {"symbol": "ZZZZ", "time": "time-pre-market"}]
    got = es.keep(datetime.date(2026, 10, 8), raw, meta)
    assert [r["ticker"] for r in got] == ["PEP", "BRK-B"]
    assert got[0]["time"] == "pre" and got[0]["eps"] == 2.29 and got[0]["n_est"] == 7
    assert got[0]["sector"] == "Consumer Staples"
    assert got[1]["name"] == "Berkshire Hathaway"                  # universe name blank
    assert got[1]["time"] == "post" and got[1]["eps"] is None and got[1]["n_est"] is None


def test_a_failed_day_keeps_the_previous_rows_and_is_recorded():
    uni_tk = es.pd.read_csv(es.UNIVERSE)["ticker"].iloc[0]
    today = datetime.date(2026, 10, 7)
    bad = datetime.date(2026, 10, 8)
    prev = {"earnings": [{"date": "2026-10-08", "ticker": "OLD", "name": "Old", "sector": "x",
                          "time": "", "eps": None, "n_est": None, "eps_ly": None, "mcap": None,
                          "quarter": ""}]}

    def fake(d, session):
        if d == bad:
            raise RuntimeError("timeout")
        return [{"symbol": uni_tk, "time": "time-pre-market", "epsForecast": "$1.00",
                 "marketCap": "$1,000,000,000"}] if d == today else []

    es.time.sleep, real = (lambda s: None), es.time.sleep
    try:
        blob = es.scan(today=today, prev=prev, fetch=fake)
    finally:
        es.time.sleep = real
    assert blob["days_failed"] == ["2026-10-08"] and len(blob["days_read"]) == 9
    assert {r["ticker"] for r in blob["earnings"]} == {es.symbol(uni_tk), "OLD"}
    assert blob["start"] == "2026-10-05" and blob["end"] == "2026-10-16"
