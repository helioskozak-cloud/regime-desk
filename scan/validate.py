"""B3 — WALK-FORWARD VALIDATION. The gate nothing ships without.

Owner's plan, 2026-09-16: "No rule ships without this."

The engine has never been tested on data it did not also learn from. Its only
record is the forward log started in February, which shows posted +16.6%
against realized +4.8% and a 30% beat rate — a verdict, but not an experiment:
it cannot say which PART of the rule is wrong, and it cannot compare a proposed
replacement against the incumbent.

This harness does that. At each as-of date it builds a candidate table using
ONLY bars up to that date, applies a rule, and then scores what the selection
actually did over the following horizon. Nothing a rule sees has a timestamp
later than the decision.

THREE THINGS IT DOES DIFFERENTLY FROM THE LIVE ENGINE, each because measuring
the live engine exposed the problem:

  1. THE NULL IS THE STOCK'S OWN UNCONDITIONAL FORWARD RETURN, not zero. In a
     rising market nearly every name beats zero — which is how a screen
     returned +20.7% at 120 days while losing to SPY in 78% of cases. The
     question worth asking is whether conditioning on the regime beats what
     that same stock does on an ordinary day.

  2. THE SCORE IS ALPHA VERSUS SPY over the same window, for the same reason.

  3. EVERY CONDITIONAL OBSERVATION MUST BE COMPLETE AT DECISION TIME. An
     analog day 40 sessions back has no 120-day forward return yet; including
     one silently mixes a partial outcome into the evidence. Analog days are
     required to satisfy `analog_date + horizon <= as_of`.

The rules being compared are deliberately plain, and none of their parameters
is fitted here. Fitting on the same history that judges the result is exactly
how a +53% edge came to deliver +20%.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent
DB = ROOT / "data" / "market_data.db"

BENCH = "SPY"
ANALOG_FEATURES = ["return_5", "return_20", "volatility", "drawdown"]
ANALOG_N = 30
EXCLUDE_RECENT = 30
MIN_EPISODES = 5
EPISODE_GAP_DAYS = 14


# ── data ─────────────────────────────────────────────────────────────────────

def load_closes(tickers: list[str] | None = None, db: Path = DB) -> pd.DataFrame:
    """Wide frame of closes: index = date, columns = tickers."""
    conn = sqlite3.connect(str(db))
    try:
        if tickers:
            marks = ",".join("?" * len(tickers))
            q = f"SELECT ticker, date, close FROM prices WHERE ticker IN ({marks})"
            df = pd.read_sql_query(q, conn, params=tickers)
        else:
            df = pd.read_sql_query("SELECT ticker, date, close FROM prices", conn)
    finally:
        conn.close()
    df["date"] = pd.to_datetime(df["date"].str.slice(0, 10))
    wide = df.pivot_table(index="date", columns="ticker", values="close", aggfunc="last")
    return wide.sort_index()


def market_features(bench_close: pd.Series) -> pd.DataFrame:
    """The four SPY features the engine conditions on, same definitions as
    ci_scan.compute_features — 5- and 20-day returns, 20-day realised vol, and
    drawdown from a 60-day rolling max."""
    s = bench_close.dropna()
    out = pd.DataFrame(index=s.index)
    out["return_5"] = s.pct_change(5)
    out["return_20"] = s.pct_change(20)
    out["volatility"] = s.pct_change().rolling(20).std()
    out["drawdown"] = s / s.rolling(60, min_periods=1).max() - 1
    return out.dropna()


def analog_dates(feats: pd.DataFrame, as_of: pd.Timestamp, horizon: int,
                 n: int = ANALOG_N, exclude_recent: int = EXCLUDE_RECENT) -> pd.DatetimeIndex:
    """The n past sessions most like `as_of`, z-scored, with no look-ahead.

    Two exclusions, and the second is the one the live engine does not make:
    the last `exclude_recent` sessions are skipped as too close to today, AND
    any day whose forward window has not finished by `as_of` is skipped,
    because its outcome is not knowable at decision time.
    """
    hist = feats.loc[:as_of]
    if len(hist) < 150:
        return pd.DatetimeIndex([])
    current = hist.iloc[-1]
    mean, std = hist.mean(), hist.std().replace(0, 1)
    z = (hist - mean) / std
    cz = (current - mean) / std
    dist = pd.Series(np.linalg.norm(z.values - cz.values, axis=1), index=hist.index)

    eligible = dist.iloc[:-exclude_recent] if exclude_recent else dist
    # Only days whose horizon has fully elapsed by as_of.
    positions = {d: i for i, d in enumerate(feats.index)}
    as_of_pos = positions.get(as_of, len(feats) - 1)
    complete = [d for d in eligible.index if positions.get(d, 10 ** 9) + horizon <= as_of_pos]
    if not complete:
        return pd.DatetimeIndex([])
    return pd.DatetimeIndex(dist.loc[complete].nsmallest(n).index)


def episodes(dates: pd.DatetimeIndex, gap_days: int = EPISODE_GAP_DAYS) -> int:
    """Independent clusters among analog days. Adjacent sessions describe the
    same market episode and must not be counted as separate evidence."""
    if len(dates) == 0:
        return 0
    ordered = sorted(dates)
    n = 1
    for prev, cur in zip(ordered, ordered[1:]):
        if (cur - prev).days > gap_days:
            n += 1
    return n


# ── candidate table, as of a date ────────────────────────────────────────────

@dataclass
class Candidates:
    as_of: pd.Timestamp
    horizon: int
    table: pd.DataFrame = field(default_factory=pd.DataFrame)
    n_analogs: int = 0
    n_episodes: int = 0


def build_candidates(closes: pd.DataFrame, feats: pd.DataFrame,
                     as_of: pd.Timestamp, horizon: int,
                     min_history: int = 260) -> Candidates:
    """Every ticker's conditional and unconditional forward return as of a date.

    Columns:
      cond      - mean forward return over the analog days
      uncond    - mean forward return over ALL past days (the null)
      excess    - cond - uncond, the thing actually worth testing
      spread    - dispersion of the analog outcomes
      n_obs     - analog days that produced a number
    """
    dates = analog_dates(feats, as_of, horizon)
    if len(dates) < MIN_EPISODES:
        return Candidates(as_of, horizon)

    past = closes.loc[:as_of]
    if len(past) < min_history:
        return Candidates(as_of, horizon)

    fwd = past.shift(-horizon) / past - 1.0          # forward return per bar
    analog_rows = fwd.reindex(dates).dropna(how="all")
    if analog_rows.empty:
        return Candidates(as_of, horizon)

    enough = past.notna().sum() >= min_history
    cols = [c for c in past.columns if enough.get(c, False)]

    cond = analog_rows[cols].mean()
    spread = analog_rows[cols].std()
    n_obs = analog_rows[cols].notna().sum()
    uncond = fwd[cols].mean()

    table = pd.DataFrame({
        "cond": cond, "uncond": uncond, "spread": spread, "n_obs": n_obs,
    })
    table["excess"] = table["cond"] - table["uncond"]
    table = table[table["n_obs"] >= MIN_EPISODES].dropna(subset=["cond", "uncond"])
    return Candidates(as_of, horizon, table, len(dates), episodes(dates))


# ── outcomes ─────────────────────────────────────────────────────────────────

def realised(closes: pd.DataFrame, as_of: pd.Timestamp, horizon: int,
             tickers: list[str]) -> pd.Series:
    """Forward return from as_of over `horizon` bars. This is the only place in
    the module that reads bars after the decision date."""
    idx = closes.index
    pos = idx.get_indexer([as_of])[0]
    if pos < 0 or pos + horizon >= len(idx):
        return pd.Series(dtype=float)
    start, end = closes.iloc[pos], closes.iloc[pos + horizon]
    out = (end / start - 1.0)
    return out.reindex(tickers).dropna()


@dataclass
class RunResult:
    rule: str
    horizon: int
    picks_per_date: list[int]
    alpha: list[float]
    dates: list[pd.Timestamp]

    def summary(self) -> dict:
        a = np.array([x for x in self.alpha if x == x])
        picks = np.array(self.picks_per_date)
        if len(a) == 0:
            return {"rule": self.rule, "horizon": self.horizon, "runs": 0,
                    "mean_alpha": None, "beat_rate": None, "t": None,
                    "avg_picks": float(picks.mean()) if len(picks) else 0.0}
        se = a.std(ddof=1) / np.sqrt(len(a)) if len(a) > 1 else float("nan")
        return {
            "rule": self.rule,
            "horizon": self.horizon,
            "runs": len(a),
            "mean_alpha": float(a.mean()),
            "beat_rate": float((a > 0).mean()),
            # Across as-of dates, which overlap; treat as indicative, not exact.
            "t": float(a.mean() / se) if se and se == se and se > 0 else None,
            "avg_picks": float(picks.mean()) if len(picks) else 0.0,
        }


# ── the rules under test ─────────────────────────────────────────────────────
#
# Each takes the candidate table (plus optional scanner scores) and returns the
# tickers it would buy. No parameter here is fitted on this history.

N_PICK = 20


def rule_legacy(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK) -> list[str]:
    """WHAT THE ENGINE DOES TODAY: the highest conditional mean forward return.
    Included as the incumbent — a replacement has to beat this, not beat zero."""
    return list(tab.nlargest(n, "cond").index)


def rule_excess(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK) -> list[str]:
    """Conditional mean MINUS the same stock's unconditional mean. Asks whether
    the regime told us anything, rather than whether the market went up."""
    return list(tab.nlargest(n, "excess").index)


def rule_shrunk_fdr(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK) -> list[str]:
    """B2 applied properly: shrink the excess by episode count, test every
    candidate, control the false discovery rate across the WHOLE set, then take
    the best survivors. Returns fewer than n — often none — on purpose."""
    import selection as sel
    rows = [{"key": t, "edge": r.excess, "spread": r.spread, "n_episodes": r.n_obs}
            for t, r in tab.iterrows()]
    out = sel.select(rows, q=0.10)
    if not out["survivors"]:
        return []
    keep = tab.loc[[t for t in tab.index if t in out["survivors"]]]
    return list(keep.nlargest(n, "excess").index)


def rule_scanner(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK) -> list[str]:
    """B4 alone: what is strongest NOW, ignoring the conditional statistics."""
    if scan is None or scan.empty:
        return []
    common = [t for t in scan.index if t in tab.index]
    return list(scan.loc[common].nlargest(n).index)


def rule_combined(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK) -> list[str]:
    """The intersection: names moving now that also sit in a regime cohort with
    a positive excess. The shape the owner and I agreed was the end state."""
    if scan is None or scan.empty:
        return []
    common = [t for t in scan.index if t in tab.index]
    if not common:
        return []
    sub = tab.loc[common].copy()
    sub["scan"] = scan.loc[common]
    strong = sub[sub["scan"] >= sub["scan"].quantile(0.5)]
    strong = strong[strong["excess"] > 0]
    return list(strong.nlargest(n, "excess").index)


def rule_random(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK,
                seed: int = 0) -> list[str]:
    """THE CONTROL. Any rule that cannot beat drawing names out of the same hat
    is not a rule. Seeded per as-of date so a run is reproducible."""
    rng = np.random.default_rng(seed)
    idx = list(tab.index)
    if len(idx) <= n:
        return idx
    return [idx[i] for i in rng.choice(len(idx), size=n, replace=False)]


RULES = {
    "legacy (cond mean)": rule_legacy,
    "excess (cond-uncond)": rule_excess,
    "shrunk+FDR": rule_shrunk_fdr,
    "scanner": rule_scanner,
    "combined": rule_combined,
    "random (control)": rule_random,
}


def scanner_scores(closes: pd.DataFrame, as_of: pd.Timestamp,
                   tickers: list[str]) -> pd.Series:
    """B4's composite as of a date, computed only from bars up to it."""
    import scanner as sc
    past = closes.loc[:as_of]
    if BENCH not in past.columns:
        return pd.Series(dtype=float)
    bench = past[BENCH].dropna()
    rows = {}
    for t in tickers:
        s = past[t].dropna()
        if len(s) < 260:
            continue
        rows[t] = sc.features(s, bench)
    if not rows:
        return pd.Series(dtype=float)
    return pd.Series(sc.composite(rows))


def walk_forward(closes: pd.DataFrame, horizon: int, as_of_dates: list[pd.Timestamp],
                 rules: dict = None, n_pick: int = N_PICK,
                 verbose: bool = True) -> dict[str, RunResult]:
    """Run every rule at every as-of date and score it against SPY."""
    rules = rules or RULES
    feats = market_features(closes[BENCH])
    results = {name: RunResult(name, horizon, [], [], []) for name in rules}

    for i, as_of in enumerate(as_of_dates):
        cands = build_candidates(closes, feats, as_of, horizon)
        if cands.table.empty:
            if verbose:
                print(f"  {as_of.date()}: no candidates", flush=True)
            continue
        scan = scanner_scores(closes, as_of, list(cands.table.index))
        bench_fwd = realised(closes, as_of, horizon, [BENCH])
        if bench_fwd.empty:
            continue
        spy_ret = float(bench_fwd.iloc[0])

        line = [f"  {as_of.date()} cand={len(cands.table):4d} epi={cands.n_episodes:2d} SPY={spy_ret * 100:+6.2f}%"]
        for name, fn in rules.items():
            picks = fn(cands.table, scan, n_pick) if name != "random (control)" \
                else fn(cands.table, scan, n_pick, seed=i)
            res = results[name]
            res.picks_per_date.append(len(picks))
            res.dates.append(as_of)
            if not picks:
                res.alpha.append(float("nan"))
                line.append(f"{name}: none")
                continue
            got = realised(closes, as_of, horizon, picks)
            if got.empty:
                res.alpha.append(float("nan"))
                continue
            a = float(got.mean()) - spy_ret
            res.alpha.append(a)
            line.append(f"{name}: {a * 100:+5.1f}")
        if verbose:
            print(" | ".join(line), flush=True)
    return results
