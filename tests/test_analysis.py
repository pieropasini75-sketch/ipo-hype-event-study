"""Tests for ipo_study.analysis. Made-up numbers only, no network."""

import math

import pandas as pd
import pytest

from ipo_study.analysis import choose_best_n, is_hype, period_of, summarize, summary_table


def test_best_n_is_chosen_by_t_stat_not_by_mean():
    # The example used to fix the rule. N=3 has the higher mean (+8%) only
    # because of one +60% IPO; N=10 earns less (+4%) but beats the market
    # every time, so it has the higher t-statistic and must be chosen.
    returns = {
        3: [0.60, -0.10, -0.05, -0.08, 0.03],
        10: [0.06, 0.04, 0.05, 0.03, 0.02],
    }
    panel = pd.DataFrame(
        [{"group": "hype", "period": "train", "N": n, "abnormal_return": r}
         for n, values in returns.items() for r in values]
    )

    assert choose_best_n(summary_table(panel)) == 10


def test_period_boundaries():
    assert period_of("2019-12-31") == "train"
    assert period_of("2020-01-02") == "test"
    assert period_of("2009-06-01") is None


def test_hype_needs_both_conditions():
    assert is_hype(12.0, 10.0, 500_000_000) is True   # exactly +20% and exactly US$500M
    assert is_hype(11.9, 10.0, 600_000_000) is False   # pop too small
    assert is_hype(12.0, 10.0, 400_000_000) is False   # deal too small


def test_summarize_basic_stats():
    s = summarize(pd.Series([0.1, -0.2, 0.3, 0.4]))
    assert s["mean"] == pytest.approx(0.15)
    assert s["median"] == pytest.approx(0.2)
    assert s["hit_rate"] == pytest.approx(0.75)
    assert s["ci_low"] <= s["mean"] <= s["ci_high"]


def test_constant_sample_has_no_t_stat():
    s = summarize(pd.Series([0.05, 0.05, 0.05, 0.05]))
    assert math.isnan(s["t_stat"])


def test_choose_best_n_fails_without_hyped_ipos():
    panel = pd.DataFrame({"group": ["no_hype"] * 2, "period": ["train"] * 2,
                          "N": [0, 0], "abnormal_return": [0.01, 0.02]})
    with pytest.raises(ValueError):
        choose_best_n(summary_table(panel))



def test_prospective_verdict_is_pending_until_n_star_and_never_extrapolates():
    # A new IPO with 4 trading days (N = 0..3) and N* = 6: the trade is not
    # finished, so there is no result at N* and no percentile, only the latest N.
    from ipo_study.analysis import prospective_verdict

    curve = pd.Series([-0.15, -0.21, -0.17, -0.19], index=range(4))
    reference = pd.Series([-0.30, -0.10, 0.05, 0.40])

    pending = prospective_verdict(curve, n_star=6, reference=reference)
    assert pending["status"].startswith("pending")
    assert math.isnan(pending["abnormal_at_n_star"])
    assert pending["abnormal_at_last_n"] == pytest.approx(-0.19)

    # Once day N* exists, the value is placed in the reference distribution:
    # -0.20 beats only the -0.30 IPO, so it sits at the 25th percentile.
    final = prospective_verdict(pd.concat([curve, pd.Series([-0.18, -0.19, -0.20], index=[4, 5, 6])]),
                                n_star=6, reference=reference)
    assert final["status"] == "final"
    assert final["percentile_in_reference"] == pytest.approx(0.25)


def test_suspect_data_flags_inconsistent_split_adjustment():
    # Lexin-like: open 87% below the offer (a later ADS-ratio change Yahoo applied
    # to prices but not to its split list). A normal +30% pop is not flagged, and
    # neither is a direct listing (no offer) with ordinary daily moves.
    from ipo_study.analysis import max_daily_move, suspect_data

    table = pd.DataFrame({
        "day0_open": [1.18, 13.0, 10.0, 20.0],
        "adjusted_offer": [9.0, 10.0, float("nan"), 20.0],
        "max_daily_move": [1.1, 1.4, 1.2, 4.5],  # the last one jumps 4.5x in one day
    })
    assert suspect_data(table).tolist() == [True, False, False, True]
    # A fall to a quarter counts the same as a quadrupling.
    assert max_daily_move(pd.Series([10.0, 2.5, 2.6])) == pytest.approx(4.0)
