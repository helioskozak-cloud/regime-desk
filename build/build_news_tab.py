"""
build_news_tab.py — merge news-desk's page into regime-desk's News view.

WHY A GENERATOR AND NOT A HAND-COPY. news-desk's HTML shell changes rarely
(12 commits in 60 days against 16,000 data commits — its 5-minute cron only
writes docs/data/*.json), but "rarely" is not "never". A hand-copy would drift
silently the first time someone edited news-desk. Re-running this re-ports it.

WHAT IT TRANSFORMS, and why each is necessary:

  CSS globals   news-desk styles `html,body`, `*`, `:root` and the scrollbar.
                Copied verbatim those would restyle the whole of regime-desk.
                `:root` is re-scoped to #v-news so its variables still resolve
                inside the tab; the rest are scoped or dropped.

  Everything    Every other selector is prefixed with #v-news. Not strictly
  else          required — the collision audit found exactly one shared class
                name (`active`) and both use it only in compound selectors —
                but prefixing means a future news-desk class cannot silently
                restyle regime-desk.

  fetch URLs    news-desk fetches 'data/headlines.json' relatively. Inside
                regime-desk that resolves to regime-desk's own /data/, which
                exists and contains something else entirely — a wrong answer
                rather than an error. Rewritten to absolute.

  boot          news-desk's script runs setInterval and paints on load. Inside
                regime-desk it would run whether or not the tab is open, against
                elements that do not exist yet. Wrapped in a function called by
                the view's postrender hook.

  handlers      Wrapping makes its functions local, but five are referenced by
                inline onclick attributes. Those are re-exposed on window. The
                audit found zero collisions with regime-desk's 93 globals.

Run:  python build/build_news_tab.py
"""
from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGET = ROOT / "docs" / "index.html"
SOURCE_URL = "https://helioskozak-cloud.github.io/news-desk/"
LOCAL = ROOT.parent / "news-desk" / "docs" / "index.html"

FEED = "https://helioskozak-cloud.github.io/news-desk/data"
SCOPE = "#v-news"

# Markers in regime-desk's index.html between which everything is generated.
CSS_START = "/* @@NEWS-TAB-CSS-START@@ */"
CSS_END = "/* @@NEWS-TAB-CSS-END@@ */"
JS_START = "// @@NEWS-TAB-JS-START@@"
JS_END = "// @@NEWS-TAB-JS-END@@"

# Referenced by inline onclick= in news-desk's markup, so they must stay
# reachable from the global scope after wrapping.
HANDLERS = ["switchView", "render", "clearFilters", "pickTicker",
            "_pasteWatchlist", "tickerClick"]

# news-desk rules that style the whole document. Left alone they would apply to
# regime-desk as well.
GLOBAL_SELECTORS = ("html", "body", "*", ":root", "::-webkit-scrollbar",
                    "::selection", ":focus")


def source_html(offline: bool) -> str:
    if offline:
        if not LOCAL.is_file():
            sys.exit(f"--offline given but {LOCAL} does not exist")
        print(f"reading {LOCAL}")
        return LOCAL.read_text(encoding="utf-8")
    print(f"fetching {SOURCE_URL}")
    with urllib.request.urlopen(SOURCE_URL, timeout=30) as r:
        return r.read().decode("utf-8")


def scope_css(css: str) -> str:
    """Prefix every rule with #v-news, handling the document-wide ones."""
    # Comments are stripped FIRST. Left in, a comment immediately before a rule
    # is captured as part of that rule's selector, and the prefix lands in
    # front of the comment instead of the selector — producing a rule that
    # parses but can never match. Silent dead CSS is worse than a crash.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out: list[str] = []
    pos = 0
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = m.group(1).strip()
        body = m.group(2).strip()
        out.append(css[pos:m.start()])
        pos = m.end()
        if not selector or selector.startswith("@"):
            # at-rule header (@media …) — keep, its inner rules get handled
            out.append(m.group(0))
            continue
        parts = []
        for sel in (s.strip() for s in selector.split(",")):
            if not sel:
                continue
            if sel == ":root" or sel in ("html", "body", "html,body", "*"):
                # Variables and resets belong to the tab, not the document.
                parts.append(SCOPE)
            elif sel.startswith("::-webkit-scrollbar") or sel.startswith("::"):
                parts.append(f"{SCOPE} {sel}")
            elif sel.startswith("body.nd-embed"):
                # The embed overrides were for the iframe. Inside a real merge
                # they are the normal case, so keep them as plain tab rules.
                parts.append(sel.replace("body.nd-embed", SCOPE, 1).strip() or SCOPE)
            elif sel.startswith(SCOPE):
                parts.append(sel)
            else:
                parts.append(f"{SCOPE} {sel}")
        out.append(",".join(parts) + "{" + body + "}")
    out.append(css[pos:])
    return "".join(out)


def main() -> None:
    offline = "--offline" in sys.argv
    src = source_html(offline)

    styles = re.findall(r"<style[^>]*>(.*?)</style>", src, re.S)
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", src, re.S)
    if not styles or not scripts:
        sys.exit("could not find <style>/<script> in the source page")

    # Anchored to the start of a line. An unanchored <body[^>]*> also matches
    # the literal "<body>" written inside a CSS comment, which silently
    # captured the stylesheet instead of the markup the first time this ran.
    body = re.search(r"^<body[^>]*>(.*?)</body>", src, re.S | re.M)
    if not body:
        sys.exit("could not find <body> at the start of a line in the source page")
    markup = body.group(1)
    # Drop every <script> and <style> from the markup — they are emitted
    # separately, into regime-desk's own blocks.
    markup = re.sub(r"<script[\s\S]*?</script>", "", markup)
    markup = re.sub(r"<style[\s\S]*?</style>", "", markup)
    markup = markup.strip()

    css = scope_css("\n".join(styles))

    js = "\n".join(scripts)
    js = js.replace("fetch('data/", f"fetch('{FEED}/")
    js = js.replace('fetch("data/', f'fetch("{FEED}/')

    # The upload UI must not offer what this build cannot read. See csv_parser
    # below for why .xlsx is gone: SheetJS is CDN-loaded and gets stripped.
    for before, after in [
        ('accept=".xlsx,.xls,.csv"', 'accept=".csv,text/csv"'),
        ("Drop .xlsx here", "Drop .csv here"),
        ("*.xlsx</code>", "*.csv</code>"),
        ("Looks for Symbol / Ticker",
         "CSV only here - save an .xlsx copy as CSV first. "
         "Looks for Symbol / Ticker"),
    ]:
        if before not in js:
            sys.exit(f"expected upload-UI text not found, refusing to ship a "
                     f"drop zone that lies about what it accepts: {before!r}")
        js = js.replace(before, after)

    # These MUST be emitted after news-desk's code has run, not before it.
    #
    # The handlers are `function` declarations sitting inside the try block
    # below. A function declared inside a BLOCK only gets an Annex B
    # function-scoped binding, and that binding holds `undefined` until the
    # block actually executes. Assigning at the top of _ndBoot therefore copied
    # `undefined` onto window — with no error to catch, because reading the
    # binding is perfectly legal. Every inline on* handler in the markup then
    # referenced an undefined global and did nothing: both tabs, the search box,
    # both filter dropdowns, CLR, and ticker clicks. The feed still painted,
    # because the code calls render() from inside the block where it IS defined,
    # so the tab looked alive while nothing in it responded.
    expose = "\n".join(
        f"    try{{window.{h}={h};}}"
        f"catch(e){{console.error('news tab: could not expose {h}',e);}}"
        for h in HANDLERS)

    # news-desk parses holdings files with SheetJS, which it loads from a CDN:
    #   <script src="https://cdn.jsdelivr.net/npm/xlsx@0.18.5/...">
    # That tag is stripped here, because this page has to stay self-contained —
    # so XLSX never exists and every upload sat on "SheetJS still loading, try
    # again in a moment." forever, including .csv, since news-desk routes CSV
    # through XLSX.read() too.
    #
    # Rather than inline ~900KB of third-party library into a public page, or
    # add a CDN script to it, the merged tab parses CSV itself and gives up on
    # .xlsx. Excel files still work on news-desk proper, where SheetJS loads.
    # The header detection, symbol-column matching and ticker filtering below
    # are deliberately identical to news-desk's — only the decoding differs.
    csv_parser = r"""
    function _ndParseCSV(text){
      // Minimal RFC4180: quoted fields, "" escapes, newlines inside quotes.
      if(text.charCodeAt(0)===0xFEFF) text=text.slice(1);
      var rows=[],row=[],cur='',q=false;
      for(var i=0;i<text.length;i++){
        var c=text[i];
        if(q){
          if(c==='"'){ if(text[i+1]==='"'){cur+='"';i++;} else q=false; }
          else cur+=c;
        }
        else if(c==='"') q=true;
        else if(c===',') { row.push(cur); cur=''; }
        else if(c==='\n'){ row.push(cur); cur=''; rows.push(row); row=[]; }
        else if(c!=='\r') cur+=c;
      }
      if(cur.length||row.length){ row.push(cur); rows.push(row); }
      return rows;
    }
    _parseHoldings=function(file){
      var reader=new FileReader();
      reader.onload=function(ev){
        try{
          var rows=_ndParseCSV(String(ev.target.result));
          var headerIdx=0;
          for(var i=0;i<Math.min(rows.length,6);i++){
            var non=rows[i].filter(function(v){
              return String(v||'').trim().length>0; }).length;
            if(non>=4){ headerIdx=i; break; }
          }
          var headers=rows[headerIdx]||[];
          var dataRows=rows.slice(headerIdx+1);
          var symCol=_findSymbolColumn(headers);
          if(!symCol){
            STATE.holdingsSummary={filename:file.name,rowCount:dataRows.length,
              symCol:null,tickerCount:0,skipped:dataRows.length,
              error:'No Symbol-like column found. If this was an .xlsx, save it '
                   +'as CSV first - Excel files are not supported here.'};
            render(); return;
          }
          var seen={},skipped=0,order=[];
          for(var r=0;r<dataRows.length;r++){
            var tk=String(dataRows[r][symCol.idx]||'').trim().toUpperCase()
                     .replace(/\s+/g,'');
            if(!tk) continue;
            if(_CASH_LIKE.has(tk)){ skipped++; continue; }
            if(!_TICKER_RE.test(tk)){ skipped++; continue; }
            if(!seen[tk]){ seen[tk]=1; order.push(tk); }
          }
          STATE.watchlist=order.sort();
          STATE.watchOnly=STATE.watchlist.length>0;
          STATE.holdingsSummary={filename:file.name,rowCount:dataRows.length,
            symCol:symCol.label,tickerCount:STATE.watchlist.length,
            skipped:skipped};
          _savePrefs(); _renderWatchUI(); render();
        }catch(err){
          STATE.holdingsSummary={filename:file.name,rowCount:0,error:String(err)};
          render();
        }
      };
      reader.readAsText(file);
    };"""

    # MY BOOK counted 0 forever because news-desk keeps its watchlist in its own
    # store (nd-prefs-v1) while regime-desk keeps one in `rd-watchlist`. Two
    # watchlists in one page, and the tab was reading the empty one. Seed from
    # regime-desk's when news-desk has none, so the tab means something without
    # asking for a holdings file the rest of the site already knows.
    #
    # Session-only on purpose: not written back to nd-prefs-v1, so "Clear book"
    # still clears an uploaded list rather than fighting a value that silently
    # reappears. An uploaded or pasted list always wins, because it is the more
    # specific answer.
    seed = (
        "    try{\n"
        "      if(!STATE.watchlist.length){\n"
        "        var _rdw=(localStorage.getItem('rd-watchlist')||'')\n"
        "          .split(',').map(function(s){return s.trim().toUpperCase();})\n"
        "          .filter(Boolean);\n"
        "        if(_rdw.length){\n"
        "          STATE.watchlist=_rdw;\n"
        "          STATE.holdingsSummary={filename:null,"
        "source:'regime-desk watchlist'};\n"
        "        }\n"
        "      }\n"
        "    }catch(e){console.error('news tab: watchlist seed failed',e);}"
    )

    # A silent failure here is what made the above cost a day. If a future
    # news-desk drops or renames a handler, say so in the console rather than
    # shipping a tab whose controls quietly do nothing.
    check = (
        "    var _ndMissing=" + json.dumps(HANDLERS) + ".filter("
        "function(n){return typeof window[n]!=='function';});\n"
        "    if(_ndMissing.length)console.error("
        "'news tab: handlers not exposed, inline controls will be dead:',"
        "_ndMissing);"
    )

    wrapped = (
        "// GENERATED by build/build_news_tab.py — do not edit by hand.\n"
        "// Re-run that script to re-port news-desk after it changes.\n"
        "window._ndBoot=function(){\n"
        "  if(window._ndBooted)return; window._ndBooted=true;\n"
        "  try{\n"
        f"{js}\n"
        f"{csv_parser}\n"
        f"{seed}\n"
        f"{expose}\n"
        f"{check}\n"
        "  }catch(e){\n"
        "    console.error('news tab failed to start',e);\n"
        "    var c=document.getElementById('content');\n"
        "    if(c)c.innerHTML='<div style=\"padding:20px;color:#8b949e\">"
        "The news view failed to start. Its own site is at "
        "<a href=\"https://helioskozak-cloud.github.io/news-desk/\" "
        "target=\"_blank\" rel=\"noopener noreferrer\" style=\"color:#58a6ff\">"
        "news-desk</a>.</div>';\n"
        "  }\n"
        "};\n"
        "window._ndMarkup=" + repr_js(markup) + ";\n"
    )

    verify(css, markup, js)

    html = TARGET.read_text(encoding="utf-8")
    html = replace_between(html, CSS_START, CSS_END, "\n" + css + "\n")
    html = replace_between(html, JS_START, JS_END, "\n" + wrapped + "\n")
    TARGET.write_text(html, encoding="utf-8")

    print(f"  css    {len(css):,} chars")
    print(f"  markup {len(markup):,} chars")
    print(f"  js     {len(js):,} chars")
    print(f"wrote {TARGET.relative_to(ROOT)}")


# Elements the ported script writes to without guarding. If the markup stops
# carrying them, the tab throws on load rather than degrading.
REQUIRED_IDS = ["content", "search", "srcFilter", "typeFilter", "counts",
                "count-news", "count-book", "updated"]


def verify(css: str, markup: str, js: str) -> None:
    """Refuse to write a port that would misbehave.

    Checked here rather than in a separate test because the failure modes are
    all silent: CSS that escapes the tab restyles the rest of the dashboard,
    and a relative fetch resolves against regime-desk's own /data/ — which
    exists, and holds something else entirely. Both produce a plausible wrong
    page rather than an error.
    """
    problems: list[str] = []

    for m in re.finditer(r"([^{}]+)\{[^{}]*\}", css):
        sel = m.group(1).strip()
        if not sel or sel.startswith("@"):
            continue
        for one in (s.strip() for s in sel.split(",")):
            if one and SCOPE not in one:
                problems.append(f"selector escapes {SCOPE}: {one[:70]}")

    if "fetch('data/" in js or 'fetch("data/' in js:
        problems.append("a relative fetch survived — it would read regime-desk's /data/")

    if SCOPE + "{" not in css:
        problems.append(f"no {SCOPE}{{...}} rule — the :root variables did not get remapped")

    for el in REQUIRED_IDS:
        if f'id="{el}"' not in markup:
            problems.append(f'markup is missing id="{el}", which the script writes to')

    if "<script" in markup:
        problems.append("a <script> survived into the markup (it would not run via innerHTML)")

    if problems:
        print("\nREFUSING TO WRITE:")
        for p in problems:
            print(f"  {p}")
        sys.exit(1)
    print(f"  verified: scope clean, {len(REQUIRED_IDS)} required ids present")


def repr_js(s: str) -> str:
    """A JS string literal for arbitrary HTML — JSON escaping is close enough
    and avoids every quoting trap backticks would introduce."""
    import json
    return json.dumps(s)


def replace_between(text: str, start: str, end: str, body: str) -> str:
    i = text.find(start)
    j = text.find(end)
    if i < 0 or j < 0:
        sys.exit(f"markers not found in {TARGET.name}: {start} / {end}")
    return text[: i + len(start)] + body + text[j:]


if __name__ == "__main__":
    main()
