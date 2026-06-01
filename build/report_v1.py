"""
report_v1.py — generates an advisor-review style PDF for the archived v1
paper portfolios. Includes performance summary, holdings snapshot at the
archive date, complete trade log, and a daily risk profile chart.

Output: reports/v1_portfolio_review_<date>.pdf
"""
import json
import math
import statistics
from datetime import datetime, date
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, String, Line, PolyLine
from reportlab.graphics import renderPDF

ROOT = Path(__file__).parent.parent
DATA = ROOT / "data"
OUT_DIR = ROOT / "reports"
OUT_DIR.mkdir(exist_ok=True)

# ── Brand palette (printer-friendly: avoid pure black backgrounds) ──────────
COL_HEAD       = colors.HexColor("#1a2333")
COL_ACCENT     = colors.HexColor("#1f4e79")
COL_TEXT       = colors.HexColor("#222222")
COL_MUTED      = colors.HexColor("#666666")
COL_GREEN      = colors.HexColor("#2e7d32")
COL_RED        = colors.HexColor("#c62828")
COL_TAB_BG     = colors.HexColor("#f3f5f8")
COL_TAB_ALT    = colors.HexColor("#fbfbfd")
COL_BORDER     = colors.HexColor("#cccccc")
COL_DIVIDER    = colors.HexColor("#bbbbbb")


def _color_val(v: float) -> colors.Color:
    return COL_GREEN if v is None or v >= 0 else COL_RED


def _money(v) -> str:
    if v is None:
        return "—"
    return f"${v:,.2f}"


def _pct(v) -> str:
    if v is None:
        return "—"
    return f"{v:+.2f}%"


def _compute_risk_profile(history: list) -> dict:
    """Daily-return based risk stats."""
    if len(history) < 5:
        return {
            "vol_daily": None, "vol_annual": None,
            "sharpe": None, "max_dd": None, "max_dd_date": None,
            "avg_return": None, "win_rate": None,
        }
    rets = []
    prev = history[0]["total_value"]
    for h in history[1:]:
        cur = h["total_value"]
        if prev:
            rets.append(cur / prev - 1)
        prev = cur
    if not rets:
        return {}
    avg = statistics.fmean(rets)
    sd = statistics.pstdev(rets) if len(rets) > 1 else 0.0
    sharpe = (avg / sd) * math.sqrt(252) if sd > 0 else None

    # Max drawdown
    peak = history[0]["total_value"]
    max_dd = 0.0
    max_dd_date = ""
    for h in history:
        v = h["total_value"]
        if v > peak:
            peak = v
        dd = (v / peak - 1) if peak else 0
        if dd < max_dd:
            max_dd = dd
            max_dd_date = h["date"]
    win_rate = sum(1 for r in rets if r > 0) / len(rets) if rets else 0
    return {
        "vol_daily":   sd * 100,
        "vol_annual":  sd * math.sqrt(252) * 100,
        "sharpe":      sharpe,
        "max_dd":      max_dd * 100,
        "max_dd_date": max_dd_date,
        "avg_return":  avg * 100,
        "win_rate":    win_rate * 100,
    }


def _equity_curve_drawing(history: list, width=6.0*inch, height=2.0*inch,
                          color=colors.HexColor("#1f4e79")) -> Drawing:
    d = Drawing(width, height)
    if len(history) < 2:
        return d
    vals = [h.get("return_pct", 0) for h in history]
    n = len(vals)
    mn = min(vals + [0])
    mx = max(vals + [0])
    pad = max((mx - mn) * 0.10, 1.0)
    mn -= pad
    mx += pad
    rng = mx - mn or 1
    pl, pr, pt, pb = 36, 12, 14, 22
    pw = width - pl - pr
    ph = height - pt - pb

    def x(i): return pl + i / max(n - 1, 1) * pw
    def y(v): return pt + ph - (v - mn) / rng * ph

    # Zero line
    if mn < 0 < mx:
        d.add(Line(pl, y(0), pl + pw, y(0), strokeColor=COL_MUTED,
                   strokeDashArray=[2, 2], strokeWidth=0.5))
    # Y gridlines + labels (quartiles)
    for q in (0.25, 0.5, 0.75):
        gv = mn + rng * q
        gy = y(gv)
        d.add(Line(pl, gy, pl + pw, gy, strokeColor=colors.HexColor("#eeeeee"),
                   strokeWidth=0.4))
        d.add(String(pl - 3, gy - 3, f"{gv:+.0f}%", fontSize=6.5,
                     fillColor=COL_MUTED, textAnchor="end"))
    # X labels (start, middle, end)
    for idx in (0, n // 2, n - 1):
        if 0 <= idx < n:
            label = history[idx]["date"][5:]
            d.add(String(x(idx), pt + ph + 12, label, fontSize=6.5,
                         fillColor=COL_MUTED, textAnchor="middle"))
    # Curve
    pts = []
    for i, v in enumerate(vals):
        pts.extend([x(i), y(v)])
    if len(pts) >= 4:
        d.add(PolyLine(pts, strokeColor=color, strokeWidth=1.4,
                       strokeLineJoin=1, strokeLineCap=1))
    # End marker
    d.add(Rect(x(n - 1) - 1.5, y(vals[-1]) - 1.5, 3, 3,
               strokeColor=color, fillColor=color))
    return d


# ── Document builder ────────────────────────────────────────────────────────
def build_report(port_v1: dict, out_path: Path):
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        leftMargin=0.6 * inch,
        rightMargin=0.6 * inch,
        topMargin=0.55 * inch,
        bottomMargin=0.6 * inch,
        title="Regime Desk — v1 Portfolio Review",
        author="Regime Desk",
    )

    styles = getSampleStyleSheet()
    h_title = ParagraphStyle("h_title", parent=styles["Title"],
                              fontSize=20, leading=24, textColor=COL_HEAD,
                              spaceAfter=4, fontName="Helvetica-Bold")
    h_subtitle = ParagraphStyle("h_sub", parent=styles["Normal"],
                                 fontSize=10, textColor=COL_MUTED,
                                 spaceAfter=14)
    h_section = ParagraphStyle("h_section", parent=styles["Heading1"],
                                fontSize=13, leading=16, textColor=COL_ACCENT,
                                spaceBefore=10, spaceAfter=6,
                                fontName="Helvetica-Bold")
    h_sub2 = ParagraphStyle("h_sub2", parent=styles["Heading2"],
                             fontSize=11, leading=14, textColor=COL_HEAD,
                             spaceBefore=8, spaceAfter=4,
                             fontName="Helvetica-Bold")
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=9.5,
                           leading=13, textColor=COL_TEXT)
    body_small = ParagraphStyle("body_small", parent=styles["Normal"],
                                 fontSize=8.5, leading=11, textColor=COL_TEXT)
    body_muted = ParagraphStyle("body_muted", parent=styles["Normal"],
                                 fontSize=8.5, leading=11, textColor=COL_MUTED)
    footer_st = ParagraphStyle("footer", parent=styles["Normal"], fontSize=7,
                                leading=9, textColor=COL_MUTED,
                                alignment=TA_CENTER)

    story = []

    # ── Title page header ──────────────────────────────────────────────────
    story.append(Paragraph("Paper Portfolio Review — v1 Archive", h_title))
    today = date.today().strftime("%B %d, %Y")
    inception = min((p.get("inception_date", "") for p in port_v1.values()), default="")
    archive_date = max((p.get("archive_date", "") for p in port_v1.values()), default="")
    story.append(Paragraph(
        f"Report generated {today} · Experiment {inception} to {archive_date} · "
        "Simulated only — not real money", h_subtitle))

    story.append(Paragraph("Executive Summary", h_section))
    summary_lines = []
    for key, p in port_v1.items():
        ret = p["history"][-1]["return_pct"] if p["history"] else 0
        cash = p["history"][-1]["cash"] if p["history"] else p.get("cash", 0)
        n_days = len(p["history"])
        n_txns = len(p["transactions"])
        summary_lines.append([
            p.get("name", key),
            p.get("label", ""),
            _money(p["history"][-1]["total_value"] if p["history"] else 0),
            _pct(ret),
            f"{n_days} days",
            f"{n_txns} trades",
        ])

    summary_tbl = Table(
        [["Strategy", "Description", "Final Value", "Return", "Track", "Activity"]] + summary_lines,
        colWidths=[1.0*inch, 2.3*inch, 1.0*inch, 0.75*inch, 0.85*inch, 0.85*inch],
        repeatRows=1,
    )
    ts = [
        ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
        ("BACKGROUND", (0, 0), (-1, 0), COL_HEAD),
        ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
        ("FONTSIZE",   (0, 0), (-1, -1), 9),
        ("ALIGN",      (2, 1), (-1, -1), "RIGHT"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COL_TAB_BG, COL_TAB_ALT]),
        ("BOX",        (0, 0), (-1, -1), 0.5, COL_BORDER),
        ("INNERGRID",  (0, 0), (-1, -1), 0.25, COL_BORDER),
        ("LEFTPADDING",   (0, 0), (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 5),
        ("TOPPADDING",    (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]
    # Color the return cells
    for i, (_, _, _, ret_str, *_rest) in enumerate(summary_lines, start=1):
        ts.append(("TEXTCOLOR", (3, i), (3, i),
                   _color_val(float(ret_str.replace("%", "").replace("+", "")))))
        ts[-1] = ts[-1]  # noqa
    summary_tbl.setStyle(TableStyle(ts))
    story.append(summary_tbl)

    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "Methodology: Three paper portfolios were seeded with $100,000 each on "
        f"{inception}. All three pulled candidate names from the daily Regime Desk "
        "analog-matching scan but ranked them differently: <b>Max Edge</b> by "
        "conditional median minus baseline; <b>Bull Case</b> by 90th-percentile "
        "forward return; <b>Defensive</b> by 10th-percentile floor. Trades were "
        "executed at the next available close, equal-weighted to about 3.3% per slot "
        "with a 25% sector cap. Cash was redeployed in weekly tranches of 15% of "
        "total value, with a quarterly (63-day) turnover that rotated out 10% of "
        "holdings.",
        body))
    story.append(Spacer(1, 14))
    story.append(Paragraph(
        "Note: This v1 ruleset has been retired in favor of a v2 ruleset "
        "(horizon-based exits, signal-decay sells, stay-long renewals, and "
        "continuous buying). The figures in this report reflect the original "
        "experiment as it ran.",
        body_muted))

    # ── Per-portfolio sections ─────────────────────────────────────────────
    for key, p in port_v1.items():
        story.append(PageBreak())
        story.append(Paragraph(f"{p.get('name', key)} — Detailed Review", h_section))
        story.append(Paragraph(p.get("label", ""), body_muted))
        story.append(Spacer(1, 8))

        # Performance card row
        history = p.get("history", [])
        if history:
            last = history[-1]
            risk = _compute_risk_profile(history)
            best_day = max(history, key=lambda h: h["return_pct"])
            worst_day = min(history, key=lambda h: h["return_pct"])

            stats_rows = [
                ["Starting capital", _money(p.get("initial_cash", 100000))],
                ["Final value",      _money(last["total_value"])],
                ["Total return",     _pct(last["return_pct"])],
                ["Days tracked",     str(len(history))],
                ["Trades executed",  str(len(p.get("transactions", [])))],
                ["Annualized vol",   f"{risk.get('vol_annual', 0):.1f}%" if risk.get("vol_annual") is not None else "—"],
                ["Daily vol",        f"{risk.get('vol_daily', 0):.2f}%"  if risk.get("vol_daily")  is not None else "—"],
                ["Sharpe (rf=0)",    f"{risk.get('sharpe', 0):.2f}"      if risk.get("sharpe")     is not None else "—"],
                ["Max drawdown",     f"{risk.get('max_dd', 0):.2f}% on {risk.get('max_dd_date','')}" if risk.get("max_dd") is not None else "—"],
                ["Best single day",  f"{best_day['return_pct']:+.2f}% on {best_day['date']}"],
                ["Worst single day", f"{worst_day['return_pct']:+.2f}% on {worst_day['date']}"],
                ["Up days %",        f"{risk.get('win_rate', 0):.0f}%"   if risk.get("win_rate")   is not None else "—"],
                ["Final cash",       _money(last["cash"])],
                ["Final positions",  f"{last['n_positions']}"],
            ]
            stats_tbl = Table(stats_rows, colWidths=[1.6*inch, 1.7*inch])
            stats_tbl.setStyle(TableStyle([
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (0, -1), COL_MUTED),
                ("TEXTCOLOR", (1, 0), (1, -1), COL_TEXT),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("ROWBACKGROUNDS", (0, 0), (-1, -1), [COL_TAB_BG, COL_TAB_ALT]),
                ("BOX", (0, 0), (-1, -1), 0.5, COL_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, COL_BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 5),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))

            # Equity curve chart
            curve = _equity_curve_drawing(history, width=3.4*inch, height=2.6*inch,
                                          color=COL_ACCENT)
            row_tbl = Table([[stats_tbl, curve]], colWidths=[3.5*inch, 3.7*inch])
            row_tbl.setStyle(TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ]))
            story.append(row_tbl)
            story.append(Spacer(1, 6))
            story.append(Paragraph(
                f"Equity curve · {history[0]['date']} to {history[-1]['date']}",
                body_muted))
            story.append(Spacer(1, 14))

        # Holdings snapshot (at archive)
        holdings = p.get("holdings", [])
        if holdings:
            story.append(Paragraph("Holdings at Archive Date", h_sub2))
            h_rows = sorted(holdings, key=lambda x: -(x.get("current_value", 0) or 0))
            tbl_data = [["Ticker", "Sector", "Horizon", "Entry", "Shares", "Cost", "Value", "P&L"]]
            for h in h_rows:
                pnl = h.get("pnl_pct", 0) or 0
                tbl_data.append([
                    h.get("ticker", "?"),
                    (h.get("sector") or "—")[:20],
                    h.get("horizon", "—"),
                    h.get("entry_date", "—"),
                    f"{h.get('shares', 0):.2f}",
                    _money(h.get("shares", 0) * h.get("entry_price", 0)),
                    _money(h.get("current_value", 0)),
                    f"{pnl:+.2f}%",
                ])
            hold_tbl = Table(tbl_data,
                              colWidths=[0.7*inch, 1.4*inch, 0.6*inch, 0.85*inch,
                                         0.7*inch, 0.85*inch, 0.85*inch, 0.7*inch],
                              repeatRows=1)
            hs = [
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 0), (-1, 0), COL_HEAD),
                ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COL_TAB_BG, COL_TAB_ALT]),
                ("BOX", (0, 0), (-1, -1), 0.4, COL_BORDER),
                ("INNERGRID", (0, 0), (-1, -1), 0.2, COL_BORDER),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
            # Color the PnL column
            for i, h in enumerate(h_rows, start=1):
                hs.append(("TEXTCOLOR", (7, i), (7, i), _color_val(h.get("pnl_pct", 0) or 0)))
            hold_tbl.setStyle(TableStyle(hs))
            story.append(hold_tbl)
            story.append(Spacer(1, 10))

    # ── Trade log section per portfolio ────────────────────────────────────
    for key, p in port_v1.items():
        story.append(PageBreak())
        story.append(Paragraph(f"{p.get('name', key)} — Complete Trade Log",
                                h_section))
        story.append(Paragraph(
            f"{len(p.get('transactions', []))} transactions in chronological order",
            body_muted))
        story.append(Spacer(1, 6))
        txns = p.get("transactions", [])
        if not txns:
            story.append(Paragraph("No transactions recorded.", body))
            continue
        rows = [["Date", "Action", "Ticker", "Reason", "Shares", "Price", "Value", "P&L"]]
        for t in txns:
            pnl = t.get("pnl_pct")
            rows.append([
                t.get("date", "—"),
                (t.get("action", "") or "").upper(),
                t.get("ticker", "—"),
                (t.get("reason") or "—")[:18],
                f"{t.get('shares', 0):.2f}",
                _money(t.get("price", 0)),
                _money(t.get("value", 0)),
                f"{pnl:+.2f}%" if pnl is not None else "—",
            ])
        log_tbl = Table(rows,
                         colWidths=[0.85*inch, 0.55*inch, 0.65*inch, 1.0*inch,
                                    0.7*inch, 0.8*inch, 0.85*inch, 0.65*inch],
                         repeatRows=1)
        ls = [
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 0), (-1, 0), COL_HEAD),
            ("ALIGN", (4, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COL_TAB_BG, COL_TAB_ALT]),
            ("BOX", (0, 0), (-1, -1), 0.4, COL_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, COL_BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]
        # Color action column + P&L column
        for i, t in enumerate(txns, start=1):
            act = t.get("action", "")
            if act == "buy":
                ls.append(("TEXTCOLOR", (1, i), (1, i), COL_GREEN))
            elif act == "sell":
                ls.append(("TEXTCOLOR", (1, i), (1, i), COL_RED))
            pnl = t.get("pnl_pct")
            if pnl is not None:
                ls.append(("TEXTCOLOR", (7, i), (7, i), _color_val(pnl)))
        log_tbl.setStyle(TableStyle(ls))
        story.append(log_tbl)

    # ── Daily risk profile per portfolio ───────────────────────────────────
    for key, p in port_v1.items():
        history = p.get("history", [])
        if len(history) < 5:
            continue
        story.append(PageBreak())
        story.append(Paragraph(
            f"{p.get('name', key)} — Daily Risk Profile", h_section))
        story.append(Paragraph(
            "Daily snapshots of total value, return, position count, and cash share. "
            "Used for drawdown attribution and pacing review.",
            body_muted))
        story.append(Spacer(1, 6))

        rows = [["Date", "Total Value", "Return", "Daily Δ", "Positions", "Cash", "Cash %"]]
        prev_value = None
        for h in history:
            v = h["total_value"]
            daily = ((v / prev_value) - 1) * 100 if prev_value else 0.0
            cash_pct = (h["cash"] / v * 100) if v else 0.0
            rows.append([
                h["date"],
                _money(v),
                _pct(h["return_pct"]),
                _pct(daily) if prev_value else "—",
                str(h["n_positions"]),
                _money(h["cash"]),
                f"{cash_pct:.1f}%",
            ])
            prev_value = v
        risk_tbl = Table(rows,
                          colWidths=[0.85*inch, 1.0*inch, 0.75*inch, 0.75*inch,
                                     0.7*inch, 1.0*inch, 0.7*inch],
                          repeatRows=1)
        rs = [
            ("FONTSIZE", (0, 0), (-1, -1), 7.5),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("BACKGROUND", (0, 0), (-1, 0), COL_HEAD),
            ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [COL_TAB_BG, COL_TAB_ALT]),
            ("BOX", (0, 0), (-1, -1), 0.4, COL_BORDER),
            ("INNERGRID", (0, 0), (-1, -1), 0.2, COL_BORDER),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 1.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5),
        ]
        # Color the daily return + total return cols
        prev_v = None
        for i, h in enumerate(history, start=1):
            rs.append(("TEXTCOLOR", (2, i), (2, i), _color_val(h["return_pct"])))
            if prev_v is not None:
                rs.append(("TEXTCOLOR", (3, i), (3, i),
                           _color_val((h["total_value"] / prev_v) - 1)))
            prev_v = h["total_value"]
        risk_tbl.setStyle(TableStyle(rs))
        story.append(risk_tbl)

    # ── Build & footer ─────────────────────────────────────────────────────
    def _page_footer(canv, doc):
        canv.saveState()
        canv.setFont("Helvetica", 7)
        canv.setFillColor(COL_MUTED)
        page_text = f"Page {canv.getPageNumber()}"
        canv.drawString(0.6 * inch, 0.35 * inch,
                        "Regime Desk · v1 Portfolio Review · Simulated only — not investment advice")
        canv.drawRightString(letter[0] - 0.6 * inch, 0.35 * inch, page_text)
        canv.restoreState()

    doc.build(story, onFirstPage=_page_footer, onLaterPages=_page_footer)


def main():
    v1_path = DATA / "portfolio_v1.json"
    if not v1_path.exists():
        raise SystemExit(f"v1 archive not found at {v1_path}")
    with open(v1_path, "r", encoding="utf-8") as f:
        port_v1 = json.load(f)

    # Reshape to match the renderer's expected schema
    def _shape(p):
        return {
            "name":            p.get("name", ""),
            "label":           p.get("label", ""),
            "inception_date":  p.get("inception_date", ""),
            "archive_date":    p.get("archive_date", ""),
            "initial_cash":    p.get("initial_cash", 100000),
            "cash":            p.get("cash", 0),
            "history":         p.get("history", []),
            "transactions":    p.get("transactions", []),
            "holdings":        [{"ticker": k, **v} for k, v in p.get("holdings", {}).items()],
        }

    port_shaped = {k: _shape(v) for k, v in port_v1.items()}

    today_str = date.today().strftime("%Y-%m-%d")
    out_path = OUT_DIR / f"v1_portfolio_review_{today_str}.pdf"
    build_report(port_shaped, out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()
