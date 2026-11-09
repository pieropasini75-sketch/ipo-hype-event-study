"""Tests for ipo_study.nasdaq. Made-up responses only, no network."""

import math

import pandas as pd

from ipo_study.nasdaq import parse_priced


def test_parse_priced_turns_text_into_numbers_and_dates():
    # Shaped like a real Nasdaq row: every value arrives as text with $ and commas.
    payload = {"data": {"priced": {"rows": [{
        "dealID": "665410-63240",
        "proposedTickerSymbol": "TSLA",
        "companyName": "Tesla, Inc.",
        "proposedExchange": "Nasdaq National Market",
        "proposedSharePrice": "17.00",
        "sharesOffered": "13,300,000",
        "pricedDate": "6/29/2010",
        "dollarValueOfSharesOffered": "$226,100,000",
        "dealStatus": "Priced",
    }]}}}

    row = parse_priced(payload).iloc[0]

    assert row["offer_price"] == 17.0
    assert row["shares_offered"] == 13_300_000
    assert row["nasdaq_dollar_value"] == 226_100_000
    assert row["priced_date"] == pd.Timestamp("2010-06-29")
    assert not math.isnan(row["offer_price"])
