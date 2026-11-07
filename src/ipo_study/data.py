"""Download and cache daily prices and split histories from Yahoo Finance.

This is the only module that touches the network. Everything downstream reads
the cached CSV files in data/prices/, so the analysis is reproducible and does
not depend on Yahoo being available (or silently changing its data).
"""

from __future__ import annotations

import sys
import warnings
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import yfinance as yf

PROJECT_ROOT = Path(__file__).resolve().parents[2]
IPOS_CSV = PROJECT_ROOT / "data" / "ipos.csv"
PRICES_DIR = PROJECT_ROOT / "data" / "prices"

DAYS_BEFORE = 7  # calendar days before the IPO date; any bar here means a wrong ticker or date
DAYS_AFTER = 90  # calendar days after the IPO date; comfortably covers 20 trading days
BENCHMARKS = ("QQQ", "SPY")
PRICE_COLUMNS = ["Open", "High", "Low", "Close", "Adj Close", "Volume"]


# --- IPO list -----------------------------------------------------------------

def load_ipos(path: Path = IPOS_CSV) -> pd.DataFrame:
    """Read the IPO list and check that offer_size_usd = offer_price * shares_offered."""
    ipos = pd.read_csv(path, parse_dates=["ipo_date"])
    implied = ipos["offer_price"] * ipos["shares_offered"]
    # Direct listings have NaN in both columns; NaN > 1 is False, so they pass.
    mismatch = (ipos["offer_size_usd"] - implied).abs() > 1
    if mismatch.any():
        bad = ipos.loc[mismatch, "ticker"].tolist()
        raise ValueError(f"offer_size_usd != offer_price * shares_offered for {bad}")
    return ipos


def event_window(ipo_date) -> tuple[date, date]:
    """Calendar range to download for one IPO: DAYS_BEFORE before to DAYS_AFTER after."""
    ipo_date = pd.Timestamp(ipo_date)
    start = ipo_date - pd.Timedelta(days=DAYS_BEFORE)
    end = ipo_date + pd.Timedelta(days=DAYS_AFTER)
    return start.date(), end.date()


def benchmark_window(ipos: pd.DataFrame) -> tuple[date, date]:
    """One range that covers the event window of every IPO in the list."""
    first_start, _ = event_window(ipos["ipo_date"].min())
    _, last_end = event_window(ipos["ipo_date"].max())
    return first_start, last_end


# --- Download and cache -------------------------------------------------------

def _to_dates(index: pd.Index) -> pd.DatetimeIndex:
    """Drop time zone and time of day.

    Yahoo stamps daily bars at midnight New York time and splits at 09:30.
    We only care about the trading date, and naive dates compare cleanly
    with the dates in ipos.csv.
    """
    index = pd.DatetimeIndex(index)
    if index.tz is not None:
        index = index.tz_localize(None)
    return index.normalize()


def _download(ticker: str, start: date, end: date) -> tuple[pd.DataFrame, pd.Series]:
    """Fetch daily prices for [start, end] and the full split history of `ticker`."""
    yt = yf.Ticker(ticker)
    # auto_adjust=False keeps the raw Close (no dividend adjustment). Yahoo still
    # adjusts OHLC for splits; adjusted_offer_price() puts the offer on that scale.
    # history() treats `end` as exclusive, so ask for one extra day.
    prices = yt.history(start=start, end=end + timedelta(days=1),
                        auto_adjust=False, actions=False)
    splits = yt.splits
    if prices.empty:
        return prices, splits

    prices = prices[PRICE_COLUMNS]
    prices.index = _to_dates(prices.index)
    prices.index.name = "Date"

    splits = splits.copy()
    splits.index = _to_dates(splits.index)
    splits.index.name = "Date"
    splits.name = "ratio"
    return prices, splits


def get_ticker_data(ticker: str, start: date, end: date,
                    cache_dir: Path = PRICES_DIR,
                    refresh: bool = False) -> tuple[pd.DataFrame, pd.Series]:
    """Daily prices and split history for one ticker, read from cache when possible.

    Prices and splits are always downloaded and cached together. Yahoo's prices
    are split-adjusted *as of the download date*; if a new split happened later
    and only the split file were refreshed, the two files would disagree and the
    adjusted offer price would be wrong.
    """
    stem = f"{ticker}_{start}_{end}"
    prices_path = cache_dir / f"{stem}_prices.csv"
    splits_path = cache_dir / f"{stem}_splits.csv"

    if prices_path.exists() and splits_path.exists() and not refresh:
        prices = pd.read_csv(prices_path, index_col="Date", parse_dates=True)
        splits = pd.read_csv(splits_path, index_col="Date", parse_dates=True)["ratio"]
        splits.index = pd.DatetimeIndex(splits.index)  # an empty file reads back as plain strings
        return prices, splits

    prices, splits = _download(ticker, start, end)
    if prices.empty:
        # Not cached, so a temporary network failure is retried on the next run.
        warnings.warn(f"{ticker}: Yahoo returned no prices for {start}..{end} "
                      "(delisted, renamed or wrong ticker?)")
        return prices, splits
    if end >= date.today():
        # The window is still open; caching now would freeze incomplete data.
        warnings.warn(f"{ticker}: window ends {end}, not finished yet; not cached")
        return prices, splits

    cache_dir.mkdir(parents=True, exist_ok=True)
    prices.to_csv(prices_path)
    splits.to_csv(splits_path)
    return prices, splits


# --- Split adjustment and sanity checks ---------------------------------------

def split_factor_after(splits: pd.Series, when) -> float:
    """Product of all split ratios with an ex-date strictly after `when`.

    A 5-for-1 split is stored as 5.0 and a 1-for-10 reverse split as 0.1, so the
    product is how many of today's shares one share held on `when` became.
    The product of an empty series is 1.0: no splits, no adjustment.
    """
    later = splits[splits.index > pd.Timestamp(when)]
    return float(later.prod())


def adjusted_offer_price(offer_price: float, splits: pd.Series, ipo_date) -> float:
    """Offer price on the same split-adjusted scale as Yahoo's prices."""
    return offer_price / split_factor_after(splits, ipo_date)


def has_prices_before(prices: pd.DataFrame, ipo_date) -> bool:
    """True if Yahoo has bars before the IPO date: the ticker was reused or the date is wrong."""
    return bool((prices.index < pd.Timestamp(ipo_date)).any())


def load_all_ipos(ipos: pd.DataFrame, cache_dir: Path = PRICES_DIR,
                  refresh: bool = False) -> dict[str, tuple[pd.DataFrame, pd.Series]]:
    """Prices and splits for every IPO, dropping (with a warning) the ones that fail checks."""
    out = {}
    for row in ipos.itertuples(index=False):
        start, end = event_window(row.ipo_date)
        prices, splits = get_ticker_data(row.ticker, start, end, cache_dir, refresh)
        if prices.empty:
            continue  # get_ticker_data already warned
        if has_prices_before(prices, row.ipo_date):
            warnings.warn(f"{row.ticker}: prices exist before the IPO date "
                          f"{row.ipo_date.date()}; wrong ticker or date, dropped")
            continue
        out[row.ticker] = (prices, splits)
    return out


def load_benchmarks(ipos: pd.DataFrame, cache_dir: Path = PRICES_DIR,
                    refresh: bool = False) -> dict[str, pd.DataFrame]:
    """Daily prices for QQQ and SPY over a range covering every IPO window."""
    start, end = benchmark_window(ipos)
    return {b: get_ticker_data(b, start, end, cache_dir, refresh)[0] for b in BENCHMARKS}


# --- Manual check: python -m ipo_study.data TSLA ARM ---------------------------

def main(tickers: list[str]) -> None:
    ipos = load_ipos().set_index("ticker")
    for ticker in tickers:
        row = ipos.loc[ticker]
        start, end = event_window(row["ipo_date"])
        prices, splits = get_ticker_data(ticker, start, end)
        if prices.empty:
            continue
        factor = split_factor_after(splits, row["ipo_date"])
        offer = adjusted_offer_price(row["offer_price"], splits, row["ipo_date"])
        first = prices.iloc[0]
        print(f"{ticker}: {len(prices)} bars, first {prices.index[0].date()} "
              f"(IPO date {row['ipo_date'].date()}) | split factor {factor:g} | "
              f"offer ${row['offer_price']:g} -> ${offer:.4f} adjusted | "
              f"day-0 open ${first['Open']:.4f}")


if __name__ == "__main__":
    main(sys.argv[1:] or ["TSLA", "ARM"])
