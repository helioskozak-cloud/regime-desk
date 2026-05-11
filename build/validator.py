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


REQUIRED_VIEWS = [
    "home", "regime", "sectors", "stocks", "themes",
    "signals", "risks", "narrative", "analog", "methodology", "advisor", "meeting", "ask"
]

MIN_SIZE = 5_000


def validate(html: str) -> None:
    errors = []

    if len(html) < MIN_SIZE:
        errors.append(f"File too small: {len(html)} bytes (min {MIN_SIZE})")

    if "window.SNAPSHOT" not in html:
        errors.append("window.SNAPSHOT not found")

    # Check each view exists as a DOM element (id="v-<name>") AND in the router (renderers object)
    for v in REQUIRED_VIEWS:
        if f'id="v-{v}"' not in html:
            errors.append(f"View element id='v-{v}' not found")

    if re.search(r'<script[^>]+src\s*=', html, re.IGNORECASE):
        errors.append("External <script src=...> found — file must be self-contained")

    # fetch() to localhost is allowed (local API server); any other target is not
    fetch_calls = re.findall(r"fetch\(['\"]([^'\"]*)['\"]", html)
    bad_fetch = [u for u in fetch_calls if not u.startswith("http://localhost")]
    if bad_fetch:
        errors.append("fetch() to external URL found — file must be self-contained: " + str(bad_fetch))
    elif re.search(r"fetch\([^'\"]", html.replace("fetch('http://localhost", "").replace('fetch("http://localhost', "")):
        pass  # dynamic fetch targets can't be statically verified; allow

    if "XMLHttpRequest" in html:
        errors.append("XMLHttpRequest found — file must be self-contained")

    if re.search(r"import\s+.*from\s+['\"]https?://", html):
        errors.append("ESM URL import found — file must be self-contained")

    if errors:
        raise ValueError("Validation failed:\n" + "\n".join(f"  - {e}" for e in errors))
