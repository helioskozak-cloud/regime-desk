"""
daily_suggestions.py — Analyze questions from the Ask tab and suggest
interface improvements. Run daily; updates wishlist.md Pending section.

Workflow:
  1. In the dashboard, go to Ask ✦ → Daily Question Log → Download JSON
  2. Save the downloaded file to:  regime-desk/data/question_log.json
  3. Run:  python build/daily_suggestions.py
     (or double-click run_daily.bat)

Output: 3-5 new items prepended to the Pending section of wishlist.md,
        keyed to today's date so re-running the same day is idempotent.
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
WISHLIST_PATH = Path("wishlist.md")
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


def call_claude(questions_text):
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
        "Questions asked by advisors (most frequent first):\n"
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


def update_wishlist(suggestions_text, today):
    wishlist = WISHLIST_PATH.read_text(encoding="utf-8")

    marker = f"AI suggestions {today}"
    if marker in wishlist:
        print(f"Suggestions for {today} already present in wishlist.md — skipping write.")
        return 0

    lines = [l.strip() for l in suggestions_text.splitlines() if l.strip().startswith("**")]
    if not lines:
        print("WARNING: Claude returned no parseable suggestions. Raw output:")
        print(suggestions_text)
        return 0

    items = "\n".join(
        f"- {line} — {today}: based on advisor question patterns"
        for line in lines
    )
    block = f"\n<!-- {marker} -->\n{items}\n"

    updated = wishlist.replace("## Pending\n", "## Pending\n" + block, 1)
    WISHLIST_PATH.write_text(updated, encoding="utf-8")
    return len(lines)


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
    print(f"Analyzing {len(ranked)} distinct question patterns...\n")

    suggestions = call_claude(questions_text)
    print("Claude suggestions:\n")
    print(suggestions)
    print()

    n = update_wishlist(suggestions, today)
    if n:
        print(f"Wrote {n} suggestion(s) to wishlist.md Pending section.")


if __name__ == "__main__":
    main()
