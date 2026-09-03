"""Tests for the geographic explorer data layer.

The explorer is the first place PRISM-R serves indicators that live at
different geographies side by side, so these tests protect the two rules
that keeps that honest: an indicator appears only at the level its publisher
releases it, and a suppressed cell never carries a value or anything a value
can be recovered from.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

EXPLORER = REPO_ROOT / "data" / "processed" / "explorer"
LEVELS = ("rgn", "utla", "lad", "pfa")


@pytest.fixture(scope="module")
def index():
    return json.loads((EXPLORER / "index.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def records():
    return {level: json.loads((EXPLORER / f"{level}.json").read_text("utf-8"))["records"]
            for level in LEVELS}


def test_every_geography_level_is_complete(index):
    counts = {}
    for geography in index["geographies"]:
        counts[geography["level"]] = counts.get(geography["level"], 0) + 1
    assert counts == {"lad": 318, "utla": 175, "pfa": 42, "rgn": 10}


def test_no_suppressed_cell_carries_a_recoverable_value(records):
    """A suppressed count must not survive as a value, a rate or a numerator:
    a rate against a published denominator gives the count straight back."""
    for level, rows in records.items():
        for row in rows:
            suppressed = (row.get("suppressed")
                          or row.get("disclosure_status") == "source_suppressed")
            if not suppressed:
                continue
            for field in ("value", "numerator", "source_rate"):
                assert row.get(field) is None, (level, row["geo_id"],
                                                row["indicator"], field)


def test_indicators_appear_only_at_their_published_level(index, records):
    spec = index["meta"]["indicators"]
    for level, rows in records.items():
        for row in rows:
            declared = spec[row["indicator"]]["level"]
            # Regions carry the DfE's own published regional rows.
            assert level in (declared, "rgn"), (level, row["indicator"])


def test_exclusion_rates_recompute_from_their_counts(records):
    """Rates are recomputed from counts at the level shown, never averaged
    from a lower level's rates, so the counts must reproduce the rate."""
    checked = 0
    for row in records["utla"]:
        if row["indicator"] not in ("suspension_rate", "permanent_exclusion_rate"):
            continue
        if row.get("numerator") is None or not row.get("denominator"):
            continue
        assert row["value"] == pytest.approx(
            row["numerator"] / row["denominator"] * 100, abs=0.001)
        checked += 1
    assert checked > 3000


def test_non_aggregatable_indicators_are_flagged(index):
    """imd_score and the Welsh exclusion rates have no published counts, so
    they can only be shown at the level their publisher releases."""
    spec = index["meta"]["indicators"]
    assert spec["imd_score"]["aggregatable"] is False
    assert spec["suspension_rate"]["aggregatable"] is True


def test_imd_comparator_never_crosses_the_border(index, records):
    """IDACI and WIMD are parallel scales: an authority is compared with its
    own nation's average, never with the other's."""
    national = index["national"]
    assert "imd_score|2025|overall|England" in national
    assert "imd_score|2019|overall|Wales" in national
    england = national["imd_score|2025|overall|England"]["value"]
    wales = national["imd_score|2019|overall|Wales"]["value"]
    for row in records["lad"]:
        if row["indicator"] != "imd_score":
            continue
        expected = england if row["jurisdiction"] == "England" else wales
        assert row["national_value"] == expected


def test_every_record_carries_a_national_comparator(records):
    for level, rows in records.items():
        for row in rows:
            assert "national_value" in row, (level, row["indicator"])


def test_source_keys_resolve_to_full_provenance(index, records):
    catalogue = index["sources"]
    for rows in records.values():
        for row in rows:
            entry = catalogue[row["source_key"]]
            assert entry["source"] and entry["reference_period"]


def test_upper_tier_geographies_name_their_youth_justice_service(index):
    """The panel must be able to tell a user which service covers the
    authority they clicked."""
    upper = [g for g in index["geographies"] if g["level"] == "utla"]
    assert all(g.get("parent_yot_name") for g in upper)
