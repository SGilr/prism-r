"""Tests for the RRI calculator in pipeline/compute_rri.py.

The Wald log-ratio method is validated with four synthetic fixtures whose
expected outputs were computed independently. The function must reproduce
each to at least four decimal places.

A separate sanity check compares the child custodial sentencing RRIs with
the adult MoJ values. It is a sanity check, not a validation: a breach
emits a warning for review and does not fail the suite.
"""

import sys
import warnings
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import compute_rri  # noqa: E402
from pipeline.compute_rri import relative_rate_index  # noqa: E402

# Synthetic fixtures: (name, events, total, baseline_events, baseline_total,
# expected rri, se_ln, ci_lower, ci_upper). Expected values were computed
# independently of compute_rri.py, using Z = 1.96.
FIXTURES = [
    ("rri_2x", 50, 500, 40, 800, 2.0000000000, 0.2043281674, 1.3399924404, 2.9850914673),
    ("parity", 30, 300, 30, 300, 1.0000000000, 0.2449489743, 0.6187215230, 1.6162360009),
    ("below_one", 20, 400, 60, 600, 0.5000000000, 0.2500000000, 0.3063131971, 0.8161581100),
    ("rri_1p5", 12, 240, 18, 540, 1.5000000000, 0.3645138823, 0.7341939111, 3.0645854806),
]


@pytest.mark.parametrize(
    "name,events,total,base_events,base_total,exp_rri,exp_se,exp_lo,exp_hi", FIXTURES
)
def test_rri_fixture(name, events, total, base_events, base_total, exp_rri, exp_se, exp_lo, exp_hi):
    result = relative_rate_index(events, total, base_events, base_total)
    assert result.rri == pytest.approx(exp_rri, abs=1e-4), name
    assert result.se_ln == pytest.approx(exp_se, abs=1e-4), name
    assert result.ci_lower == pytest.approx(exp_lo, abs=1e-4), name
    assert result.ci_upper == pytest.approx(exp_hi, abs=1e-4), name


def test_rri_interval_brackets_the_point_estimate():
    for name, events, total, be, bt, *_ in FIXTURES:
        result = relative_rate_index(events, total, be, bt)
        assert result.ci_lower <= result.rri <= result.ci_upper, name


def test_rri_rejects_non_positive_counts():
    with pytest.raises(ValueError):
        relative_rate_index(0, 100, 10, 100)
    with pytest.raises(ValueError):
        relative_rate_index(10, 100, 10, 0)


def test_rri_rejects_events_above_total():
    with pytest.raises(ValueError):
        relative_rate_index(120, 100, 10, 100)


# --------------------------------------------------------------------------
# Output structure
# --------------------------------------------------------------------------
def test_build_rri_produces_four_series():
    rows = compute_rri.build_rri()
    assert len(rows) == 20  # 4 series x 5 ethnicities (White baseline included)
    series = {(r["decision_point"], r["provenance"]) for r in rows}
    assert series == {
        ("custodial_sentence", "moj_published"),
        ("custodial_sentence", "prism_r_derived"),
        ("remand", "moj_published"),
        ("remand", "prism_r_derived"),
    }


def test_adult_rows_have_no_confidence_interval():
    for row in compute_rri.build_rri():
        if row["provenance"] == "moj_published":
            assert row["ci_lower"] is None and row["ci_upper"] is None
            assert row["ci_method"] == "not_published"


def test_child_non_baseline_rows_have_confidence_intervals():
    for row in compute_rri.build_rri():
        if row["provenance"] == "prism_r_derived" and row["ethnicity"] != "White":
            assert row["ci_lower"] is not None and row["ci_upper"] is not None
            assert row["ci_method"] == "wald_log_ratio"
            assert row["ci_lower"] <= row["rri"] <= row["ci_upper"]


def test_white_baseline_rri_is_one():
    for row in compute_rri.build_rri():
        if row["ethnicity"] == "White":
            assert row["rri"] == 1.0


def test_adult_rri_matches_moj_published_values():
    # Adopted verbatim from MoJ Table 9.01 and Table 5.17a, 2024.
    rows = {
        (r["decision_point"], r["ethnicity"]): r["rri"]
        for r in compute_rri.build_rri()
        if r["provenance"] == "moj_published"
    }
    assert rows[("custodial_sentence", "Asian")] == pytest.approx(1.0946, abs=1e-4)
    assert rows[("custodial_sentence", "Other")] == pytest.approx(1.1697, abs=1e-4)
    assert rows[("remand", "Black")] == pytest.approx(1.2871, abs=1e-4)


# --------------------------------------------------------------------------
# Sanity check (not a validation; warns rather than fails)
# --------------------------------------------------------------------------
def test_child_sentencing_rri_sanity_check():
    """Child custodial sentencing RRIs should sit in a plausible range
    relative to the adult MoJ values: same direction, within a factor of
    three. A breach emits a warning for review and does not fail the suite.
    """
    rows = compute_rri.build_rri()
    adult = {
        r["ethnicity"]: r["rri"]
        for r in rows
        if r["decision_point"] == "custodial_sentence" and r["provenance"] == "moj_published"
    }
    child = {
        r["ethnicity"]: r["rri"]
        for r in rows
        if r["decision_point"] == "custodial_sentence" and r["provenance"] == "prism_r_derived"
    }
    issues = []
    for group in compute_rri.GROUPS:
        adult_rri, child_rri = adult[group], child[group]
        if (adult_rri > 1) != (child_rri > 1):
            issues.append(
                f"{group}: adult {adult_rri:.2f} and child {child_rri:.2f} "
                f"point in opposite directions"
            )
        ratio = child_rri / adult_rri
        if not (1 / 3 <= ratio <= 3):
            issues.append(
                f"{group}: child to adult ratio {ratio:.2f} is outside the "
                f"factor-of-three range"
            )
    if issues:
        warnings.warn(
            "child custodial sentencing RRI sanity check, review advised: "
            + "; ".join(issues),
            stacklevel=2,
        )
