"""Tests for the YJB ingest pipeline.

These tests run the ingest end to end, then check the structure of the two
processed datasets and the reproduction of the published national totals.
"""

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import ingest_yjb  # noqa: E402

GEO_PATH = REPO_ROOT / "data" / "processed" / "geographies.json"
REMAND_PATH = REPO_ROOT / "data" / "processed" / "remand_outcomes.json"

GEO_FIELDS = {
    "geo_id",
    "geo_name",
    "geo_type",
    "parent_region",
    "parent_force",
    "ons_code",
    "centroid_lat",
    "centroid_lon",
    "boundary_ref",
}
REMAND_FIELDS = {
    "geo_id",
    "year",
    "remand_type",
    "breakdown",
    "ethnicity",
    "age_band",
    "sex",
    "offence_band",
    "count",
    "suppressed",
}


@pytest.fixture(scope="module")
def result():
    return ingest_yjb.ingest()


@pytest.fixture(scope="module")
def geographies(result):
    return json.loads(GEO_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def remand(result):
    return json.loads(REMAND_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Validation against published national totals
# --------------------------------------------------------------------------
def test_all_validation_checks_pass(result):
    assert result["failed"] == []
    assert len(result["checks"]) >= 40


def test_grand_total_check_present_and_passed(result):
    named = {name: passed for name, passed, _ in result["checks"]}
    assert named["6.1 total remand episodes"] is True
    assert named["6.2 2025 total"] is True


def test_remand_grand_total_2025(remand):
    total = sum(
        r["count"]
        for r in remand["records"]
        if r["breakdown"] == "total" and r["year"] == 2025
    )
    assert total == 11092


def test_remand_trend_2021_total(remand):
    total = sum(
        r["count"]
        for r in remand["records"]
        if r["breakdown"] == "total" and r["year"] == 2021
    )
    assert total == 12710


def test_remand_type_totals_2025(remand):
    by_type = {
        r["remand_type"]: r["count"]
        for r in remand["records"]
        if r["breakdown"] == "total" and r["year"] == 2025
    }
    assert by_type == {"bail": 8691, "community_remand": 991, "rlaa": 422, "ydp": 988}


def test_marginal_breakdowns_reproduce_type_total(remand):
    records = remand["records"]
    for remand_type in ingest_yjb.REMAND_TYPES:
        total = next(
            r["count"]
            for r in records
            if r["breakdown"] == "total"
            and r["year"] == 2025
            and r["remand_type"] == remand_type
        )
        for breakdown in ("ethnicity", "sex", "age"):
            marginal = sum(
                r["count"]
                for r in records
                if r["year"] == 2025
                and r["remand_type"] == remand_type
                and r["breakdown"] == breakdown
            )
            assert marginal == total, (remand_type, breakdown)


# --------------------------------------------------------------------------
# Remand outcomes structure
# --------------------------------------------------------------------------
def test_remand_record_count(remand):
    assert len(remand["records"]) == 64


def test_remand_record_schema(remand):
    for record in remand["records"]:
        assert set(record) == REMAND_FIELDS
        assert record["geo_id"] == "ew"
        assert record["remand_type"] in ingest_yjb.REMAND_TYPES
        assert record["breakdown"] in {"total", "ethnicity", "sex", "age"}
        assert record["offence_band"] is None
        assert record["suppressed"] is False
        assert isinstance(record["count"], int)


# --------------------------------------------------------------------------
# Geographies structure
# --------------------------------------------------------------------------
def test_geography_counts(geographies):
    counts = geographies["meta"]["counts"]
    assert counts == {"nation": 1, "region": 10, "police_force": 42, "yot": 156}
    assert len(geographies["records"]) == 209


def test_geography_ids_unique(geographies):
    ids = [r["geo_id"] for r in geographies["records"]]
    assert len(ids) == len(set(ids))


def test_geography_record_schema(geographies):
    for record in geographies["records"]:
        assert set(record) == GEO_FIELDS
        assert record["geo_type"] in {"nation", "region", "police_force", "yot"}


def test_yot_parents_resolve(geographies):
    records = geographies["records"]
    region_ids = {r["geo_id"] for r in records if r["geo_type"] == "region"}
    force_ids = {r["geo_id"] for r in records if r["geo_type"] == "police_force"}
    for record in records:
        if record["geo_type"] == "yot":
            assert record["parent_region"] in region_ids
            assert record["parent_force"] is None or record["parent_force"] in force_ids
        else:
            assert record["parent_region"] is None
            assert record["parent_force"] is None


# --------------------------------------------------------------------------
# Idempotency
# --------------------------------------------------------------------------
def test_ingest_is_idempotent(result):
    before_geo = GEO_PATH.read_bytes()
    before_remand = REMAND_PATH.read_bytes()
    ingest_yjb.ingest()
    assert GEO_PATH.read_bytes() == before_geo
    assert REMAND_PATH.read_bytes() == before_remand
