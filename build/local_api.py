"""
local_api.py — On-demand ticker signal server for Regime Desk.

The dashboard detects this server and fetches signals in real time when
a pinned ticker is not in the snapshot.  The server also writes the ticker
to data/watchlist.txt and data/ticker_cache.json so the next scheduled
build keeps it permanently.

Run:   python build/local_api.py
  or:  run_local_api.bat  (keeps the window open)

Requires: numpy, pandas (already used by ticker_lookup.py)
"""
import json
import re
import sqlite3
import sys
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from ticker_lookup import (
    CACHE_PATH,
    MIN_OBSERVATIONS,
    WATCHLIST_PATH,
    _find_db,
    compute_analog_dates,
    compute_ticker,
    load_sector_map,
)

PORT = 7534
_state = {"analog_dates": None, "sector_map": {}, "lock": threading.Lock()}


def _ensure_analog_dates():
    """Return (analog_dates, sector_map), computing once and caching."""
    with _state["lock"]:
        if _state["analog_dates"] is not None:
            return _state["analog_dates"], _state["sector_map"]
        db = _find_db()
        if not db:
            return None, {}
        conn = sqlite3.connect(db)
        try:
            _state["analog_dates"] = compute_analog_dates(conn)
            _state["sector_map"] = load_sector_map(conn)
            print(f"[api] Analog dates cached ({len(_state['analog_dates'])} days)")
        finally:
            conn.close()
        return _state["analog_dates"], _state["sector_map"]


def _lookup(ticker):
    """Compute signal for ticker. Returns signal dict or None."""
    analog_dates, sector_map = _ensure_analog_dates()
    if not analog_dates:
        return None
    db = _find_db()
    if not db:
        return None
    conn = sqlite3.connect(db)
    try:
        return compute_ticker(conn, ticker, analog_dates, sector_map)
    finally:
        conn.close()


def _persist(ticker, signal):
    """Write ticker to watchlist.txt and update ticker_cache.json."""
    try:
        existing_wl = []
        if WATCHLIST_PATH.exists():
            for line in WATCHLIST_PATH.read_text(encoding="utf-8").splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    existing_wl.append(s.upper())
        if ticker not in existing_wl:
            with open(WATCHLIST_PATH, "a", encoding="utf-8") as f:
                f.write(f"{ticker}\n")
            print(f"[api] Added {ticker} to watchlist.txt")
    except Exception as exc:
        print(f"[api] watchlist.txt write failed: {exc}")

    try:
        cache = {"generated": str(date.today()), "tickers": {}}
        if CACHE_PATH.exists():
            with open(CACHE_PATH, "r", encoding="utf-8") as f:
                cache = json.load(f)
        cache["tickers"][ticker] = signal
        CACHE_PATH.write_text(json.dumps(cache, indent=2), encoding="utf-8")
    except Exception as exc:
        print(f"[api] ticker_cache.json write failed: {exc}")


class _Handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)

        if parsed.path == "/api/ping":
            self._json({"ok": True, "port": PORT})

        elif parsed.path == "/api/ticker":
            ticker = re.sub(r"[^A-Z0-9.]", "", (qs.get("t", [""])[0]).strip().upper())
            if not ticker:
                self._json({"error": "missing ?t=TICKER"}, 400)
                return
            print(f"[api] Computing {ticker}...", flush=True)
            signal = _lookup(ticker)
            if signal:
                _persist(ticker, signal)
                flag = " [below threshold]" if signal["below_threshold"] else ""
                print(f"[api] {ticker}: edge={signal['edge']:+.1%} ({signal['horizon']}, n={signal['n_obs']}){flag}", flush=True)
                self._json(signal)
            else:
                print(f"[api] {ticker}: not found or insufficient data", flush=True)
                self._json({"error": f"{ticker} not in database or insufficient observations"}, 404)

        else:
            self._json({"error": "not found"}, 404)

    def _json(self, data, status=200):
        body = json.dumps(data).encode()
        self.send_response(status)
        self._cors()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def log_message(self, fmt, *args):
        pass  # suppress default per-request logging


def main():
    db = _find_db()
    if not db:
        print("[api] ERROR: market_data.db not found — cannot start server")
        sys.exit(1)

    print(f"[api] Regime Desk local API -> http://localhost:{PORT}")
    print(f"[api] DB: {db}")
    print(f"[api] Warming up analog dates...", flush=True)
    _ensure_analog_dates()
    print(f"[api] Ready. Pin any ticker in the dashboard to compute its signal.")
    print(f"[api] Press Ctrl+C to stop.\n", flush=True)

    server = HTTPServer(("localhost", PORT), _Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[api] Stopped.")


if __name__ == "__main__":
    main()
