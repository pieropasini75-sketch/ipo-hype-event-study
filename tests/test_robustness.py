"""Tests for the multiple-testing and investor-risk tools. Made-up numbers only."""

import numpy as np
import pandas as pd

from ipo_study.analysis import max_t_bootstrap


def test_strong_real_effect_survives_the_max_t_correction():
    # 30 IPOs that all beat the market by about 5% at every N, with little
    # noise. Searching over 21 N cannot explain an effect this strong, so the
    # adjusted p-value must be tiny.
    rng = np.random.default_rng(0)
    curves = pd.DataFrame(0.05 + rng.normal(0, 0.02, size=(30, 21)))

    result = max_t_bootstrap(curves, n_resamples=2_000)

    assert result["p_adjusted"] < 0.01
