"""Event windows, returns, abnormal returns and volatility for one IPO.

Every function here works on plain pandas objects (prices indexed by date),
so it can be tested with made-up numbers and never touches the network.

Conventions (fixed before looking at any results):
- Day 0 is the first trading day. Entry is the day-0 open, exit is the
  day-N close, for N = 0..MAX_N trading days.
- ROUND_TRIP_COST (buy + sell together) is subtracted once from the IPO
  return. It is not subtracted from the benchmark, which is a yardstick,
  not a trade.
- If an IPO has fewer than MAX_N + 1 bars, only the available N are
  returned; nothing is filled in.
"""

from __future__ import annotations

import math
import warnings

import numpy as np
import pandas as pd

MAX_N = 20
MAX_DAY0_LAG_DAYS = 4  # calendar days between ipo_date and the first bar before we warn
ROUND_TRIP_COST = 0.002  # 0.2% for buying and selling together
VOL_DAYS = 10
TRADING_DAYS_PER_YEAR = 252


def find_day0(prices: pd.DataFrame, ipo_date) -> pd.Timestamp:
    """First bar on or after the IPO date (pitfall 5: warn if it is far from it)."""
    ipo_date = pd.Timestamp(ipo_date)
    candidates = prices.index[prices.index >= ipo_date]
    if len(candidates) == 0:
        raise ValueError(f"no prices on or after the IPO date {ipo_date.date()}")
    day0 = candidates[0]
    lag = (day0 - ipo_date).days
    if lag > MAX_DAY0_LAG_DAYS:
        warnings.warn(f"day 0 is {day0.date()}, {lag} days after the IPO date "
                      f"{ipo_date.date()}; check the date")
    return day0


def missed_trading_days(market_dates: pd.DatetimeIndex, ipo_date,
                        day0: pd.Timestamp) -> pd.DatetimeIndex:
    """Market trading days from the IPO date up to (not including) our day 0.

    Non-empty means the data is missing the IPO's real first day(s), so our
    "day 0" is not the first trade (Klarna: Yahoo has no bar for 2025-09-10).
    The calendar-day check in find_day0 cannot see this when the gap is short.
    """
    ipo_date = pd.Timestamp(ipo_date)
    return market_dates[(market_dates >= ipo_date) & (market_dates < day0)]


def trading_window(prices: pd.DataFrame, day0: pd.Timestamp,
                   max_n: int = MAX_N) -> pd.DataFrame:
    """Bars for day 0 through day max_n (fewer if the data ends early).

    The index is replaced by N = 0, 1, 2, ...; the original dates are kept
    in a 'Date' column so the benchmark can be matched on the same days.
    """
    window = prices.loc[day0:].iloc[: max_n + 1].copy()
    entry = window["Open"].iloc[0]
    if not entry > 0:  # also catches NaN; Yahoo sometimes reports a 0 open for old IPOs
        raise ValueError(f"invalid day-0 open on {day0.date()}: {entry}")
    window["Date"] = window.index
    window.index = pd.RangeIndex(len(window), name="N")
    return window


def buy_and_hold_returns(window: pd.DataFrame) -> pd.Series:
    """Return from the day-0 open to each day-N close, before costs."""
    return window["Close"] / window["Open"].iloc[0] - 1


def benchmark_window(benchmark: pd.DataFrame, dates: pd.Series) -> pd.DataFrame:
    """Benchmark bars on exactly the same dates as the IPO window."""
    matched = benchmark.reindex(pd.DatetimeIndex(dates))
    missing = matched["Close"].isna()
    if missing.any():
        first_missing = pd.DatetimeIndex(dates)[missing.to_numpy()][0]
        raise ValueError(f"benchmark has no bar on {first_missing.date()}")
    matched.index = pd.RangeIndex(len(matched), name="N")
    return matched


def event_returns(prices: pd.DataFrame, benchmark: pd.DataFrame, ipo_date,
                  max_n: int = MAX_N, cost: float = ROUND_TRIP_COST) -> pd.DataFrame:
    """IPO, benchmark and abnormal return for each holding period N.

    abnormal_return = (IPO return - cost) - benchmark return, over the same days.
    """
    day0 = find_day0(prices, ipo_date)
    window = trading_window(prices, day0, max_n)
    bench = benchmark_window(benchmark, window["Date"])

    ipo_ret = buy_and_hold_returns(window) - cost
    bench_ret = buy_and_hold_returns(bench)
    return pd.DataFrame({
        "date": window["Date"],
        "ipo_return": ipo_ret,
        "benchmark_return": bench_ret,
        "abnormal_return": ipo_ret - bench_ret,
    })


# --- Volatility ---------------------------------------------------------------

def day0_range(prices: pd.DataFrame, ipo_date) -> float:
    """(High - Low) / Open on day 0: how far the price swung on the first day."""
    bar = prices.loc[find_day0(prices, ipo_date)]
    return float((bar["High"] - bar["Low"]) / bar["Open"])


def annualized_volatility(closes: pd.Series, days: int = VOL_DAYS) -> float:
    """Annualised std of daily log returns, close to close, over days 1..`days`.

    Uses closes for days 0..`days`, so the first return is close(0) -> close(1).
    The day-0 jump from the offer price is deliberately left out; day0_range
    measures the first day separately. NaN if there are fewer than 2 returns.
    """
    log_returns = np.log(closes.iloc[: days + 1]).diff().dropna()
    if len(log_returns) < 2:
        return math.nan
    return float(log_returns.std(ddof=1) * math.sqrt(TRADING_DAYS_PER_YEAR))
