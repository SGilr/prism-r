"""Serialisation precision for values that depend on the maths library.

IEEE 754 requires addition, subtraction, multiplication, division and square
root to be correctly rounded, so a value built from those alone is the same
double on every conforming platform. It makes no such requirement of exp,
log, pow, lgamma or the trigonometric functions: two platforms' maths
libraries may return results a unit or two apart in the last place.

PRISM-R serialises very few values computed that way. The exact confidence
interval in pipeline/exact_ci.py evaluates exp, lgamma, log and log1p inside
a bisection. The bisection is deterministic for a given maths library, so a
machine reproduces its own build exactly, but on a different library the
bracket can settle a few units away. The verification run of 14 September
2026 found interval bounds built on Linux differing from those built on
macOS in the last few significant digits.

Rounding those values to SERIALISED_DECIMALS places when they are written
absorbs that drift, which is many orders of magnitude smaller than the sixth
decimal place, while six places remains far finer than any precision the
interval supports. The one case rounding cannot absorb is a value lying
within the drift of a rounding half-way point. tests/test_serialisation.py
checks that every published bound keeps a wide margin from one, so a rebuild
that lands close fails a test that says why, rather than the verification
job failing without explanation.

Only values derived from drift-prone functions are rounded. Values built
from exact arithmetic already reproduce bit for bit, and rounding them would
change published figures for no gain: RRI point estimates are a ratio of
rates, and some rates are carried verbatim from their publisher.
"""

from __future__ import annotations

SERIALISED_DECIMALS = 6

# Functions IEEE 754 does not require to be correctly rounded, and which
# therefore may differ between maths libraries. tests/test_serialisation.py
# fails if a pipeline module that writes output calls one of these without
# rounding what it writes. sqrt is deliberately absent: it is correctly
# rounded, like division.
DRIFT_PRONE_FUNCTIONS: tuple[str, ...] = (
    "exp", "expm1", "log", "log1p", "log2", "log10", "pow", "lgamma",
    "gamma", "erf", "erfc", "sin", "cos", "tan", "asin", "acos", "atan",
    "atan2", "sinh", "cosh", "tanh", "asinh", "acosh", "atanh", "hypot",
    "cbrt",
)


def stable_float(value: float | None) -> float | None:
    """A drift-prone value, rounded for serialisation.

    None passes through, since a suppressed or baseline cell carries no
    bound. A value already at six or fewer decimal places is returned
    unchanged, so applying this twice is harmless.
    """
    if value is None:
        return None
    return round(float(value), SERIALISED_DECIMALS)
