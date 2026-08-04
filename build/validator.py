"""
validator.py — static smoke-tests for the proposed index.html.

Checks:
  1. window.SNAPSHOT present
  2. Every routable view has a mount point
  3. No external script tags (<script src=)
  4. No fetch( or XMLHttpRequest calls
  5. No ESM URL imports (import ... from 'http)
  6. Minimum file size sanity check
"""
import re


# Must track the page's own VIEWS array. Anything listed here that the page no
# longer mounts fails validation, build.py rolls back, nothing stages, and the run
# still goes green — so a stale entry here freezes the dashboard silently rather
# than reporting an error. Ten renderers were deleted 2026-08-04 as unreachable;
# this list went from thirteen names (twelve of them already dead, and missing
# three of the four live ones) to exactly what VIEWS routes.
REQUIRED_VIEWS = ["home", "analysis", "bubble", "news"]

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

    # The News tab loads the vendored SheetJS on demand by building a <script>
    # element, so the literal-tag check above never sees it. That is fine while
    # the URL is same-origin — docs/vendor/ ships in this repo — and not fine
    # the moment it points at a CDN, which is exactly the dependency the
    # self-contained rule exists to prevent. Check the assignments themselves so
    # the guarantee survives being routed around.
    for src in re.findall(r"""\.src\s*=\s*['"]([^'"]+)['"]""", html):
        if src.startswith("http://localhost"):
            continue
        if "://" in src or src.startswith("//"):
            errors.append(
                f"script/element .src set to a cross-origin URL — vendor it "
                f"under docs/ and use a relative path instead: {src}")

    # fetch() to localhost is allowed (local API server). Same-origin
    # relative paths are also allowed — they resolve against the Pages
    # site origin, no third-party data flow. The cloud-tunnel discovery
    # code fetches api_endpoint.json, which is a relative path.
    #
    # news-desk's own data files are allowed too. The News tab was MERGED in on
    # 2026-07-29 rather than framed, and the point of merging is that the
    # headlines stay live — news-desk republishes them every five minutes, while
    # this page rebuilds a few times a day. Baking them in would make the tab
    # stale by design, which is why the tab fetches these two absolute URLs at
    # runtime. (Until 2026-07-31 they were rewritten into a port of news-desk's
    # own page by build/build_news_tab.py; the tab is now a native view that
    # reads the same JSON, so the URLs are written literally in index.html.)
    #
    # This check rolled the whole build back for a full day because of it: every
    # run since the merge failed validation, kept the original HTML, and left
    # the dashboard frozen at 2026-07-29 while the data underneath it updated
    # normally. Narrow allowance on purpose — this is the one origin the page is
    # designed to read, not a general licence to fetch.
    NEWS_DESK_DATA = "https://helioskozak-cloud.github.io/news-desk/data/"

    def _is_external_fetch(u: str) -> bool:
        if u.startswith("http://localhost"):
            return False
        if u.startswith(NEWS_DESK_DATA):
            return False
        # Relative URL — no scheme, no protocol-relative leading //
        if "://" not in u and not u.startswith("//"):
            return False
        return True
    fetch_calls = re.findall(r"fetch\(['\"]([^'\"]*)['\"]", html)
    bad_fetch = [u for u in fetch_calls if _is_external_fetch(u)]
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
