"""Export api_server.py's _SECTOR_MAP as a public data/sector_map.json.

_SECTOR_MAP is regime-desk's real ticker -> theme classification (currently
used only by the local API server for on-demand ticker lookups). It was
never published anywhere finvisible or another consumer could fetch it from,
so finvisible fell back to its own coarser, independently-derived classifier
- which buckets nearly all ETFs into a generic "ETF" label that can't be
cross-referenced against regime-desk's own theme names at all.

Run manually (or from CI) whenever _SECTOR_MAP changes:
    python scripts/export_sector_map.py
"""
import ast
import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent
API_SERVER = REPO_ROOT / "api_server.py"
OUT_FILE = REPO_ROOT / "data" / "sector_map.json"


def extract_sector_map() -> dict[str, str]:
    source = API_SERVER.read_text(encoding="utf-8")
    match = re.search(r"_SECTOR_MAP\s*=\s*(\{.*?\n\})", source, re.DOTALL)
    if not match:
        raise RuntimeError("Could not find _SECTOR_MAP literal in api_server.py")
    # ast.literal_eval, not exec/eval - the dict is untrusted-ish input in
    # principle (a source file), safe parsing avoids running arbitrary code.
    return ast.literal_eval(match.group(1))


def main() -> None:
    sector_map = extract_sector_map()
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(
        json.dumps(sector_map, indent=1, sort_keys=True),
        encoding="utf-8",
    )
    print(f"Wrote {len(sector_map)} tickers to {OUT_FILE}")


if __name__ == "__main__":
    main()
