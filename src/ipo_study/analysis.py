"""Hype classification, train/test split, summary statistics and the choice of N*.

Rules (fixed before looking at any results):
- Hype: day-0 open >= 1.20 x the split-adjusted offer price AND offer size
  >= US$500M. Both are known at the moment of buying. Direct listings have no
  offer price and form their own group.
- Train: IPOs dated 2010-2019. Test: 2020 onwards. N* is chosen on train only.
- N* is the holding period with the highest t-statistic of the mean abnormal
  return among hyped IPOs in the training period, using QQQ. With few IPOs and
  very skewed returns, the mean alone would be decided by one extreme IPO.
- The SPY robustness check reuses the N* chosen with QQQ; it does not re-choose.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from ipo_study import data, events

HYPE_MIN_OPEN_PREMIUM = 0.20  # day-0 open at least 20% above the offer price
HYPE_MIN_OFFER_SIZE_USD = 500_000_000
TRAIN_FIRST_YEAR, TRAIN_LAST_YEAR = 2010, 2019
TEST_FIRST_YEAR = 2020
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 42
CONFIDENCE_LEVEL = 0.95
WORST_CASE_PERCENTILE = 10


# --- Classification -----------------------------------------------------------

def period_of(ipo_date) -> str | None:
    """'train' for 2010-2019, 'test' for 2020 onwards, None for anything earlier."""
    year = pd.Timestamp(ipo_date).year
    if TRAIN_FIRST_YEAR <= year <= TRAIN_LAST_YEAR:
        return "train"
    if year >= TEST_FIRST_YEAR:
        return "test"
    return None


def is_hype(day0_open: float, adjusted_offer: float, offer_size_usd: float) -> bool:
    """Both hype conditions. Any NaN input makes a comparison False, so the result is False."""
    big_pop = day0_open >= (1 + HYPE_MIN_OPEN_PREMIUM) * adjusted_offer
    big_deal = offer_size_usd >= HYPE_MIN_OFFER_SIZE_USD
    return bool(big_pop and big_deal)


# --- Building the event panel -------------------------------------------------

def build_events(ipos: pd.DataFrame,
                 ipo_data: dict[str, tuple[pd.DataFrame, pd.Series]],
                 benchmark: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Abnormal returns for every IPO and N, plus one descriptive row per IPO.

    Returns
    -------
    panel : one row per (ticker, N) with group, period and the three returns.
    ipo_table : one row per IPO with the hype inputs and the volatility measures.
    """
    panel_parts, ipo_rows = [], []
    for row in ipos.itertuples(index=False):
        if row.ticker not in ipo_data:
            continue  # dropped in data.load_all_ipos, already warned
        period = period_of(row.ipo_date)
        if period is None:
            continue
        prices, splits = ipo_data[row.ticker]

        ev = events.event_returns(prices, benchmark, row.ipo_date)
        day0 = ev["date"].iloc[0]
        day0_open = float(prices.loc[day0, "Open"])

        if row.listing_type == "direct_listing":
            group, adjusted_offer = "direct_listing", math.nan
        else:
            adjusted_offer = data.adjusted_offer_price(row.offer_price, splits, row.ipo_date)
            hyped = is_hype(day0_open, adjusted_offer, row.offer_size_usd)
            group = "hype" if hyped else "no_hype"

        ev = ev.reset_index()  # N becomes a column
        ev.insert(0, "ticker", row.ticker)
        ev.insert(1, "group", group)
        ev.insert(2, "period", period)
        panel_parts.append(ev)

        bench_closes = benchmark["Close"].reindex(pd.DatetimeIndex(ev["date"]))
        ipo_rows.append({
            "ticker": row.ticker,
            "group": group,
            "period": period,
            "day0": day0,
            "day0_open": day0_open,
            "adjusted_offer": adjusted_offer,
            "open_premium": day0_open / adjusted_offer - 1,
            "offer_size_usd": row.offer_size_usd,
            "n_days": len(ev),
            "day0_range": events.day0_range(prices, row.ipo_date),
            "vol_10d": events.annualized_volatility(prices.loc[day0:, "Close"]),
            "benchmark_vol_10d": events.annualized_volatility(bench_closes.reset_index(drop=True)),
        })

    return pd.concat(panel_parts, ignore_index=True), pd.DataFrame(ipo_rows)


# --- Statistics ---------------------------------------------------------------

def summarize(abnormal: pd.Series) -> dict:
    """Mean, median, hit rate, t-test, bootstrap CI and worst case of abnormal returns."""
    x = abnormal.dropna().to_numpy(dtype=float)
    n = len(x)
    out = {
        "n": n,
        "mean": float(x.mean()) if n else math.nan,
        "median": float(np.median(x)) if n else math.nan,
        "hit_rate": float((x > 0).mean()) if n else math.nan,
        "t_stat": math.nan, "p_value": math.nan,
        "ci_low": math.nan, "ci_high": math.nan,
        "worst": float(x.min()) if n else math.nan,
        f"p{WORST_CASE_PERCENTILE}": float(np.percentile(x, WORST_CASE_PERCENTILE)) if n else math.nan,
    }
    if n >= 2 and x.std(ddof=1) > 0:  # a t-test needs spread; a constant sample has none
        test = stats.ttest_1samp(x, popmean=0.0)
        out["t_stat"], out["p_value"] = float(test.statistic), float(test.pvalue)
        ci = stats.bootstrap(
            (x,), np.mean,
            n_resamples=BOOTSTRAP_RESAMPLES,
            confidence_level=CONFIDENCE_LEVEL,
            method="percentile",
            rng=np.random.default_rng(BOOTSTRAP_SEED),
        ).confidence_interval
        out["ci_low"], out["ci_high"] = float(ci.low), float(ci.high)
    return out


def summary_table(panel: pd.DataFrame) -> pd.DataFrame:
    """summarize() for every (group, period, N) in the panel."""
    rows = []
    for (group, period, n), sub in panel.groupby(["group", "period", "N"]):
        rows.append({"group": group, "period": period, "N": n, **summarize(sub["abnormal_return"])})
    return pd.DataFrame(rows)


def choose_best_n(table: pd.DataFrame, group: str = "hype", period: str = "train") -> int:
    """N with the highest t-statistic for `group` in `period` (ties go to the smaller N)."""
    sub = table[(table["group"] == group) & (table["period"] == period)]
    sub = sub.dropna(subset=["t_stat"]).sort_values("N")
    if sub.empty:
        raise ValueError(f"no t-statistics available for group={group!r}, period={period!r}")
    return int(sub.loc[sub["t_stat"].idxmax(), "N"])


def at_n(table: pd.DataFrame, n: int) -> pd.DataFrame:
    """The rows of the summary table for one holding period, one per group and period."""
    return table[table["N"] == n].set_index(["group", "period"]).drop(columns="N")
