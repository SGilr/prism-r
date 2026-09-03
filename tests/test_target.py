"""Tests for the target tracker computation in pipeline/compute_target.py.

The fixture runs the computation once and restores the output afterwards,
so the working tree keeps the committed build output.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import compute_target  # noqa: E402


@pytest.fixture(scope="module")
def payload():
    original = (compute_target.OUTPUT.read_bytes()
                if compute_target.OUTPUT.exists() else None)
    assert compute_target.main() == 0
    yield json.loads(compute_target.OUTPUT.read_text(encoding="utf-8"))
    if original is not None:
        compute_target.OUTPUT.write_bytes(original)


def test_baseline_is_the_mean_of_the_twelve_months_to_march_2025(payload):
    stock = payload["meta"]["stock"]
    assert stock["baseline"] == 215.75
    assert stock["target"] == pytest.approx(215.75 * 0.75, abs=0.01)


def test_rolling_average_matches_a_hand_computed_window(payload):
    rows = {r["month"]: r for r in payload["records"]
            if r["block"] == "stock_monthly"}
    # The first full window: 12 months April 2015 to March 2016.
    months = sorted(rows)[:12]
    expected = round(sum(rows[m]["remand"] for m in months) / 12, 2)
    assert rows["2016-03"]["rolling_avg_12m"] == expected
    assert rows["2016-02"]["rolling_avg_12m"] is None  # window not yet full


def test_pre_commitment_trend_is_negative_and_matches_the_series(payload):
    stock = payload["meta"]["stock"]
    rows = {r["month"]: r for r in payload["records"]
            if r["block"] == "stock_monthly"}
    expected = round(
        (rows["2026-05"]["rolling_avg_12m"] - rows["2025-03"]["rolling_avg_12m"])
        / rows["2025-03"]["rolling_avg_12m"] * 100, 2)
    assert stock["pre_commitment_trend"] == expected
    assert stock["pre_commitment_trend"] < 0


def test_markers_carry_the_verified_february_2026_values(payload):
    feb = next(m for m in payload["meta"]["markers"] if m["date"] == "2026-02")
    assert feb["estate_total"] == 412
    assert feb["remand"] == 149
    assert feb["remand_share"] == 0.362
    assert any(m["date"] == "2026-05-18" for m in payload["meta"]["markers"])


def test_flow_block_baseline_and_target(payload):
    flow = payload["meta"]["flow"]
    assert flow["baseline"] == 988
    assert flow["target"] == 741
    rows = [r for r in payload["records"] if r["block"] == "flow_annual"]
    baseline_row = next(r for r in rows if r["year_ending_march"] == 2025)
    assert baseline_row["yda_remand_episodes"] == 988


def test_duration_block_is_binary_episodes_ending_with_2026_provisional(payload):
    rows = [r for r in payload["records"] if r["block"] == "duration_median_nights"]
    assert {r["ethnicity_group"] for r in rows} == {"ethnic_minority", "white"}
    for r in rows:
        assert r["ethnicity_basis"] == "binary"
        assert r["measure"] == "episodes_ending"
        assert r["provisional"] == (r["year_ending_march"] == 2026)
    ye25 = {r["ethnicity_group"]: r["median_nights"] for r in rows
            if r["year_ending_march"] == 2025}
    assert ye25 == {"ethnic_minority": 74.0, "white": 40.5}


def test_ethnicity_block_is_whole_custody_shares(payload):
    rows = [r for r in payload["records"]
            if r["block"] == "whole_custody_ethnicity_monthly"]
    assert rows and all(r["scope"] == "whole_custody" for r in rows)
    months = {r["month"] for r in rows}
    for month in list(sorted(months))[-3:]:
        shares = [r["share"] for r in rows if r["month"] == month]
        assert sum(s for s in shares if s is not None) == pytest.approx(1.0, abs=0.01)
