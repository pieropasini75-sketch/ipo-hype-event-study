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
import warnings

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
        key = data.ipo_id(row.ticker, row.ipo_date)
        if key not in ipo_data:
            continue  # dropped in data.load_all_ipos, already warned
        period = period_of(row.ipo_date)
        if period is None:
            continue
        prices, splits = ipo_data[key]

        day0 = events.find_day0(prices, row.ipo_date)
        missed = events.missed_trading_days(benchmark.index, row.ipo_date, day0)
        if len(missed):
            warnings.warn(f"{row.ticker}: no bar on {missed[0].date()} although the market "
                          "traded; the first trade is missing from the data, dropped")
            continue

        ev = events.event_returns(prices, benchmark, row.ipo_date)
        day0_open = float(prices.loc[day0, "Open"])

        if row.listing_type == "direct_listing":
            group, adjusted_offer = "direct_listing", math.nan
        else:
            adjusted_offer = data.adjusted_offer_price(row.offer_price, splits, row.ipo_date)
            hyped = is_hype(day0_open, adjusted_offer, row.offer_size_usd)
            group = "hype" if hyped else "no_hype"

        ev = ev.reset_index()  # N becomes a column
        ev.insert(0, "ipo_id", key)
        ev.insert(1, "ticker", row.ticker)
        ev.insert(2, "group", group)
        ev.insert(3, "period", period)
        panel_parts.append(ev)

        bench_closes = benchmark["Close"].reindex(pd.DatetimeIndex(ev["date"]))
        ipo_rows.append({
            "ipo_id": key,
            "ticker": row.ticker,
            "group": group,
            "period": period,
            "day0": day0,
            "day0_open": day0_open,
            "adjusted_offer": adjusted_offer,
            "open_premium": day0_open / adjusted_offer - 1,
            "offer_size_usd": row.offer_size_usd,
            "n_days": len(ev),
            "max_daily_move": max_daily_move(prices.loc[day0:, "Close"].iloc[: events.MAX_N + 1]),
            "day0_range": events.day0_range(prices, row.ipo_date),
            "vol_10d": events.annualized_volatility(prices.loc[day0:, "Close"]),
            "benchmark_vol_10d": events.annualized_volatility(bench_closes.reset_index(drop=True)),
        })

    return pd.concat(panel_parts, ignore_index=True), pd.DataFrame(ipo_rows)


# --- Data-quality screen (robustness only) -------------------------------------
# Added 2026-11-24 AFTER seeing the v2 extremes, so it is reported as a robustness
# check and never replaces the main result. Small IPOs with later reverse splits or
# ADS-ratio changes sometimes come back from Yahoo inconsistently adjusted:
# Lexin (LX, 2017) shows a day-0 open 87% below its offer and then +1,364% in six days.

SUSPECT_FACTOR = 3.0  # a factor of 3 between offer and open, or within one day


def max_daily_move(closes: pd.Series) -> float:
    """Largest close-to-close move in either direction, as a factor (>= 1)."""
    ratio = (closes / closes.shift(1)).dropna()
    if ratio.empty:
        return 1.0
    return float(np.maximum(ratio, 1 / ratio).max())


def suspect_data(ipo_table: pd.DataFrame, factor: float = SUSPECT_FACTOR) -> pd.Series:
    """True for IPOs whose prices look inconsistently split-adjusted.

    Flags a day-0 open more than `factor` times away from the adjusted offer
    price (either direction), or a single day in the window moving by more
    than `factor`. Direct listings have no offer, so only the second test applies.
    """
    ratio = ipo_table["day0_open"] / ipo_table["adjusted_offer"]
    bad_open = (ratio > factor) | (ratio < 1 / factor)  # NaN compares False
    return bad_open | (ipo_table["max_daily_move"] > factor)


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


# --- Multiple testing: centered bootstrap of the max t (Romano-Wolf) ----------

def curves(panel: pd.DataFrame, group: str, period: str,
           column: str = "abnormal_return") -> pd.DataFrame:
    """One row per IPO, one column per N: each IPO's whole curve from day 0 to 20."""
    sub = panel[(panel["group"] == group) & (panel["period"] == period)]
    return sub.pivot(index="ipo_id", columns="N", values=column)


def t_by_column(x: np.ndarray) -> np.ndarray:
    """One-sample t-statistic against 0 for every column, ignoring missing values."""
    n = np.sum(~np.isnan(x), axis=0)
    mean = np.nanmean(x, axis=0)
    sd = np.nanstd(x, axis=0, ddof=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        return mean / (sd / np.sqrt(n))


def max_t_bootstrap(curve_table: pd.DataFrame, n_resamples: int = BOOTSTRAP_RESAMPLES,
                    seed: int = BOOTSTRAP_SEED) -> dict:
    """p-value for the best N that accounts for having searched over every N.

    Whole curves are resampled (so the correlation between N is kept) and the
    observed mean curve is subtracted, which makes "true mean is 0 at every N"
    hold by construction. Unlike sign-flipping, this does not assume the
    returns are symmetric, which IPO returns are not.
    """
    x = curve_table.to_numpy(dtype=float)
    observed = float(np.nanmax(t_by_column(x)))
    centered = x - np.nanmean(x, axis=0)
    rng = np.random.default_rng(seed)
    n_ipos = len(x)
    exceed = 0
    for _ in range(n_resamples):
        sample = centered[rng.integers(0, n_ipos, size=n_ipos)]
        if np.nanmax(t_by_column(sample)) >= observed:
            exceed += 1
    return {"max_t": observed, "p_adjusted": (1 + exceed) / (1 + n_resamples)}


def label_permutation_test(hype: pd.Series, no_hype: pd.Series,
                           n_resamples: int = BOOTSTRAP_RESAMPLES,
                           seed: int = BOOTSTRAP_SEED) -> dict:
    """Two-sided test of whether the hype label separates abnormal returns.

    If the label meant nothing, shuffling it would give differences in means
    as large as the observed one quite often.
    """
    a, b = hype.dropna().to_numpy(float), no_hype.dropna().to_numpy(float)
    observed = a.mean() - b.mean()
    pooled = np.concatenate([a, b])
    rng = np.random.default_rng(seed)
    exceed = 0
    for _ in range(n_resamples):
        shuffled = rng.permutation(pooled)
        diff = shuffled[: len(a)].mean() - shuffled[len(a):].mean()
        if abs(diff) >= abs(observed):
            exceed += 1
    return {"diff_in_means": float(observed), "p_value": (1 + exceed) / (1 + n_resamples)}


# --- Risk for an investor -----------------------------------------------------

LOSS_THRESHOLD = -0.20
PORTFOLIO_SIZES = (3, 5, 10)


def risk_profile(returns) -> dict:
    """Share losing, share losing more than 20%, median and the 5th/10th percentiles."""
    x = np.asarray(returns, dtype=float)
    x = x[~np.isnan(x)]
    return {
        "n": len(x),
        "share_losing": float((x < 0).mean()),
        "share_losing_20pct": float((x < LOSS_THRESHOLD).mean()),
        "median": float(np.median(x)),
        "p5": float(np.percentile(x, 5)),
        "p10": float(np.percentile(x, 10)),
    }


def single_trade_risk(returns: pd.Series) -> dict:
    """Risk of one trade: direct proportions from the data, no simulation needed."""
    return risk_profile(returns)


def average_of_k_risk(returns: pd.Series, ks=PORTFOLIO_SIZES,
                      n_resamples: int = BOOTSTRAP_RESAMPLES,
                      seed: int = BOOTSTRAP_SEED) -> pd.DataFrame:
    """Monte Carlo: risk of averaging k trades drawn with replacement from real returns."""
    x = returns.dropna().to_numpy(float)
    rng = np.random.default_rng(seed)
    rows = []
    for k in ks:
        averages = rng.choice(x, size=(n_resamples, k), replace=True).mean(axis=1)
        rows.append({"k": k, **risk_profile(averages)})
    return pd.DataFrame(rows).drop(columns="n")


# --- Prospective case (Anthropic) ---------------------------------------------

def prospective_verdict(curve: pd.Series, n_star: int, reference: pd.Series) -> dict:
    """Compare one new IPO with what the study predicted, without re-fitting anything.

    curve     : the new IPO's abnormal return by N (index = N), as far as data exists.
    n_star    : the holding period chosen on the training period, never re-chosen.
    reference : abnormal returns at n_star of hyped test-period IPOs, the
                distribution the study would have used to decide on the trade.

    While fewer than n_star + 1 days have traded the verdict is 'pending' and
    only the latest available N is reported: nothing is extrapolated.
    """
    ref = reference.dropna().to_numpy(float)
    last_n = int(curve.index.max())
    done = n_star in curve.index
    value = float(curve.loc[n_star]) if done else math.nan
    return {
        "status": "final" if done else f"pending ({last_n + 1} of {n_star + 1} days traded)",
        "n_star": n_star,
        "abnormal_at_n_star": value,
        "last_n": last_n,
        "abnormal_at_last_n": float(curve.loc[last_n]),
        # Share of reference IPOs that did worse; NaN until N* is reached.
        "percentile_in_reference": float((ref < value).mean()) if done else math.nan,
        "reference_n": len(ref),
        "reference_median": float(np.median(ref)),
        "reference_share_beat_market": float((ref > 0).mean()),
    }
