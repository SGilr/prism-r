"""Tests for disclosure suppression wired into the build orchestrator.

The suppression rules themselves are tested in test_suppression.py. These
tests cover the wiring in pipeline/build.py: that suppression maps correctly
onto a records list, that an output with no firing rule is left untouched,
and that the audit trail is produced.
"""

import copy
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import build  # noqa: E402

CONTEXT_PLAN = next(
    p for p in build.SUPPRESSION_PLANS if p.filename == "context_indicators.json"
)


def _lac_records(values: list[int | None]) -> list[dict]:
    """Five by-ethnicity lac_count records for one authority, given counts."""
    groups = ["White", "Black", "Asian", "Mixed", "Other"]
    records = []
    for ethnicity, value in zip(groups, values):
        records.append({
            "geo_id": "E06000001", "year": 2025, "indicator": "lac_count",
            "breakdown": "by_ethnicity", "ethnicity": ethnicity, "value": value,
            "disclosure_status": "source_suppressed" if value is None else "released",
        })
    return records


# --------------------------------------------------------------------------
# Identical where no rule fires
# --------------------------------------------------------------------------
def test_no_rule_fires_leaves_records_untouched():
    records = _lac_records([120, 95, 60, 44, 31])
    original = copy.deepcopy(records)
    audit = build.suppress_records(records, CONTEXT_PLAN)
    assert records == original
    assert all(entry["resulting_state"] != "suppressed" for entry in audit)


def test_out_of_scope_indicator_is_never_touched():
    """imd_score is not in the context plan's indicators, so it is ignored."""
    records = [{
        "geo_id": "E06000001", "year": 2025, "indicator": "imd_score",
        "breakdown": "overall", "ethnicity": None, "value": 0.49,
        "disclosure_status": "released",
    }]
    original = copy.deepcopy(records)
    build.suppress_records(records, CONTEXT_PLAN)
    assert records == original


# --------------------------------------------------------------------------
# Primary suppression
# --------------------------------------------------------------------------
def test_primary_suppression_fires_on_small_counts():
    # Two small cells: both primary-suppressed, so secondary does not fire.
    records = _lac_records([120, 95, 60, 3, 4])
    build.suppress_records(records, CONTEXT_PLAN)
    by_ethnicity = {r["ethnicity"]: r for r in records}
    for small in ("Mixed", "Other"):
        assert by_ethnicity[small]["value"] is None
        assert by_ethnicity[small]["suppressed"] is True
        assert by_ethnicity[small]["suppression_rule"] == "primary"
    for large in ("White", "Black", "Asian"):
        assert by_ethnicity[large]["value"] is not None
        assert "suppressed" not in by_ethnicity[large]


# --------------------------------------------------------------------------
# Secondary suppression
# --------------------------------------------------------------------------
def test_secondary_suppression_protects_a_lone_small_cell():
    # One small cell: primary suppresses it, secondary suppresses the
    # next-smallest non-zero cell so it cannot be back-calculated.
    records = _lac_records([120, 95, 60, 44, 3])
    build.suppress_records(records, CONTEXT_PLAN)
    by_ethnicity = {r["ethnicity"]: r for r in records}
    assert by_ethnicity["Other"]["suppression_rule"] == "primary"
    assert by_ethnicity["Mixed"]["suppression_rule"] == "secondary"
    assert by_ethnicity["Mixed"]["value"] is None
    assert "suppressed" not in by_ethnicity["White"]


# --------------------------------------------------------------------------
# Inherited suppression
# --------------------------------------------------------------------------
def test_inherited_suppression_is_carried_and_audited():
    records = _lac_records([120, 95, 60, 44, None])  # Other source-suppressed
    audit = build.suppress_records(records, CONTEXT_PLAN)
    by_ethnicity = {r["ethnicity"]: r for r in records}
    assert by_ethnicity["Other"]["suppressed"] is True
    assert by_ethnicity["Other"]["suppression_rule"] == "inherited"
    # A lone inherited suppression still triggers secondary protection.
    assert by_ethnicity["Mixed"]["suppression_rule"] == "secondary"
    rules = {entry["rule"] for entry in audit}
    assert "inherited" in rules and "secondary" in rules


# --------------------------------------------------------------------------
# Audit trail
# --------------------------------------------------------------------------
def test_audit_entries_carry_dataset_and_rule():
    records = _lac_records([120, 95, 60, 44, 3])
    audit = build.suppress_records(records, CONTEXT_PLAN)
    assert audit, "a firing rule must produce audit entries"
    for entry in audit:
        assert entry["dataset"] == "context_indicators.json"
        assert entry["rule"] in ("inherited", "primary", "secondary", "rate-threshold")
        assert "group" in entry


def test_suppression_plans_cover_the_count_bearing_outputs():
    covered = {plan.filename for plan in build.SUPPRESSION_PLANS}
    assert covered == {
        "remand_outcomes.json",
        "context_indicators.json",
        "custody_monthly.json",
        "custody_episodes_ending.json",
        "custody_episode_length.json",
        "rri.json",
    }
