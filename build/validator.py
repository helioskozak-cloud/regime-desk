"""
validator.py — static smoke-tests for the proposed index.html.

Checks:
  1. window.SNAPSHOT present
  2. All 10 view hashes referenced
  3. No external script tags (<script src=)
  4. No fetch( or XMLHttpRequest calls
  5. No ESM URL imports (import ... from 'http)
  6. Minimum file size sanity check
"""
import re


REQUIRED_HASHES = [
    "#home", "#regime", "#sectors", "#stocks", "#themes",
    "#signals", "#risks", "#narrative", "#analog", "#methodology"
]

MIN_SIZE = 5_000


def validate(html: str) -> None:
    errors = []

    if len(html) < MIN_SIZE:
        errors.append(f"File too small: {len(html)} bytes (min {MIN_SIZE})")

    if "window.SNAPSHOT" not in html:
        errors.append("window.SNAPSHOT not found")

    for h in REQUIRED_HASHES:
        if h not in html:
            errors.append(f"View hash '{h}' not referenced")

    if re.search(r'<script[^>]+src\s*=', html, re.IGNORECASE):
        errors.append("External <script src=...> found — file must be self-contained")

    if "fetch(" in html:
        errors.append("fetch() call found — file must be self-contained")

    if "XMLHttpRequest" in html:
        errors.append("XMLHttpRequest found — file must be self-contained")

    if re.search(r"import\s+.*from\s+['\"]https?://", html):
        errors.append("ESM URL import found — file must be self-contained")

    if errors:
        raise ValueError("Validation failed:\n" + "\n".join(f"  - {e}" for e in errors))
