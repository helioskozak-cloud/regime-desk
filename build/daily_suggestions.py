"""
daily_suggestions.py — Analyze questions from the Ask tab and write
suggested interface improvements to data/suggestions/ for your review.

Suggestions are NOT written to wishlist.md automatically.
Review the output file and copy anything you approve into wishlist.md.

Workflow:
  1. In the dashboard, go to Ask ✦ → Daily Question Log → Download JSON
  2. Save the downloaded file to:  regime-desk/data/question_log.json
  3. Run:  python build/daily_suggestions.py  (or run_daily.bat)
  4. Review:  data/suggestions/YYYY-MM-DD.md
  5. Copy approved items into wishlist.md under ## Pending
"""
import json
import re
import datetime
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("anthropic package not installed. Run: pip install anthropic")
    sys.exit(1)

LOG_PATH = Path("data/question_log.json")
SUGGESTIONS_DIR = Path("data/suggestions")
MODEL = "claude-opus-4-7"


def load_log():
    if not LOG_PATH.exists():
        return []
    return json.loads(LOG_PATH.read_text(encoding="utf-8"))


def rank_questions(log):
    """Collapse near-duplicates by normalized key, return sorted by frequency."""
    buckets = {}
    for e in log:
        q = (e.get("q") or "").strip()
        if not q:
            continue
        key = re.sub(r"[^a-z0-9 ]", "", q.lower()).strip()
        if key not in buckets:
            buckets[key] = {"q": q, "count": 0, "dates": set()}
        buckets[key]["count"] += 1
        if e.get("date"):
            buckets[key]["dates"].add(e["date"])

    ranked = sorted(buckets.values(), key=lambda x: x["count"], reverse=True)
    return ranked[:60]


def format_questions(ranked):
    lines = []
    for item in ranked:
        freq = f" (×{item['count']})" if item["count"] > 1 else ""
        lines.append(f"- {item['q']}{freq}")
    return "\n".join(lines)


def call_claude(questions_text, total, days):
    client = anthropic.Anthropic()
    prompt = (
        "You are analyzing questions asked by financial advisors using the Regime Desk dashboard.\n"
        "The dashboard is a self-contained HTML file (no live data feed) showing:\n"
        "  • Market regime (Bull Trend / Bear / Volatile / etc.) with SPY metrics\n"
        "  • Sector rankings by signal edge\n"
        "  • Individual stock signals: edge, p50, distribution, n_obs, horizon\n"
        "  • Historical analog precedents with SPY +20d outcomes\n"
        "  • Cross-asset signals, 7 risk axes, narrative summaries\n"
        "  • Ask ✦ tab: client-side query engine that answers natural-language questions\n\n"
        f"Total questions logged: {total} across {days} day(s). Most frequent first:\n"
        + questions_text
        + "\n\n"
        "Identify 3–5 specific interface features or new views that would directly close the gaps "
        "in what advisors are asking for. Focus on questions the dashboard currently can't answer well, "
        "or that are asked repeatedly (suggesting unmet need).\n\n"
        "Output exactly this format — one suggestion per line, nothing else:\n"
        "**Feature Name** — what it shows and where it lives in the dashboard\n\n"
        "Be concrete: specify the data, chart type, or interaction. No vague suggestions."
    )
    resp = client.messages.create(
        model=MODEL,
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text.strip()


def save_suggestions(suggestions_text, questions_text, today):
    SUGGESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SUGGESTIONS_DIR / f"{today}.md"

    lines = [l.strip() for l in suggestions_text.splitlines() if l.strip().startswith("**")]

    content = f"# Regime Desk — Suggested Improvements\n"
    content += f"Generated: {today}\n\n"
    content += "---\n\n"
    content += "## Suggested Features\n\n"
    content += "_Review these and copy any approved items into wishlist.md under ## Pending._\n\n"

    if lines:
        for line in lines:
            content += f"- {line} — {today}: based on advisor question patterns\n"
    else:
        content += suggestions_text + "\n"

    content += "\n---\n\n"
    content += "## Questions Analyzed\n\n"
    content += questions_text + "\n"

    out_path.write_text(content, encoding="utf-8")
    return out_path, len(lines)


def main():
    today = datetime.date.today().isoformat()

    log = load_log()
    if not log:
        print(f"No data found at {LOG_PATH}.")
        print("Steps:")
        print("  1. Open the dashboard → Ask ✦ tab")
        print("  2. Click 'Download JSON' in the Daily Question Log card")
        print(f"  3. Save the file to:  {LOG_PATH.resolve()}")
        print("  4. Re-run this script")
        return

    total = len(log)
    days = len({e.get("date") for e in log if e.get("date")})
    print(f"Loaded {total} questions across {days} day(s) from {LOG_PATH}")

    ranked = rank_questions(log)
    questions_text = format_questions(ranked)
    print(f"Analyzing {len(ranked)} distinct question patterns...")

    suggestions = call_claude(questions_text, total, days)

    out_path, n = save_suggestions(suggestions, questions_text, today)

    print(f"\nSuggestions written to: {out_path.resolve()}")
    print(f"\n{'='*60}")
    print(suggestions)
    print(f"{'='*60}")
    print(f"\nReview the file above, then copy approved items into wishlist.md")
    print(f"Suggestions are NOT added to wishlist.md automatically.")


if __name__ == "__main__":
    main()
