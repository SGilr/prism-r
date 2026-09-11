"""Tests for the exact confidence intervals in pipeline/exact_ci.py.

The implementation carries its own special functions rather than depending
on SciPy, so it is checked against published Clopper-Pearson limits and
against the properties an exact interval must have. The reference values
are from the standard tables reproduced in textbook treatments of the
binomial interval, and are quoted to four decimal places.
"""

import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline.exact_ci import (  # noqa: E402
    beta_quantile,
    clopper_pearson,
    exact_rate_ratio_interval,
    regularised_incomplete_beta,
)


# --------------------------------------------------------------------------
# The incomplete beta, against values that can be checked in closed form
# --------------------------------------------------------------------------
def test_incomplete_beta_matches_closed_forms():
    # I_x(1, 1) = x, since Beta(1,1) is uniform.
    for x in (0.1, 0.25, 0.5, 0.9):
        assert regularised_incomplete_beta(1, 1, x) == pytest.approx(x, abs=1e-12)
    # I_x(1, 2) = 1 - (1 - x)^2, and I_x(2, 1) = x^2.
    for x in (0.2, 0.6):
        assert regularised_incomplete_beta(1, 2, x) == pytest.approx(
            1 - (1 - x) ** 2, abs=1e-12)
        assert regularised_incomplete_beta(2, 1, x) == pytest.approx(
            x ** 2, abs=1e-12)


def test_incomplete_beta_is_bounded_and_monotonic():
    previous = 0.0
    for i in range(0, 101):
        value = regularised_incomplete_beta(2.5, 7.5, i / 100)
        assert 0.0 <= value <= 1.0
        assert value >= previous
        previous = value


def test_beta_quantile_inverts_the_incomplete_beta():
    for a, b in ((2, 8), (5, 5), (0.5, 3), (20, 3)):
        for p in (0.025, 0.5, 0.975):
            x = beta_quantile(p, a, b)
            assert regularised_incomplete_beta(a, b, x) == pytest.approx(p, abs=1e-9)


# --------------------------------------------------------------------------
# Clopper-Pearson, against published limits
# --------------------------------------------------------------------------
@pytest.mark.parametrize("successes,trials,lower,upper", [
    (2, 10, 0.0252, 0.5561),
    (5, 20, 0.0866, 0.4910),
    (1, 100, 0.0003, 0.0545),
    (0, 10, 0.0000, 0.3085),   # no successes: the lower limit is exactly 0
    (10, 10, 0.6915, 1.0000),  # all successes: the upper limit is exactly 1
])
def test_clopper_pearson_matches_published_limits(successes, trials, lower, upper):
    got_lower, got_upper = clopper_pearson(successes, trials)
    assert got_lower == pytest.approx(lower, abs=6e-4)
    assert got_upper == pytest.approx(upper, abs=6e-4)


def test_clopper_pearson_brackets_the_point_estimate():
    for successes, trials in ((3, 17), (9, 26), (40, 80), (1, 5)):
        lower, upper = clopper_pearson(successes, trials)
        assert lower <= successes / trials <= upper


def test_clopper_pearson_rejects_impossible_input():
    with pytest.raises(ValueError):
        clopper_pearson(5, 0)
    with pytest.raises(ValueError):
        clopper_pearson(11, 10)


# --------------------------------------------------------------------------
# The rate ratio interval
# --------------------------------------------------------------------------
def test_interval_brackets_the_rate_ratio():
    """Whatever else it does, the interval must contain the estimate."""
    cases = [(7, 12000, 260, 480000), (26, 47000, 900, 1200000),
             (10326, 430000, 9800, 980000), (50, 9000, 320, 210000)]
    for events, total, baseline_events, baseline_total in cases:
        lower, upper = exact_rate_ratio_interval(
            events, total, baseline_events, baseline_total)
        rri = (events / total) / (baseline_events / baseline_total)
        assert lower <= rri <= upper


def test_the_interval_is_wider_than_wald_at_small_counts():
    """The reason for the method: at small counts the normal approximation
    is optimistic, so the exact interval is wider.

    Wider in total width, not necessarily outside Wald at both ends. An
    exact interval is asymmetric about the estimate, and at some counts its
    upper limit sits just inside the Wald one while the lower limit extends
    well below. Asserting both ends would be asserting something untrue.
    """
    events, total, baseline_events, baseline_total = 9, 15000, 300, 520000
    lower, upper = exact_rate_ratio_interval(
        events, total, baseline_events, baseline_total)
    rri = (events / total) / (baseline_events / baseline_total)
    se = math.sqrt(1 / events + 1 / baseline_events
                   - 1 / total - 1 / baseline_total)
    wald_lower = math.exp(math.log(rri) - 1.96 * se)
    wald_upper = math.exp(math.log(rri) + 1.96 * se)
    assert (upper - lower) > (wald_upper - wald_lower)
    # The lower limit is where the difference bites, and where a claim of
    # significance is won or lost.
    assert lower < wald_lower


def test_the_interval_converges_on_wald_at_large_counts():
    """And the reason it is safe to adopt everywhere: at the thousands-scale
    counts in the stop and search series the two agree closely."""
    events, total, baseline_events, baseline_total = 10326, 430000, 9800, 980000
    lower, upper = exact_rate_ratio_interval(
        events, total, baseline_events, baseline_total)
    rri = (events / total) / (baseline_events / baseline_total)
    se = math.sqrt(1 / events + 1 / baseline_events
                   - 1 / total - 1 / baseline_total)
    assert lower == pytest.approx(math.exp(math.log(rri) - 1.96 * se), rel=0.01)
    assert upper == pytest.approx(math.exp(math.log(rri) + 1.96 * se), rel=0.01)


def test_a_zero_event_count_gives_a_lower_limit_of_zero():
    """Wald divides by zero here. No current series has a zero cell, but
    finer pooling could produce one."""
    lower, upper = exact_rate_ratio_interval(0, 5000, 200, 400000)
    assert lower == 0.0
    assert upper > 0.0


def test_narrower_intervals_as_counts_grow():
    """More evidence, tighter interval, holding the ratio fixed."""
    widths = []
    for scale in (1, 10, 100):
        lower, upper = exact_rate_ratio_interval(
            10 * scale, 20000 * scale, 400 * scale, 600000 * scale)
        widths.append(upper - lower)
    assert widths[0] > widths[1] > widths[2]


def test_interval_rejects_impossible_input():
    with pytest.raises(ValueError):
        exact_rate_ratio_interval(5, 0, 10, 100)
    with pytest.raises(ValueError):
        exact_rate_ratio_interval(0, 100, 0, 100)
