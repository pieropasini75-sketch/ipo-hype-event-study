"""Tests for ipo_study.data. Made-up numbers only, no network."""

from datetime import date

import pandas as pd
import pytest

import ipo_study.data as data
from ipo_study.data import (
    adjusted_offer_price,
    has_prices_before,
    load_ipos,
    split_factor_after,
)


def test_split_factor_multiplies_only_splits_after_the_ipo():
    # Tesla-like history: 5-for-1 in 2020 and 3-for-1 in 2022. The 2-for-1 in
    # 2005 is before the IPO and must be ignored, otherwise the factor is 30.
    splits = pd.Series(
        [2.0, 5.0, 3.0],
        index=pd.to_datetime(["2005-01-03", "2020-08-31", "2022-08-25"]),
    )
    assert split_factor_after(splits, "2010-06-29") == 15.0


def test_split_factor_is_one_without_splits():
    splits = pd.Series([], index=pd.DatetimeIndex([]), dtype=float)
    assert split_factor_after(splits, "2010-06-29") == 1.0


def test_reverse_split_shrinks_the_factor():
    # 1-for-10 reverse split after the IPO
    splits = pd.Series([0.1], index=pd.to_datetime(["2023-01-03"]))
    assert split_factor_after(splits, "2020-01-02") == pytest.approx(0.1)


def test_adjusted_offer_price_matches_yahoo_scale():
    splits = pd.Series([5.0, 3.0], index=pd.to_datetime(["2020-08-31", "2022-08-25"]))
    assert adjusted_offer_price(17, splits, "2010-06-29") == pytest.approx(17/15)


def test_has_prices_before_detects_bars_before_the_ipo():
    prices = pd.DataFrame(
        {"Open": [10.0, 11.0]},
        index=pd.to_datetime(["2020-01-02", "2020-01-03"]),
    )
    assert has_prices_before(prices, "2020-01-03") is True
    assert has_prices_before(prices, "2020-01-02") is False


HEADER = "ticker,company,ipo_date,offer_price,shares_offered,offer_size_usd,range_low,range_high,listing_type,notes\n"


def test_load_ipos_rejects_wrong_offer_size(tmp_path):
    csv_path = tmp_path / "ipos.csv"
    csv_path.write_text(HEADER + "AAA,Fake Co,2020-01-02,10,1000,99999,9,11,ipo,\n")
    with pytest.raises(ValueError):
        load_ipos(csv_path)


def test_get_ticker_data_reads_cache_without_network(tmp_path, monkeypatch):
    start, end = date(2020, 1, 1), date(2020, 1, 31)
    fake_prices = pd.DataFrame(
        {"Open": [10.0], "Close": [11.0]},
        index=pd.DatetimeIndex(["2020-01-02"], name="Date"),
    )
    fake_splits = pd.Series([2.0], index=pd.DatetimeIndex(["2021-06-01"], name="Date"), name="ratio")

    # First call: a fake download fills the cache.
    monkeypatch.setattr(data, "_download", lambda ticker, s, e: (fake_prices, fake_splits))
    data.get_ticker_data("FAKE", start, end, cache_dir=tmp_path)

    # Second call: downloading now fails loudly. If the function uses it, the test fails.
    def no_network(*args):
        raise AssertionError("should have read from the cache")
    monkeypatch.setattr(data, "_download", no_network)

    prices, splits = data.get_ticker_data("FAKE", start, end, cache_dir=tmp_path)
    assert prices["Close"].tolist() == [11.0]
    assert splits.tolist() == [2.0]


