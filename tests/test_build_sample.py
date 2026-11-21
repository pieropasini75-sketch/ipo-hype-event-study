"""Tests for the v2 sample filter. Made-up calendar rows only, no network."""

import pandas as pd

from build_sample import exclusion_reason


def test_spac_listed_under_its_merger_target_name_is_still_excluded():
    # Nasdaq shows a SPAC under the *current* name of the company it later bought,
    # so the name looks like a real business. Its unit ticker gives it away; a
    # plain $10.00 offer from 2019 on does too. A normal IPO must stay in.
    calendar = pd.DataFrame({
        "ticker": ["RTP'U", "KVSB", "ABCD"],
        "company": ["Joby Aviation, Inc.", "Nextdoor Holdings, Inc.", "Real Company Inc."],
        "exchange": ["NYSE", "NASDAQ Global Select", "NASDAQ Global Select"],
        "offer_price": [10.0, 10.0, 18.0],
        "shares_offered": [60e6, 40e6, 10e6],
        "priced_date": pd.to_datetime(["2020-08-13", "2021-01-26", "2021-03-02"]),
    })

    reasons = exclusion_reason(calendar).tolist()

    assert reasons[0] == "unit / warrant / right"
    assert reasons[1].startswith("likely SPAC")
    assert pd.isna(reasons[2])  # pandas stores "no reason" as NaN, not None
