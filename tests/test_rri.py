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
def test_build_rri_produces_six_series():
    rows = compute_rri.build_rri()
    # 5 ethnicities x: stop and search, arrest, adult sentencing, adult
    # remand, child remand, child sentencing (3 single years + 1 pooled)
    # = 9 blocks = 45 rows.
    assert len(rows) == 45
    series = {(r["decision_point"], r["provenance"]) for r in rows}
    assert series == {
        ("stop_search", "prism_r_derived"),
        ("arrest", "prism_r_derived"),
        ("custodial_sentence", "moj_published"),
        ("custodial_sentence", "prism_r_derived"),
        ("remand", "moj_published"),
        ("remand", "prism_r_derived"),
    }


def test_cascade_upstream_blocks_are_home_office_derived():
    """stop_search and arrest rows are prism_r_derived from Home Office data,
    carry Wald confidence intervals and use the Census child population as the
    rate denominator (total far larger than the event count)."""
    rows = [
        r for r in compute_rri.build_rri()
        if r["decision_point"] in ("stop_search", "arrest")
    ]
    assert len(rows) == 10
    for row in rows:
        assert row["provenance"] == "prism_r_derived"
        assert row["geo_id"] == "ew"
        assert row["period_basis"] == "year_ending_march_2025"
        assert row["source_publication"].startswith("Police powers and procedures")
        assert row["events"] < row["total"]  # events over a population base
        if row["ethnicity"] != "White":
            assert row["ci_method"] == "wald_log_ratio"
            assert row["ci_lower"] <= row["rri"] <= row["ci_upper"]


# Pooled fixture: three years of counts, summed, then RRI computed.
# Expected values computed independently of compute_rri.py, Z = 1.96.
POOLED_FIXTURE_YEARS = [(10, 200, 40, 1000), (15, 250, 50, 1100), (20, 300, 60, 1200)]
POOLED_FIXTURE_EXPECTED = (1.3200000000, 0.1650833888, 0.9551071886, 1.8242978597)


def test_pooled_rri_fixture():
    events = sum(y[0] for y in POOLED_FIXTURE_YEARS)
    total = sum(y[1] for y in POOLED_FIXTURE_YEARS)
    base_events = sum(y[2] for y in POOLED_FIXTURE_YEARS)
    base_total = sum(y[3] for y in POOLED_FIXTURE_YEARS)
    result = relative_rate_index(events, total, base_events, base_total)
    exp_rri, exp_se, exp_lo, exp_hi = POOLED_FIXTURE_EXPECTED
    assert result.rri == pytest.approx(exp_rri, abs=1e-4)
    assert result.se_ln == pytest.approx(exp_se, abs=1e-4)
    assert result.ci_lower == pytest.approx(exp_lo, abs=1e-4)
    assert result.ci_upper == pytest.approx(exp_hi, abs=1e-4)


def test_pool_counts_sums_across_years():
    by_year = {
        year: {e: {"events": n, "total": n * 10} for e in compute_rri.ALL_ETHNICITIES}
        for year, n in [(2023, 1), (2024, 2), (2025, 3)]
    }
    pooled = compute_rri._pool_counts(by_year)
    assert pooled["Black"] == {"events": 6, "total": 60}


def test_child_sentencing_has_pooled_and_single_year_rows():
    rows = [
        r for r in compute_rri.build_rri()
        if r["decision_point"] == "custodial_sentence" and r["provenance"] == "prism_r_derived"
    ]
    pooled = [r for r in rows if r["pooled"]]
    single = [r for r in rows if not r["pooled"]]
    assert len(pooled) == 5  # one pooled block of 5 ethnicities
    assert {r["period_basis"] for r in pooled} == {"pooled_3y_ending_march_2025"}
    assert {r["period_basis"] for r in single} == {
        "year_ending_march_2023",
        "year_ending_march_2024",
        "year_ending_march_2025",
    }
    # The pooled row reproduces the RRI of the summed counts.
    pooled_black = next(r for r in pooled if r["ethnicity"] == "Black")
    pooled_white = next(r for r in pooled if r["ethnicity"] == "White")
    recomputed = relative_rate_index(
        pooled_black["events"], pooled_black["total"],
        pooled_white["events"], pooled_white["total"],
    )
    assert pooled_black["rri"] == pytest.approx(recomputed.rri, abs=1e-9)


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
    """The pooled child custodial sentencing RRI should sit in a plausible
    range relative to the adult MoJ values: same direction, within a factor
    of three. A breach emits a warning for review and does not fail the suite.
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
        if r["decision_point"] == "custodial_sentence"
        and r["provenance"] == "prism_r_derived"
        and r["pooled"]
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
            "pooled child custodial sentencing RRI sanity check, review advised: "
            + "; ".join(issues),
            stacklevel=2,
        )
