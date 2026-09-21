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

B5 / B6 — PRE-REGISTERED 2026-09-17, BEFORE EITHER WAS RUN
-----------------------------------------------------------
B5, BETA NEUTRALISATION. The old feed's top edge quartile carried beta 1.32
against 0.97 at the bottom: ranking on a forward return partly ranks on beta.
At each as-of date every candidate gets a trailing beta to SPY from the
BETA_WINDOW (252) daily returns ending at the decision date — no later bar —
and candidates are split into N_BUCKETS (5) equal-count beta buckets. A
neutralised rule takes the top N_PICK / N_BUCKETS names by its own score
INSIDE EACH bucket. Applied, unchanged otherwise, to legacy, excess and the
scanner. Every rule's average pick beta is recorded, so whether neutralising
did anything is measured rather than assumed.

B6, THE BLEND, ONLY AFTER B5. Score = scanner percentile rank + excess
percentile rank (each across that date's candidates, equal weight, nothing
fitted), picked within the same beta buckets.

DECISION RULES, fixed now:
  * B5 is a finding if a neutralised rule's paired alpha vs the random control
    is positive at all three horizons (20/60/120).
  * B6 earns consideration for a future generation only if it is positive vs
    the control at ALL THREE horizons AND beats neutralised scanner, paired on
    the same dates, at AT LEAST TWO of three. The un-neutralised blend posted
    the table's best cell and a negative neighbour; one strong cell is not
    enough, and the bar is set before the numbers exist so it cannot move.
  * Run parameters are the B3 run's: 900-name universe, 40 dates at 20d and
    60d, 36 at 120d, same local database. No rerun on other parameters to
    rescue a result; if one is ever done, it is reported beside this one.

B5 / B6 — RESULTS, 2026-09-17 (data/validation_b5b6_*.json)
-----------------------------------------------------------
Paired alpha vs the random control, and average pick beta (control ~1.06).
The pre-existing rules reproduce the B3 run to the basis point.

                          20d      60d     120d    pick beta
  legacy                -0.96%   +1.46%   -0.14%   1.51/1.31/0.84
  legacy beta-neutral   -0.38%   -0.31%   -1.40%   1.00/0.86/0.40
  excess beta-neutral   -0.11%   +0.70%   +3.50%   0.96/0.99/1.03
  scanner               +1.04%   +2.88%   +5.56%   0.98/1.07/0.95
  scanner beta-neutral  +0.34%   +3.48%   +4.00%   0.72/0.72/0.65
  blend beta-neutral    +0.08%   -0.79%   +2.96%   1.03/1.04/1.05

  B5: FINDING, for the scanner only. Positive vs control at all three
      horizons after neutralisation (t 0.87 / 2.40 / 1.47, overlapping
      windows, indicative). Legacy's 60d +1.46% does not survive it: that
      was beta.
  B6: FAILS. Negative vs control at 60d, and below neutral scanner at all
      three horizons. Not considered for a future generation.

  DISCLOSED, NOT RERUN: bucket neutralisation is not beta matching. Neutral
  scanner's picks average beta ~0.7, because inside each bucket it prefers
  the calmer names. It beat the control while carrying LESS market risk,
  which strengthens rather than explains the result; a beta-MATCHED variant
  is a different rule and would need its own pre-registration.

B7 — BETA-MATCHED CONTROL. PRE-REGISTERED 2026-09-21, BEFORE IT WAS RUN
-----------------------------------------------------------------------
Owner, 2026-09-21: "go ahead" on the rule below, as written to him in plain
words: the scanner has to beat equally-calm random picks at all three time
frames, and no reruns if it fails.

THE QUESTION. B5's control is a plain random draw (beta ~1.06); neutral
scanner's picks ran ~0.7. The score is raw return, so part of any gap is
market exposure, not selection, and which way it cuts depends on the path of
the market over 2021-2025. B7 removes it by giving the control the SAME beta
profile as the picks.

THE MATCHED CONTROL, fixed now:
  * On each as-of date, candidates with a trailing beta (the B5 beta, no bar
    after the decision) are split into BETA_DECILES (10) equal-count deciles.
  * For each pick, one stand-in is drawn at random from the same decile,
    never a pick and never twice in one draw. If a decile has fewer non-pick
    names than it needs, the draw for that decile is made WITH replacement
    and counted in `short_deciles`, not dropped.
  * The control's return is the mean over MATCHED_DRAWS (200) such baskets,
    seeded per date: the expected return of a beta-matched random basket,
    not one noisy draw.
  * Picks with no beta cannot be matched and leave the pick basket too, so
    both sides are names-with-beta only. Counted per date.
  * Paired score per date = pick basket mean - matched control mean, both
    over the same horizon from the same close. Matched-control beta and pick
    beta are both recorded; if their averages differ by more than 0.05 at any
    horizon the matching failed and the run is reported as not valid.

RULES TESTED: "scanner" (the plain composite, what V5's Max Edge ranks on)
and "scanner beta-neutral" (B5's rule). Each is judged on its own.

DECISION RULES, fixed now:
  * A rule is a B7 FINDING if its mean paired score vs the matched control is
    positive at all three horizons (20/60/120). Anything else is a FAIL.
  * Pass: its edge is selection, not market exposure; V5 carries on unchanged.
    Fail: its edge is largely lower market exposure; the V5 book(s) ranking on
    it are described as a low-volatility tilt and judged as one.
  * Run parameters are B5's exactly: the first 900 names of universe_ci.csv
    AS OF cb2d56a (the file was refreshed 2026-09-18), 40 dates at 20d and
    60d, 36 at 120d, the same local database. Before any B7 number is read,
    the plain-control results for both rules must reproduce B5's to the basis
    point; if they do not, the run is invalid and that is reported instead.
  * No rerun on other parameters to rescue a result. t-statistics are printed
    as before and remain indicative: the as-of windows overlap.
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
BETA_WINDOW = 252
N_BUCKETS = 5
BETA_DECILES = 10       # B7
MATCHED_DRAWS = 200     # B7


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


# ── beta, as of a date (B5) ──────────────────────────────────────────────────

def trailing_beta(closes: pd.DataFrame, as_of: pd.Timestamp, tickers,
                  window: int = BETA_WINDOW) -> pd.Series:
    """Beta to SPY over the `window` daily returns ending AT `as_of`.

    Reads nothing after the decision date. A ticker with fewer than 80% of the
    window's returns is left out (NaN), never assigned a beta of 1."""
    past = closes.loc[:as_of].iloc[-(window + 1):]
    rets = past.pct_change().iloc[1:]
    if BENCH not in rets.columns:
        return pd.Series(dtype=float)
    b = rets[BENCH]
    out = {}
    for t in tickers:
        if t not in rets.columns:
            continue
        pair = pd.concat([rets[t], b], axis=1).dropna()
        if len(pair) < 0.8 * window:
            continue
        var = pair.iloc[:, 1].var()
        if not var or var != var:
            continue
        out[t] = float(pair.iloc[:, 0].cov(pair.iloc[:, 1]) / var)
    return pd.Series(out, dtype=float)


def within_beta_buckets(score: pd.Series, beta: pd.Series, n: int,
                        buckets: int = N_BUCKETS) -> list[str]:
    """Top n // buckets names by `score` inside each equal-count beta bucket.

    Names with no score or no beta cannot be placed and are left out. Fewer
    than two names per bucket: abstain, rather than fill from one end."""
    s = score.dropna()
    bt = beta.dropna()
    common = s.index.intersection(bt.index)
    if len(common) < buckets * 2 or n < buckets:
        return []
    labels = pd.qcut(bt.loc[common].rank(method="first"), buckets, labels=False)
    per = n // buckets
    picks: list[str] = []
    for k in range(buckets):
        members = labels.index[labels == k]
        picks += list(s.loc[members].nlargest(per).index)
    return picks


def beta_matched_baskets(picks: list[str], beta: pd.Series, draws: int = MATCHED_DRAWS,
                         deciles: int = BETA_DECILES, seed: int = 0):
    """B7: random baskets with the same beta-decile profile as `picks`.

    Returns (matched_picks, baskets, short): the picks that had a beta (the
    only ones that can be matched), `draws` stand-in baskets each as long as
    matched_picks, and how many deciles had to be drawn with replacement.
    Uses only the betas passed in, which are as-of-date betas."""
    bt = beta.dropna()
    matched = [p for p in picks if p in bt.index]
    if not matched or len(bt) < deciles * 2:
        return matched, [], 0
    labels = pd.qcut(bt.rank(method="first"), deciles, labels=False)
    pickset = set(picks)
    need: dict[int, int] = {}
    for p in matched:
        need[int(labels[p])] = need.get(int(labels[p]), 0) + 1
    pools = {k: [t for t in labels.index[labels == k] if t not in pickset] for k in need}
    short = sum(1 for k, n in need.items() if len(pools[k]) < n)
    rng = np.random.default_rng(seed)
    baskets = []
    for _ in range(draws):
        b: list[str] = []
        for k, n in need.items():
            pool = pools[k]
            if not pool:
                continue
            take = rng.choice(len(pool), size=n, replace=len(pool) < n)
            b += [pool[i] for i in take]
        baskets.append(b)
    return matched, baskets, short


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
    pick_beta: list[float] = field(default_factory=list)
    # B7, filled only for rules named in walk_forward(matched_for=...)
    matched: list[float] = field(default_factory=list)       # pick mean - matched mean
    matched_pick_beta: list[float] = field(default_factory=list)
    matched_ctrl_beta: list[float] = field(default_factory=list)
    matched_unbeta: list[int] = field(default_factory=list)  # picks with no beta
    matched_short: list[int] = field(default_factory=list)

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
            "avg_pick_beta": (float(np.nanmean(self.pick_beta))
                              if any(x == x for x in self.pick_beta) else None),
            **self._matched_summary(),
        }

    def _matched_summary(self) -> dict:
        m = np.array([x for x in self.matched if x == x])
        if len(m) == 0:
            return {}
        se = m.std(ddof=1) / np.sqrt(len(m)) if len(m) > 1 else float("nan")
        return {
            "vs_matched": float(m.mean()),
            "vs_matched_n": int(len(m)),
            "vs_matched_beat_rate": float((m > 0).mean()),
            "vs_matched_t": float(m.mean() / se) if se and se == se and se > 0 else None,
            "matched_pick_beta": float(np.nanmean(self.matched_pick_beta)),
            "matched_ctrl_beta": float(np.nanmean(self.matched_ctrl_beta)),
            "matched_unbeta_picks": int(sum(self.matched_unbeta)),
            "matched_short_deciles": int(sum(self.matched_short)),
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


def _beta_col(tab: pd.DataFrame) -> pd.Series:
    return tab["beta"] if "beta" in tab.columns else pd.Series(dtype=float)


def rule_legacy_bn(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK) -> list[str]:
    """B5: legacy's score, picked within beta buckets."""
    return within_beta_buckets(tab["cond"], _beta_col(tab), n)


def rule_excess_bn(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK) -> list[str]:
    """B5: excess, picked within beta buckets."""
    return within_beta_buckets(tab["excess"], _beta_col(tab), n)


def rule_scanner_bn(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK) -> list[str]:
    """B5: the scanner composite, picked within beta buckets."""
    if scan is None or scan.empty:
        return []
    return within_beta_buckets(scan.reindex(tab.index), _beta_col(tab), n)


def rule_blend_bn(tab: pd.DataFrame, scan: pd.Series | None, n: int = N_PICK) -> list[str]:
    """B6: scanner rank + excess rank, equal weight, within beta buckets."""
    if scan is None or scan.empty:
        return []
    sc = scan.reindex(tab.index)
    both = sc.notna() & tab["excess"].notna()
    if not both.any():
        return []
    score = sc[both].rank(pct=True) + tab.loc[both, "excess"].rank(pct=True)
    return within_beta_buckets(score, _beta_col(tab), n)


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
    "legacy beta-neutral": rule_legacy_bn,
    "excess beta-neutral": rule_excess_bn,
    "scanner beta-neutral": rule_scanner_bn,
    "blend beta-neutral": rule_blend_bn,
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


def _score_matched(res: RunResult, closes: pd.DataFrame, as_of: pd.Timestamp,
                   horizon: int, picks: list[str], beta: pd.Series, seed: int) -> None:
    """B7: this date's picks against their beta-matched random baskets."""
    matched, baskets, short = beta_matched_baskets(picks, beta, seed=seed)
    res.matched_unbeta.append(len(picks) - len(matched))
    res.matched_short.append(short)
    if not matched or not baskets:
        res.matched.append(float("nan"))
        res.matched_pick_beta.append(float("nan"))
        res.matched_ctrl_beta.append(float("nan"))
        return
    names = sorted(set(matched) | {t for b in baskets for t in b})
    fwd = realised(closes, as_of, horizon, names)
    pick_ret = fwd.reindex(matched).dropna()
    ctrl = [fwd.reindex(b).dropna().mean() for b in baskets]
    ctrl = [c for c in ctrl if c == c]
    if pick_ret.empty or not ctrl:
        res.matched.append(float("nan"))
    else:
        res.matched.append(float(pick_ret.mean()) - float(np.mean(ctrl)))
    res.matched_pick_beta.append(float(beta.reindex(matched).mean()))
    res.matched_ctrl_beta.append(float(np.mean([beta.reindex(b).mean() for b in baskets])))


def walk_forward(closes: pd.DataFrame, horizon: int, as_of_dates: list[pd.Timestamp],
                 rules: dict = None, n_pick: int = N_PICK,
                 verbose: bool = True,
                 matched_for: tuple = ()) -> dict[str, RunResult]:
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
        cands.table["beta"] = trailing_beta(closes, as_of, list(cands.table.index))
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
            res.pick_beta.append(float(cands.table["beta"].reindex(picks).mean())
                                 if picks else float("nan"))
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
            if name in matched_for:
                _score_matched(res, closes, as_of, horizon, picks,
                               cands.table["beta"], seed=10_000 + i)
        if verbose:
            print(" | ".join(line), flush=True)
    return results
