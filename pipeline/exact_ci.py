"""Exact confidence intervals for counts and rate ratios.

PRISM-R's Relative Rate Indices compare small counts: the pooled child
custodial sentencing series runs to single figures for the Other ethnic
group. A Wald interval on the log rate ratio relies on a normal
approximation that is poor at those counts, and it was overstating
precision: two intervals excluded 1 under Wald that do not under an exact
method, both in the small-count custodial sentencing series.

The exact interval for a single Poisson count is Garwood's (1936). For a
ratio of two Poisson rates the exact analogue conditions on the total of
the two counts, which makes the group count binomial, so a Clopper-Pearson
interval on that proportion transforms into an interval for the rate ratio:

    p        = a / (a + b)
    RRI      = (p / (1 - p)) x (B / A)

with a and A the event count and person-time or population for the group,
and b and B those for the baseline. Clopper-Pearson limits on p carry
through the transformation because it is monotonic in p.

Exact intervals are conservative: coverage is at least the nominal 95%
rather than approximately it, so they are wider than Wald by construction.
That is the intended trade. At the thousands-scale counts in the stop and
search series the two agree to three decimal places; at counts below about
thirty the exact interval is materially wider, which is the regime the
approximation cannot be trusted in.

No SciPy. The regularised incomplete beta is evaluated by the standard
continued fraction and inverted by bisection, which is deterministic and
so keeps the build byte-reproducible. tests/test_exact_ci.py checks the
implementation against published Clopper-Pearson limits.

References:
  Clopper, C. J. and Pearson, E. S. (1934), "The use of confidence or
    fiducial limits illustrated in the case of the binomial", Biometrika
    26, 404-413.
  Garwood, F. (1936), "Fiducial limits for the Poisson distribution",
    Biometrika 28, 437-442.
  Breslow, N. E. and Day, N. E. (1987), Statistical Methods in Cancer
    Research, Volume II: The Design and Analysis of Cohort Studies, IARC,
    on exact inference for the ratio of two rates by conditioning.
"""

from __future__ import annotations

import math

# Continued-fraction settings. The iteration cap is never reached for the
# arguments this pipeline uses; it bounds the work if it ever were.
_MAX_ITERATIONS = 300
_EPSILON = 3e-16
_TINY = 1e-300

# Bisection steps for the inverse. Each step halves the bracket, so 200 is
# far past double precision and costs nothing at this scale; the point is to
# be obviously sufficient rather than tuned.
_BISECTION_STEPS = 200


def _beta_continued_fraction(a: float, b: float, x: float) -> float:
    """The continued fraction for the incomplete beta, by Lentz's method."""
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < _TINY:
        d = _TINY
    d = 1.0 / d
    result = d
    for m in range(1, _MAX_ITERATIONS + 1):
        m2 = 2 * m
        numerator = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + numerator * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + numerator / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        result *= d * c
        numerator = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + numerator * d
        if abs(d) < _TINY:
            d = _TINY
        c = 1.0 + numerator / c
        if abs(c) < _TINY:
            c = _TINY
        d = 1.0 / d
        step = d * c
        result *= step
        if abs(step - 1.0) < _EPSILON:
            break
    return result


def regularised_incomplete_beta(a: float, b: float, x: float) -> float:
    """I_x(a, b), the regularised incomplete beta function."""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    front = math.exp(
        math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
        + a * math.log(x) + b * math.log1p(-x)
    )
    # The fraction converges quickly only on one side of this point; the
    # symmetry I_x(a,b) = 1 - I_(1-x)(b,a) covers the other.
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _beta_continued_fraction(a, b, x) / a
    return 1.0 - front * _beta_continued_fraction(b, a, 1.0 - x) / b


def beta_quantile(p: float, a: float, b: float) -> float:
    """The inverse of the regularised incomplete beta, by bisection."""
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    low, high = 0.0, 1.0
    for _ in range(_BISECTION_STEPS):
        middle = (low + high) / 2.0
        if regularised_incomplete_beta(a, b, middle) < p:
            low = middle
        else:
            high = middle
    return (low + high) / 2.0


def clopper_pearson(successes: int, trials: int,
                    alpha: float = 0.05) -> tuple[float, float]:
    """The exact binomial confidence interval for a proportion.

    Zero successes give a lower limit of exactly 0, and all successes an
    upper limit of exactly 1, rather than the undefined values a normal
    approximation produces there.
    """
    if trials <= 0:
        raise ValueError("an exact interval needs at least one trial")
    if not 0 <= successes <= trials:
        raise ValueError("successes must lie between 0 and trials")
    lower = (0.0 if successes == 0
             else beta_quantile(alpha / 2, successes, trials - successes + 1))
    upper = (1.0 if successes == trials
             else beta_quantile(1 - alpha / 2, successes + 1, trials - successes))
    return lower, upper


def exact_rate_ratio_interval(events: int, total: float,
                              baseline_events: int, baseline_total: float,
                              alpha: float = 0.05) -> tuple[float, float]:
    """The exact conditional interval for (events/total) / (baseline rate).

    Conditioning on the two counts' total makes the group count binomial,
    so the Clopper-Pearson limits on that proportion transform directly
    into limits on the rate ratio. An upper limit of infinity arises only
    when the baseline count is zero, which cannot occur in the series this
    pipeline computes but is returned honestly rather than clipped.
    """
    if total <= 0 or baseline_total <= 0:
        raise ValueError("an interval needs positive denominators")
    if events < 0 or baseline_events < 0:
        raise ValueError("event counts cannot be negative")
    combined = events + baseline_events
    if combined == 0:
        raise ValueError("an interval needs at least one event")
    lower_p, upper_p = clopper_pearson(events, combined, alpha)
    scale = baseline_total / total
    lower = 0.0 if lower_p <= 0.0 else (lower_p / (1.0 - lower_p)) * scale
    upper = math.inf if upper_p >= 1.0 else (upper_p / (1.0 - upper_p)) * scale
    return lower, upper
