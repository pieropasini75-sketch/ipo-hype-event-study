"""Tests for ipo_study.events. Made-up numbers only, no network."""

import math 
import pandas as pd
import pytest

from ipo_study.events import (
    ROUND_TRIP_COST,
    annualized_volatility,
    day0_range,
    event_returns,
    find_day0,
    missed_trading_days,
)


def test_abnormal_return_is_ten_percent_minus_cost_when_market_is_flat():
    # IPO opens at 10 and closes at 11 the next day: +10%.
    # The benchmark does not move at all, so the abnormal return is
    # the IPO return minus the round-trip cost: 10% - 0.2% = 9.8%.
    dates = pd.to_datetime(["2020-01-02", "2020-01-03"])
    ipo = pd.DataFrame({"Open": [10.0, 10.5], "Close": [10.5, 11.0]}, index=dates)
    market = pd.DataFrame({"Open": [100.0, 100.0], "Close": [100.0, 100.0]}, index=dates)

    result = event_returns(ipo, market, "2020-01-02")

    assert result.loc[1, "abnormal_return"] == pytest.approx(0.10 - ROUND_TRIP_COST)


def test_day0_is_first_bar_on_or_after_ipo_date():
    prices = pd.DataFrame({"Open": [10.0]}, index=pd.to_datetime(["2020-01-06"]))  # Monday
    assert find_day0(prices, "2020-01-04") == pd.Timestamp("2020-01-06")  # Saturday


def test_day0_far_from_ipo_date_warns():
    prices = pd.DataFrame({"Open": [10.0]}, index=pd.to_datetime(["2020-01-10"]))
    with pytest.warns(UserWarning):
        find_day0(prices, "2020-01-01")  # a date more than 4 days before


def test_abnormal_return_subtracts_the_market():
    dates = pd.to_datetime(["2020-01-02", "2020-01-03"])
    ipo = pd.DataFrame({"Open": [10.0, 10.5], "Close": [10.5, 11.0]}, index=dates)
    market = pd.DataFrame({"Open": [100.0, 101.0], "Close": [101.0, 105.0]}, index=dates)
    result = event_returns(ipo, market, "2020-01-02")
    assert result.loc[1, "abnormal_return"] == pytest.approx(0.10 - ROUND_TRIP_COST - 0.05)


def test_short_history_returns_only_available_days():
    dates = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-01-06"])
    ipo = pd.DataFrame({"Open": [10.0] * 3, "Close": [10.0] * 3}, index=dates)
    market = pd.DataFrame({"Open": [100.0] * 3, "Close": [100.0] * 3}, index=dates)
    assert len(event_returns(ipo, market, "2020-01-02")) == 3


def test_zero_open_raises():
    dates = pd.to_datetime(["2020-01-02"])
    ipo = pd.DataFrame({"Open": [0.0], "Close": [10.0]}, index=dates)
    market = pd.DataFrame({"Open": [100.0], "Close": [100.0]}, index=dates)
    with pytest.raises(ValueError):
        event_returns(ipo, market, "2020-01-02")


def test_day0_range():
    prices = pd.DataFrame({"Open": [10.0], "High": [12.0], "Low": [9.0]},
                          index=pd.to_datetime(["2020-01-02"]))
    assert day0_range(prices, "2020-01-02") == pytest.approx(0.3)


def test_flat_prices_have_zero_volatility():
    assert annualized_volatility(pd.Series([10.0] * 11)) == 0.0


def test_missing_first_day_is_detected():
    # Klarna-like: the market traded on the IPO date, but our first bar is a day later.
    market = pd.to_datetime(["2025-09-09", "2025-09-10", "2025-09-11"])
    missed = missed_trading_days(market, "2025-09-10", pd.Timestamp("2025-09-11"))
    assert list(missed) == [pd.Timestamp("2025-09-10")]


def test_weekend_ipo_date_is_not_a_missing_day():
    # IPO date is a Saturday; the market did not trade until Monday, so nothing is missing.
    market = pd.to_datetime(["2020-01-03", "2020-01-06"])
    missed = missed_trading_days(market, "2020-01-04", pd.Timestamp("2020-01-06"))
    assert len(missed) == 0

