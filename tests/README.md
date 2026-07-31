# News tab tests

Two harnesses, both driving the real `docs/index.html`. Neither asserts on
markup alone: the 2026-07-30 bug was a tab whose controls rendered perfectly
and did nothing, and it was only caught by clicking them. Every assertion here
is about state *after* an event.

    npm i jsdom playwright        # not vendored; install where you run them
    node tests/news_dom.test.js       # 80 assertions
    node tests/news_layout.test.js    # 36 assertions, real Chromium

`news_dom.test.js` loads the page in jsdom with `fetch` stubbed to serve a
synthetic `headlines.json` built from the page's own `window.SNAPSHOT`, then
exercises: search, both selects, clear, the tabs, ticker click-to-filter, row
expand across a re-render, paste, `.csv` upload, `.xlsx` upload through the
actual vendored SheetJS, book seeding from `rd-watchlist`, and a deliberate
feed outage (which must fail loudly, not blankly).

`news_layout.test.js` serves `docs/` over localhost, intercepts the news-desk
fetches, and measures layout in Chromium at 1366 / 2560 / 1180 / 820 / 390 —
acceptance criterion #1, which jsdom cannot check because it has no layout
engine. It also repeats a few interactions in a real browser as a cross-check,
and writes screenshots to `$NEWS_SHOTS` (default: the system temp dir).

On this environment Chromium is preinstalled at `/opt/pw-browsers/chromium`,
which the layout test passes as `executablePath`. Do not run
`playwright install`.
