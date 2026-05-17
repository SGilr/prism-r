"""Tests for disclosure control logic in pipeline/suppress.py.

Each of the five rules in specification section 5 is exercised with
synthetic inputs.
"""

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from pipeline import suppress  # noqa: E402
from pipeline.suppress import Cell, apply_suppression, write_audit  # noqa: E402


def _by_id(result):
    return {c["cell_id"]: c for c in result.cells}


# --------------------------------------------------------------------------
# Rule 1: primary suppression
# --------------------------------------------------------------------------
def test_primary_suppresses_counts_below_six():
    # Two sub-threshold cells, so no single-cell secondary suppression fires.
    result = apply_suppression(
        [
            Cell("a", "g", 3),
            Cell("b", "g", 4),
            Cell("c", "g", 100),
            Cell("d", "g", 200),
        ]
    )
    by = _by_id(result)
    assert by["a"]["suppressed"] and by["a"]["rule"] == "primary"
    assert by["b"]["suppressed"] and by["b"]["rule"] == "primary"
    assert by["a"]["count"] is None
    assert by["a"]["display"] == suppress.SUPPRESSED_LABEL
    assert not by["c"]["suppressed"] and by["c"]["count"] == 100
    assert by["c"]["display"] == "100"


def test_primary_threshold_boundary():
    # 0 and 5 are below 6 and suppressed; 6 and above are not.
    result = apply_suppression(
        [Cell("zero", "g", 0), Cell("five", "g", 5), Cell("six", "g", 6), Cell("hi", "g", 11)]
    )
    by = _by_id(result)
    assert by["zero"]["suppressed"]
    assert by["five"]["suppressed"]
    assert not by["six"]["suppressed"]
    assert not by["hi"]["suppressed"]


# --------------------------------------------------------------------------
# Rule 5: inherited suppression
# --------------------------------------------------------------------------
def test_inherited_suppression_is_flagged():
    result = apply_suppression(
        [
            Cell("a", "g", None, source_suppressed=True),
            Cell("b", "g", 4),
        ]
    )
    by = _by_id(result)
    assert by["a"]["suppressed"] and by["a"]["rule"] == "inherited"
    assert by["b"]["suppressed"] and by["b"]["rule"] == "primary"


# --------------------------------------------------------------------------
# Rule 2: secondary suppression
# --------------------------------------------------------------------------
def test_secondary_suppresses_next_smallest():
    # One primary suppression in the group triggers a secondary one.
    result = apply_suppression(
        [Cell("a", "g", 3), Cell("b", "g", 8), Cell("c", "g", 50), Cell("d", "g", 100)]
    )
    by = _by_id(result)
    assert by["a"]["rule"] == "primary"
    assert by["b"]["rule"] == "secondary"  # 8 is the next-smallest
    assert not by["c"]["suppressed"] and not by["d"]["suppressed"]
    assert sum(c["suppressed"] for c in result.cells) == 2


def test_secondary_picks_the_smallest_remaining_cell():
    result = apply_suppression(
        [Cell("a", "g", 2), Cell("big", "g", 40), Cell("mid", "g", 9), Cell("hi", "g", 30)]
    )
    by = _by_id(result)
    assert by["a"]["rule"] == "primary"
    assert by["mid"]["rule"] == "secondary"  # 9 is smallest of 40, 9, 30
    assert not by["big"]["suppressed"] and not by["hi"]["suppressed"]


def test_secondary_not_triggered_when_two_already_suppressed():
    result = apply_suppression([Cell("a", "g", 3), Cell("b", "g", 4), Cell("c", "g", 50)])
    by = _by_id(result)
    assert not by["c"]["suppressed"]
    assert sum(c["suppressed"] for c in result.cells) == 2


def test_secondary_not_triggered_without_suppression():
    result = apply_suppression([Cell("a", "g", 10), Cell("b", "g", 20)])
    assert sum(c["suppressed"] for c in result.cells) == 0


def test_secondary_records_when_no_further_cell_exists():
    result = apply_suppression([Cell("only", "g", 3)])
    by = _by_id(result)
    assert by["only"]["suppressed"]
    not_applied = [a for a in result.audit if a["resulting_state"] == "not applied"]
    assert len(not_applied) == 1
    assert not_applied[0]["group"] == "g"


def test_secondary_is_per_group():
    # Group g1 gets a secondary suppression; group g2 is untouched.
    result = apply_suppression(
        [
            Cell("g1a", "g1", 3),
            Cell("g1b", "g1", 9),
            Cell("g2a", "g2", 10),
            Cell("g2b", "g2", 20),
        ]
    )
    by = _by_id(result)
    assert by["g1a"]["suppressed"] and by["g1b"]["suppressed"]
    assert not by["g2a"]["suppressed"] and not by["g2b"]["suppressed"]


# --------------------------------------------------------------------------
# Rule 3: rate threshold
# --------------------------------------------------------------------------
def test_rate_suppressed_below_denominator_threshold():
    result = apply_suppression(
        [
            Cell("small", "g", 60, denominator=80),
            Cell("ok", "g", 60, denominator=500),
        ]
    )
    by = _by_id(result)
    assert by["small"]["rate_suppressed"]
    assert by["small"]["rate_display"] == suppress.RATE_NOT_SHOWN_LABEL
    assert not by["ok"]["rate_suppressed"]
    assert by["ok"]["rate_display"] is None


def test_rate_threshold_boundary():
    result = apply_suppression(
        [Cell("a", "g", 50, denominator=99), Cell("b", "g", 50, denominator=100)]
    )
    by = _by_id(result)
    assert by["a"]["rate_suppressed"]
    assert not by["b"]["rate_suppressed"]


def test_rate_and_count_suppression_are_independent():
    # Count fine but denominator small: rate suppressed, count shown.
    result = apply_suppression([Cell("a", "g", 80, denominator=40), Cell("b", "g", 90)])
    by = _by_id(result)
    assert not by["a"]["suppressed"]
    assert by["a"]["count"] == 80
    assert by["a"]["rate_suppressed"]


# --------------------------------------------------------------------------
# Rule 4: audit trail
# --------------------------------------------------------------------------
def test_audit_records_every_rule():
    # g1: inherited suppression triggers a secondary one.
    # g2: primary suppression triggers a secondary one.
    # g3: a small denominator triggers the rate threshold.
    result = apply_suppression(
        [
            Cell("inh", "g1", None, source_suppressed=True),
            Cell("inh_partner", "g1", 20),
            Cell("pri", "g2", 3),
            Cell("pri_partner", "g2", 30),
            Cell("rate", "g3", 80, denominator=20),
        ]
    )
    rules = {a["rule"] for a in result.audit}
    assert {"inherited", "primary", "secondary", "rate-threshold"} <= rules
    for entry in result.audit:
        assert "original_count" in entry
        assert "resulting_state" in entry
        assert entry["detail"]


def test_write_audit_round_trip(tmp_path):
    result = apply_suppression([Cell("a", "g", 3), Cell("b", "g", 9)])
    path = tmp_path / "suppression_audit.json"
    write_audit(result.audit, path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["meta"]["dataset"] == "suppression_audit"
    assert payload["meta"]["counts"]["decisions"] == len(result.audit)
    assert len(payload["records"]) == len(result.audit)


# --------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------
def test_apply_suppression_is_deterministic():
    cells = [Cell("a", "g", 3), Cell("b", "g", 8), Cell("c", "g", 50)]
    first = apply_suppression(cells)
    second = apply_suppression(list(reversed(cells)))
    assert first.cells == second.cells
    assert first.audit == second.audit
