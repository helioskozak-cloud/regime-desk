"""
build.py — daily orchestrator for the self-evolving Regime Desk dashboard.

Flow:
  1. Read current docs/index.html
  2. Refresh window.SNAPSHOT from data/ (skip cleanly if no data)
  3. Call improver to apply one patch (skip if API key missing)
  4. Validate proposed HTML
  5. Archive old HTML to history/
  6. Atomically promote new HTML
  7. Append to changelog.json

Fail-safe: any exception leaves docs/index.html untouched.
"""
import json
import os
import shutil
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent
HTML_PATH = ROOT / "docs" / "index.html"
HISTORY_DIR = ROOT / "history"
CHANGELOG_PATH = ROOT / "changelog.json"
DATA_DIR = ROOT / "data"

sys.path.insert(0, str(Path(__file__).parent))


def _read_html() -> str:
    with open(HTML_PATH, "r", encoding="utf-8-sig") as f:
        return f.read()


def _write_html(content: str) -> None:
    with open(HTML_PATH, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)


def _archive_html(content: str) -> None:
    HISTORY_DIR.mkdir(exist_ok=True)
    archive_path = HISTORY_DIR / f"{date.today()}_regime_desk.html"
    with open(archive_path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print(f"[build] Archived to {archive_path.name}")


def _append_changelog(note: str, data_refreshed: bool, improved: bool) -> None:
    entries = []
    if CHANGELOG_PATH.exists():
        with open(CHANGELOG_PATH, "r", encoding="utf-8-sig") as f:
            try:
                entries = json.load(f)
            except json.JSONDecodeError:
                entries = []
    entries.append({
        "date": str(date.today()),
        "note": note,
        "data_refreshed": data_refreshed,
        "improved": improved
    })
    with open(CHANGELOG_PATH, "w", encoding="utf-8", newline="\n") as f:
        json.dump(entries, f, indent=2)
    print(f"[build] Changelog updated: {note}")


def _has_data() -> bool:
    for name in ("market_signals.csv", "theme_summary.csv", "spy_state.json"):
        if (DATA_DIR / name).exists():
            return True
    return False


def main():
    print(f"[build] Starting build — {date.today()}")
    original_html = _read_html()
    working_html = original_html
    data_refreshed = False
    improved = False
    note = "data-only refresh"

    # Step 0.5: Compute watchlist signals (tickers not in main scan)
    if (DATA_DIR / "watchlist.txt").exists():
        try:
            from ticker_lookup import main as run_ticker_lookup
            run_ticker_lookup()
        except Exception as exc:
            print(f"[build] WARNING: ticker_lookup failed — {exc}")

    # Step 1: Refresh snapshot from data/
    if _has_data():
        try:
            from snapshot_builder import build_snapshot, inject_snapshot
            snap = build_snapshot()
            refreshed = inject_snapshot(working_html, snap)
            working_html = refreshed
            data_refreshed = True
            print("[build] Snapshot refreshed from data/")
        except Exception as exc:
            print(f"[build] WARNING: Snapshot refresh failed — {exc}")
    else:
        print("[build] No data files found — skipping snapshot refresh")

    # Step 2: Improve via Claude API
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if api_key:
        try:
            from improver import improve
            improved_html, patch_note = improve(working_html)
            working_html = improved_html
            improved = True
            note = patch_note
            print(f"[build] Improvement applied: {patch_note}")
        except Exception as exc:
            print(f"[build] WARNING: Improvement failed — {exc}")
            note = f"improvement failed: {type(exc).__name__}"
    else:
        print("[build] ANTHROPIC_API_KEY not set — skipping improvement")

    # Step 3: Validate
    try:
        from validator import validate
        validate(working_html)
        print("[build] Validation passed")
    except Exception as exc:
        print(f"[build] VALIDATION FAILED — rolling back: {exc}")
        if data_refreshed:
            # Try data-only fallback
            try:
                from snapshot_builder import build_snapshot, inject_snapshot
                from validator import validate
                snap = build_snapshot()
                fallback = inject_snapshot(original_html, snap)
                validate(fallback)
                working_html = fallback
                improved = False
                note = "data-only refresh (improvement rolled back)"
                print("[build] Rolled back to data-only refresh")
            except Exception as exc2:
                print(f"[build] Data-only fallback also failed — keeping original: {exc2}")
                return
        else:
            print("[build] Keeping original HTML unchanged")
            return

    # Step 4: Promote
    if working_html == original_html:
        print("[build] No changes detected — skipping write")
        _append_changelog("no changes", data_refreshed, improved)
        return

    _archive_html(original_html)
    _write_html(working_html)
    _append_changelog(note, data_refreshed, improved)
    print(f"[build] Done — data_refreshed={data_refreshed}, improved={improved}")


if __name__ == "__main__":
    main()
