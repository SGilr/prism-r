"""Tests for the Youth Custody Service ingest in pipeline/ingest_ycs.py.

The module-scoped fixture runs the ingest once and restores the processed
files afterwards, so a test run never strips the build-applied disclosure
suppression from the working tree (the same pattern as test_pipeline.py).

Anchor values are read from the published June 2026 edition and its
cross-sources: YJS 2024-25 Table 7.2 for March 2025, and the 412 total
cited to the Justice Committee on 18 May 2026 for February 2026.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import ingest_ycs  # noqa: E402

OUTPUTS = (ingest_ycs.MONTHLY_OUT, ingest_ycs.EPISODES_OUT, ingest_ycs.LENGTH_OUT)


@pytest.fixture(scope="module")
def payloads():
    """Run the ingest once, yield the three payloads, restore files after."""
    originals = {p: p.read_bytes() for p in OUTPUTS if p.exists()}
    assert ingest_ycs.main() == 0
    loaded = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in OUTPUTS}
    yield loaded
    for path, data in originals.items():
        path.write_bytes(data)


@pytest.fixture(scope="module")
def monthly(payloads):
    return payloads["custody_monthly.json"]["records"]


def _one(records, **match):
    hits = [r for r in records if all(r.get(k) == v for k, v in match.items())]
    assert len(hits) == 1, f"expected one record for {match}, got {len(hits)}"
    return hits[0]


# --------------------------------------------------------------------------
# Anchors
# --------------------------------------------------------------------------
def test_march_2025_under_18_total_matches_yjs(monthly):
    row = _one(monthly, month="2025-03", measure="total", category="under_18")
    assert row["count"] == 402  # YJS 2024-25 Table 7.2, March 2025


def test_february_2026_all_ages_total_matches_hansard(monthly):
    row = _one(monthly, month="2026-02", measure="total", category="all_ages")
    assert row["count"] == 412  # cited to the Justice Committee, 18 May 2026


def test_march_2025_remand_stock(monthly):
    row = _one(monthly, month="2025-03", measure="legal_basis", category="remand")
    assert row["count"] == 199


# --------------------------------------------------------------------------
# Structure and flags
# --------------------------------------------------------------------------
def test_legal_basis_sums_to_all_ages_total_every_month(monthly):
    months = {r["month"] for r in monthly if r["measure"] == "legal_basis"}
    for month in months:
        basis = [r["count"] for r in monthly
                 if r["month"] == month and r["measure"] == "legal_basis"]
        total = _one(monthly, month=month, measure="total", category="all_ages")
        assert sum(v for v in basis if v is not None) == total["count"], month


def test_only_the_latest_month_is_provisional(monthly, payloads):
    latest = payloads["custody_monthly.json"]["meta"]["latest_month"]
    assert latest == max(r["month"] for r in monthly)
    for r in monthly:
        assert r["provisional"] == (r["month"] == latest)


def test_no_empty_future_rows(monthly):
    latest = max(r["month"] for r in monthly)
    latest_counts = [r["count"] for r in monthly if r["month"] == latest]
    assert any(v is not None for v in latest_counts)


def test_every_record_carries_age_basis_and_source_file(monthly):
    for r in monthly:
        assert r["source_file"] == ingest_ycs.SOURCE_FILE
        assert r["age_basis"] in ("under_18", "all_ages_youth_estate")
    remand = _one(monthly, month="2025-03", measure="legal_basis", category="remand")
    assert remand["age_basis"] == "all_ages_youth_estate"


def test_ethnicity_is_whole_custody_scope(monthly):
    rows = [r for r in monthly if r["measure"] == "ethnicity"]
    assert rows and all(r["scope"] == "whole_custody" for r in rows)


def test_monthly_series_bounds(monthly):
    months = sorted({r["month"] for r in monthly})
    assert months[0] == "2000-04"
    basis_months = sorted({r["month"] for r in monthly if r["measure"] == "legal_basis"})
    assert basis_months[0] == "2015-04"


# --------------------------------------------------------------------------
# Episodes ending and episode length
# --------------------------------------------------------------------------
def test_episodes_ending_binary_ethnicity_and_anchor(payloads):
    records = payloads["custody_episodes_ending.json"]["records"]
    assert all(r["ethnicity_basis"] == "binary" for r in records)
    assert {r["ethnicity_group"] for r in records} == {"ethnic_minority", "white"}
    row = _one(records, year_ending_march=2025, ethnicity_group="ethnic_minority",
               legal_basis="remand")
    assert row["count"] == 389  # table 2.2, year ending March 2025


def test_episode_length_bands_and_medians(payloads):
    records = payloads["custody_episode_length.json"]["records"]
    counts = [r for r in records if r["indicator"] == "episode_count"]
    medians = [r for r in records if r["indicator"] == "median_nights"]
    assert all(r["nights_band"] is not None for r in counts)
    assert all(r["nights_band"] is None for r in medians)
    # Bands sum to the published total: ethnic minority remand, YE March 2025.
    bands = [r["value"] for r in counts
             if r["year_ending_march"] == 2025
             and r["ethnicity_group"] == "ethnic_minority"
             and r["legal_basis"] == "remand"]
    assert sum(bands) == 389
