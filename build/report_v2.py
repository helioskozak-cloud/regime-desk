"""
report_v2.py — generates an advisor-review style PDF for the LIVE v2
paper portfolios. Same layout as report_v1.py but methodology, title,
and footer reflect the v2 ruleset (horizon exits + signal-decay +
stay-long renewals + continuous buying).

Run: python build/report_v2.py
Output: reports/v2_portfolio_review_<date>.pdf
"""
import json
import sys
from datetime import date
from pathlib import Path

# Allow `python build/report_v2.py` from project root by adding build/ to path
sys.path.insert(0, str(Path(__file__).parent))
from report_v1 import build_report, _shape, DATA, OUT_DIR


V2_META = {
    "title":          "Paper Portfolio Review — v2 Live",
    "doc_title":      "Regime Desk — v2 Portfolio Review",
    "subtitle_fmt":   "Report generated {today} · Live experiment since {inception} · "
                      "Simulated only — not investment advice",
    "methodology":    "Methodology: Three paper portfolios were seeded with $100,000 each on "
                      "{inception} as a successor to the v1 archive. The same three strategies "
                      "from v1 are used: <b>Max Edge</b> ranks by conditional median minus "
                      "baseline; <b>Bull Case</b> ranks by 90th-percentile forward return; "
                      "<b>Defensive</b> ranks by 10th-percentile floor. The v2 ruleset replaces "
                      "v1's calendar-based turnover with three signal-aware exit rules: "
                      "<b>(1) horizon exit</b> — each position is sold when its forecast horizon "
                      "elapses (calendar-day threshold ≈ horizon × 1.4); "
                      "<b>(2) signal-decay exit</b> — sells a name that has dropped out of the "
                      "current signal list after more than half its horizon has been held; "
                      "<b>(3) stay-long renewal</b> — at horizon end, if the ticker is still in "
                      "the top quartile of current signals by this portfolio's metric, the entry "
                      "date is reset rather than the position being sold. Buying is now "
                      "continuous (no weekly tranche timer): freed cash is deployed on the next "
                      "build. Equal-weight target of ~3.3% per slot and 25% sector cap unchanged "
                      "from v1.",
    "post_note":      "This report reflects the live v2 experiment as of the report date. "
                      "Figures will change with each daily build. Use it as a point-in-time "
                      "snapshot, not a frozen record.",
    "holdings_label": "Current Holdings",
    "footer_label":   "v2 Portfolio Review",
}


def main():
    v2_path = DATA / "portfolio.json"
    if not v2_path.exists():
        raise SystemExit(f"v2 portfolio not found at {v2_path}")
    with open(v2_path, "r", encoding="utf-8") as f:
        port_v2 = json.load(f)

    # Only include strategies that have actually traded — skip empty placeholders
    port_v2 = {k: v for k, v in port_v2.items() if v.get("history")}

    if not port_v2:
        raise SystemExit("v2 portfolio has no history yet — nothing to report")

    port_shaped = {k: _shape(v) for k, v in port_v2.items()}

    today_str = date.today().strftime("%Y-%m-%d")
    out_path = OUT_DIR / f"v2_portfolio_review_{today_str}.pdf"
    build_report(port_shaped, out_path, V2_META)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
