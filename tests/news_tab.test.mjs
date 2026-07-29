/* Tests for the News tab's renderer, pulled straight out of docs/index.html.
 *
 *     node tests/news_tab.test.mjs
 *
 * No test runner and no dependencies — regime-desk is a static site and this
 * is the only JS here worth gating.
 *
 * WHY THIS EXISTS. The News tab renders text fetched from thirty-odd
 * third-party RSS feeds into innerHTML. Every headline title, summary and
 * source is authored by someone else's CMS, so the escaping is the only thing
 * standing between a feed and script execution on this page. That is not code
 * to eyeball once and trust.
 *
 * The fixture is inline rather than read from news-desk's checkout: a test
 * that depends on a sibling repo being present passes or fails for reasons
 * that have nothing to do with this one.
 */
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const HERE = dirname(fileURLToPath(import.meta.url));
const html = readFileSync(join(HERE, "..", "docs", "index.html"), "utf8");

const start = html.indexOf("// ── News ─");
const end = html.indexOf("const renderers=", start);
if (start < 0 || end < 0) {
  console.log("FAIL: could not find the News block in docs/index.html");
  process.exit(1);
}

const els = {};
globalThis.document = {
  getElementById: (id) => els[id] || (els[id] = { innerHTML: "", textContent: "" }),
  querySelectorAll: () => [],
};
globalThis.window = {};
globalThis.fetch = async () => { throw new Error("no network in tests"); };

const mod = new Function(
  html.slice(start, end) +
  "\nreturn {renderNews,_newsStrip,_newsList,_nEsc,_nAgo," +
  "setDoc:(d,m)=>{_newsDoc=d;_newsMkt=m;},setCat:(c)=>{_newsCat=c;}};"
)();

let fail = 0;
const ok = (cond, msg) => { console.log(`  ${cond ? "ok  " : "FAIL"} ${msg}`); if (!cond) fail++; };

const MARKETS = {
  "^GSPC":   { label: "S&P 500", order: 0, price: 7409.65,  change: -19.13,  change_pct: -0.26 },
  "^DJI":    { label: "Dow",     order: 1, price: 52016.18, change: -731.14, change_pct: -1.39 },
  "CL=F":    { label: "Crude",   order: 2, price: 84.42,    change: 5.16,    change_pct: 6.51 },
};

const HOSTILE = {
  generated: new Date().toISOString(), feed_count: 31,
  headlines: [
    { title: "<script>alert(1)</script>", summary: 'x" onmouseover="evil()',
      link: "https://example.com/a", source: "Feed A", domain: "example.com",
      published: new Date().toISOString(), category: "markets",
      sentiment: "negative", tickers: '["AAPL","MSFT"]' },
    { title: "Ordinary macro headline", summary: "Nothing special.",
      link: "https://example.com/b", source: "Feed B", domain: "example.com",
      published: new Date().toISOString(), category: "macro",
      sentiment: "positive", tickers: "[]" },
  ],
};

console.log("escaping — every field below is third-party text");
ok(mod._nEsc("<script>alert(1)</script>") === "&lt;script&gt;alert(1)&lt;/script&gt;",
   "script tags neutralised");
ok(mod._nEsc('" onmouseover="x') === "&quot; onmouseover=&quot;x",
   "attribute break-out neutralised");
ok(mod._nEsc(null) === "", "null renders empty, not the string 'null'");

console.log("\nempty state");
ok(mod._newsStrip().includes("Loading"), "strip shows loading before data arrives");
ok(mod._newsList().includes("Loading"), "list shows loading before data arrives");

console.log("\na hostile feed");
mod.setDoc(HOSTILE, MARKETS);
const list = mod._newsList();
ok(!/<script/i.test(list.replace(/&lt;script/gi, "")), "no executable script tag survives");
// The escaped text "x&quot; onmouseover=&quot;evil()" is inert and WILL appear
// — that is the escaping working. What must not appear is the raw form, with
// real quotes, which is what would break out of the surrounding attribute.
ok(!list.includes('x" onmouseover="evil()'),
   "the raw break-out string does not survive (escaped form is fine)");
ok(!/=["'][^"']*\bonmouseover\s*=/i.test(list),
   "no unescaped quote lets an event handler into attribute position");
ok(list.includes("&lt;script&gt;"), "the hostile title is still shown, escaped");
ok(list.includes('rel="noopener noreferrer"'), "external links are rel-protected");
ok(list.includes('target="_blank"'), "links open in a new tab");

console.log("\nmarket strip");
const strip = mod._newsStrip();
ok(strip.includes("S&amp;P 500"), "ampersand in a label is escaped");
ok(strip.indexOf("Dow") > strip.indexOf("S&amp;P"), "respects display order");
ok(strip.includes("#f85149") && strip.includes("#3fb950"), "up and down are coloured differently");
ok(strip.includes("52,016"), "large numbers get thousands separators");
ok(strip.includes("84.42"), "a sub-100 price keeps two decimals");

console.log("\ncategory filter");
mod.setCat("macro");
ok(mod._newsList().includes("Ordinary macro"), "macro filter keeps macro");
ok(!mod._newsList().includes("&lt;script&gt;"), "macro filter drops the markets row");
mod.setCat("nonsense");
ok(mod._newsList().includes("Nothing in this category"), "unknown category is an empty state, not a crash");
mod.setCat("all");

console.log("\nmalformed input");
mod.setDoc({ headlines: [{ title: "still rendered", link: "y", source: "z",
                           published: "not-a-date", tickers: "{{{bad json" }] }, MARKETS);
ok(mod._newsList().includes("still rendered"),
   "unparseable tickers and an invalid date do not stop the row rendering");

console.log(`\n${fail === 0 ? "ALL PASS" : fail + " FAILURE(S)"}`);
process.exit(fail === 0 ? 0 : 1);
