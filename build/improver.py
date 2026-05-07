"""
improver.py — patch-based self-improvement via Claude API.

Instead of returning full HTML (impossible for large files), Claude returns:
  {"note": "one-line description", "search": "exact substring to find", "replace": "replacement text"}

The patch is applied by Python, keeping output tokens to ~1-2k regardless of HTML size.
"""
import json
import os
import re
from datetime import date
from pathlib import Path

import anthropic

ROOT = Path(__file__).parent.parent
WISHLIST_PATH = ROOT / "wishlist.md"
CHANGELOG_PATH = ROOT / "changelog.json"

MODEL = "claude-opus-4-7"
MAX_TOKENS = 4000


def _read_wishlist() -> str:
    if not WISHLIST_PATH.exists():
        return "No wishlist found."
    with open(WISHLIST_PATH, "r", encoding="utf-8-sig") as f:
        return f.read()


def _read_recent_changelog(n: int = 10) -> str:
    if not CHANGELOG_PATH.exists():
        return "No changelog yet."
    with open(CHANGELOG_PATH, "r", encoding="utf-8-sig") as f:
        entries = json.load(f)
    if not entries:
        return "No entries yet."
    recent = entries[-n:]
    return "\n".join(f"- {e.get('date','?')}: {e.get('note','')}" for e in recent)


def _build_system_prompt(wishlist: str, recent_changelog: str) -> str:
    return f"""You are improving a self-contained single-page market dashboard (docs/index.html).

RULES — follow all of them exactly:
1. Return ONLY a JSON object. No prose, no markdown, no code fences.
2. The JSON must have exactly three string fields:
   - "note": one-line description of the change (max 80 chars)
   - "search": the exact verbatim substring to find in the HTML (include 3-5 lines of context for uniqueness)
   - "replace": the replacement text

3. Make exactly ONE focused improvement per run.
4. The file must remain fully self-contained: no <script src=>, no fetch(), no CDN URLs.
5. All 10 hash views must keep working: #home #regime #sectors #stocks #themes #signals #risks #narrative #analog #methodology
6. Do NOT change the shape or keys of window.SNAPSHOT — it is injected by a build script.
7. Prefer items from the wishlist below. Do NOT repeat anything already in recent changelog.
8. Keep changes small enough to fit in the search/replace patch — do not rewrite whole sections.

WISHLIST:
{wishlist}

RECENT CHANGELOG (do not repeat these):
{recent_changelog}

Return only the JSON object. Example format:
{{"note": "add keyboard shortcut hints to topbar", "search": "<nav id=\\"nav\\"></nav>", "replace": "<nav id=\\"nav\\"></nav><kbd style=\\"...\\">?</kbd>"}}"""


def _apply_patch(html: str, search: str, replace: str) -> str:
    count = html.count(search)
    if count == 0:
        raise ValueError(
            f"Patch 'search' text not found in HTML.\n"
            f"First 80 chars of search: {search[:80]!r}"
        )
    if count > 1:
        raise ValueError(
            f"Patch 'search' text is ambiguous — found {count} occurrences. "
            f"Provide more surrounding context.\nFirst 80 chars: {search[:80]!r}"
        )
    return html.replace(search, replace, 1)


def improve(html_content: str) -> str:
    _BOM = chr(0xFEFF)
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").lstrip(_BOM).strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set or empty")

    client = anthropic.Anthropic(api_key=api_key)
    wishlist = _read_wishlist()
    recent = _read_recent_changelog(10)
    system = _build_system_prompt(wishlist, recent)

    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{
            "role": "user",
            "content": "Here is the current docs/index.html to improve:\n\n" + html_content
        }]
    )

    raw = message.content[0].text.strip()
    # Strip accidental code fences
    if raw.startswith("```"):
        raw = re.sub(r"^```[^\n]*\n", "", raw)
        raw = re.sub(r"\n```$", "", raw.rstrip())

    try:
        patch = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Claude returned invalid JSON: {exc}\nRaw response:\n{raw[:500]}") from exc

    for field in ("note", "search", "replace"):
        if field not in patch:
            raise ValueError(f"Patch missing required field '{field}'. Got keys: {list(patch.keys())}")

    improved = _apply_patch(html_content, patch["search"], patch["replace"])

    evolved_comment = f"<!-- evolved: {date.today()} | {patch['note']} -->"
    improved = improved.rstrip()
    if improved.endswith("</html>"):
        improved = improved[:-len("</html>")] + evolved_comment + "\n</html>"
    else:
        improved = improved + "\n" + evolved_comment + "\n</html>"

    return improved, patch["note"]
