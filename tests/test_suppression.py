"""Tests for disclosure control logic in pipeline/suppress.py.

Each of the five rules in specification section 5 is exercised with
synthetic inputs, together with the true-zero distinction and the
back-calculation protection that secondary suppression provides.
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


def _suppressed_per_group(result):
    counts = {}
    for cell in result.cells:
        counts.setdefault(cell["group"], 0)
        if cell["suppressed"]:
            counts[cell["group"]] += 1
    return counts


# --------------------------------------------------------------------------
# Rule 1: primary suppression (counts 1 to 5)
# --------------------------------------------------------------------------
def test_primary_suppresses_counts_one_to_five():
    # Two sub-threshold cells, so no single-cell secondary suppression fires.
    result = apply_suppression(
        [Cell("a", "g", 3), Cell("b", "g", 4), Cell("c", "g", 100), Cell("d", "g", 200)]
    )
    by = _by_id(result)
    assert by["a"]["suppressed"] and by["a"]["value_type"] == "suppressed_primary"
    assert by["b"]["suppressed"] and by["b"]["value_type"] == "suppressed_primary"
    assert by["a"]["count"] is None
    assert by["a"]["display"] == suppress.SUPPRESSED_LABEL
    assert not by["c"]["suppressed"] and by["c"]["count"] == 100
    assert by["c"]["value_type"] == "observed" and by["c"]["display"] == "100"


def test_primary_threshold_boundary():
    # 5 is below 6 and suppressed; 6 and above are not. 0 is handled separately.
    result = apply_suppression(
        [Cell("five", "g", 5), Cell("small", "g", 2), Cell("six", "g", 6), Cell("hi", "g", 11)]
    )
    by = _by_id(result)
    assert by["five"]["suppressed"]
    assert not by["six"]["suppressed"] and by["six"]["value_type"] == "observed"
    assert not by["hi"]["suppressed"]


# --------------------------------------------------------------------------
# True-zero distinction (Task 2 refinement)
# --------------------------------------------------------------------------
def test_true_zero_is_not_suppressed():
    # A count of exactly 0 is a true zero: shown as "0", not suppressed.
    result = apply_suppression([Cell("zero", "g", 0), Cell("obs", "g", 40), Cell("more", "g", 50)])
    by = _by_id(result)
    assert not by["zero"]["suppressed"]
    assert by["zero"]["value_type"] == "true_zero"
    assert by["zero"]["count"] == 0
    assert by["zero"]["display"] == "0"
    assert by["zero"]["rule"] is None


def test_true_zero_distinct_from_small_cell():
    # 0 stays visible; 1 to 5 are suppressed. The two are not conflated.
    # Separate groups, and a paired small cell, so secondary suppression
    # does not reclassify either cell under test.
    result = apply_suppression(
        [
            Cell("zero", "gz", 0),
            Cell("zero_partner", "gz", 80),
            Cell("one", "go", 1),
            Cell("one_partner", "go", 2),
        ]
    )
    by = _by_id(result)
    assert by["zero"]["value_type"] == "true_zero"
    assert by["one"]["value_type"] == "suppressed_primary"
    assert by["one"]["display"] == suppress.SUPPRESSED_LABEL


# --------------------------------------------------------------------------
# Rule 5: inherited suppression
# --------------------------------------------------------------------------
def test_inherited_suppression_is_flagged():
    result = apply_suppression(
        [Cell("a", "g", None, source_suppressed=True), Cell("b", "g", 4)]
    )
    by = _by_id(result)
    assert by["a"]["suppressed"] and by["a"]["value_type"] == "suppressed_inherited"
    assert by["b"]["suppressed"] and by["b"]["value_type"] == "suppressed_primary"


# --------------------------------------------------------------------------
# Rule 2: secondary suppression and back-calculation protection
# --------------------------------------------------------------------------
def test_secondary_suppresses_next_smallest():
    # One primary suppression in the group triggers a secondary one.
    result = apply_suppression(
        [Cell("a", "g", 3), Cell("b", "g", 8), Cell("c", "g", 50), Cell("d", "g", 100)]
    )
    by = _by_id(result)
    assert by["a"]["value_type"] == "suppressed_primary"
    assert by["b"]["value_type"] == "suppressed_secondary"  # 8 is the next-smallest
    assert not by["c"]["suppressed"] and not by["d"]["suppressed"]
    assert _suppressed_per_group(result)["g"] == 2


def test_secondary_picks_the_smallest_remaining_cell():
    # Four cells, one below 6: secondary must pick the smallest of the rest.
    result = apply_suppression(
        [Cell("a", "g", 2), Cell("big", "g", 40), Cell("mid", "g", 9), Cell("hi", "g", 30)]
    )
    by = _by_id(result)
    assert by["a"]["value_type"] == "suppressed_primary"
    assert by["mid"]["value_type"] == "suppressed_secondary"  # 9, smallest of 40, 9, 30
    assert not by["big"]["suppressed"] and not by["hi"]["suppressed"]


def test_secondary_closes_the_single_suppression_back_calculation_hole():
    # With one cell suppressed and a known group total, that cell would equal
    # total minus the visible cells. Secondary suppression hides a second
    # cell so the group never has exactly one suppressed cell.
    result = apply_suppression([Cell("a", "g", 3), Cell("b", "g", 8), Cell("c", "g", 50)])
    assert _suppressed_per_group(result)["g"] == 2


def test_two_primary_suppressions_prevent_back_calculation():
    # A small group where two cells are each below 6. Both are primary
    # suppressed, so an observer who knows the group total learns only the
    # hidden pair's sum (here 7); neither cell is individually recoverable.
    # Secondary suppression does not fire: the hole is already closed.
    result = apply_suppression([Cell("a", "g", 3), Cell("b", "g", 4), Cell("c", "g", 90)])
    by = _by_id(result)
    assert by["a"]["suppressed"] and by["b"]["suppressed"]
    assert by["a"]["count"] is None and by["b"]["count"] is None
    assert not by["c"]["suppressed"]
    assert _suppressed_per_group(result)["g"] == 2
    assert not any(c["value_type"] == "suppressed_secondary" for c in result.cells)


def test_four_cells_all_below_six_all_suppressed_no_secondary():
    # All four cells are below 6, so all are primary suppressed. Secondary
    # suppression does not fire: with every cell hidden, a known total
    # reveals only the total, never an individual cell.
    result = apply_suppression(
        [Cell("a", "g", 2), Cell("b", "g", 3), Cell("c", "g", 4), Cell("d", "g", 5)]
    )
    assert all(c["suppressed"] for c in result.cells)
    assert all(c["value_type"] == "suppressed_primary" for c in result.cells)
    assert not any(c["value_type"] == "suppressed_secondary" for c in result.cells)


def test_secondary_not_triggered_without_suppression():
    result = apply_suppression([Cell("a", "g", 10), Cell("b", "g", 20)])
    assert _suppressed_per_group(result)["g"] == 0


def test_secondary_records_when_no_further_cell_exists():
    # A single-cell group cannot be protected: the audit records that the
    # secondary rule could not be applied, surfacing the residual risk.
    result = apply_suppression([Cell("only", "g", 3)])
    by = _by_id(result)
    assert by["only"]["suppressed"]
    not_applied = [a for a in result.audit if a["resulting_state"] == "not applied"]
    assert len(not_applied) == 1
    assert not_applied[0]["group"] == "g"


def test_secondary_skips_true_zeros_when_a_nonzero_exists():
    # Secondary suppression prefers the smallest non-zero cell. The true zero
    # is left visible; the non-zero cell is suppressed instead.
    result = apply_suppression([Cell("a", "g", 3), Cell("z", "g", 0), Cell("c", "g", 50)])
    by = _by_id(result)
    assert by["a"]["value_type"] == "suppressed_primary"
    assert by["z"]["value_type"] == "true_zero"  # zero skipped, stays visible
    assert by["c"]["value_type"] == "suppressed_secondary"  # non-zero suppressed instead


def test_secondary_falls_back_to_zero_when_no_nonzero_available():
    # Degenerate case: the only remaining candidates are true zeros. A zero
    # is then suppressed to preserve the primary cell, and the audit records
    # the choice with reason "secondary_skipped_zero".
    result = apply_suppression([Cell("a", "g", 3), Cell("z1", "g", 0), Cell("z2", "g", 0)])
    by = _by_id(result)
    assert by["a"]["value_type"] == "suppressed_primary"
    secondaries = [c for c in result.cells if c["value_type"] == "suppressed_secondary"]
    true_zeros = [c for c in result.cells if c["value_type"] == "true_zero"]
    assert len(secondaries) == 1 and len(true_zeros) == 1
    assert _suppressed_per_group(result)["g"] == 2
    fallback = [
        a for a in result.audit
        if a["rule"] == "secondary" and a["reason"] == "secondary_skipped_zero"
    ]
    assert len(fallback) == 1


def test_secondary_is_per_group():
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
def test_rate_hidden_below_denominator_threshold_with_moderate_numerator():
    # The numerator is moderate (45) and not itself suppressed, but the
    # denominator (70) is below 100, so the rate is not shown.
    result = apply_suppression(
        [Cell("small", "g", 45, denominator=70), Cell("ok", "g", 45, denominator=600)]
    )
    by = _by_id(result)
    assert not by["small"]["suppressed"]
    assert by["small"]["rate_suppressed"]
    assert by["small"]["rate_display"] == suppress.RATE_NOT_SHOWN_LABEL
    assert by["small"]["value_type"] == "rate_hidden"
    assert not by["ok"]["rate_suppressed"]
    assert by["ok"]["value_type"] == "observed"


def test_rate_threshold_boundary():
    result = apply_suppression(
        [Cell("a", "g", 50, denominator=99), Cell("b", "g", 50, denominator=100)]
    )
    by = _by_id(result)
    assert by["a"]["rate_suppressed"]
    assert not by["b"]["rate_suppressed"]


def test_rate_and_count_suppression_are_independent():
    # A count can be suppressed while its denominator is comfortably large,
    # and a count can be shown while its rate is hidden. The two rules act
    # independently. Separate groups keep secondary suppression out of it.
    result = apply_suppression(
        [
            Cell("count_suppressed", "g1", 3, denominator=500),
            Cell("count_suppressed_partner", "g1", 4, denominator=500),
            Cell("rate_hidden", "g2", 50, denominator=40),
        ]
    )
    by = _by_id(result)
    assert by["count_suppressed"]["value_type"] == "suppressed_primary"
    assert not by["count_suppressed"]["rate_suppressed"]  # denominator 500 is fine
    assert by["rate_hidden"]["value_type"] == "rate_hidden"
    assert by["rate_hidden"]["rate_suppressed"]
    assert not by["rate_hidden"]["suppressed"]  # the count itself is shown


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
# value_type classification and determinism
# --------------------------------------------------------------------------
def test_value_type_covers_every_classification():
    result = apply_suppression(
        [
            Cell("observed", "g1", 50, denominator=500),
            Cell("zero", "g1", 0),
            Cell("primary", "g2", 3),
            Cell("primary_partner", "g2", 4),
            Cell("secondary_trigger", "g3", 2),
            Cell("secondary_target", "g3", 40),
            Cell("inherited", "g4", None, source_suppressed=True),
            Cell("inherited_partner", "g4", 70),
            Cell("rate", "g5", 30, denominator=20),
        ]
    )
    by = _by_id(result)
    assert by["observed"]["value_type"] == "observed"
    assert by["zero"]["value_type"] == "true_zero"
    assert by["primary"]["value_type"] == "suppressed_primary"
    assert by["secondary_target"]["value_type"] == "suppressed_secondary"
    assert by["inherited"]["value_type"] == "suppressed_inherited"
    assert by["rate"]["value_type"] == "rate_hidden"


def test_apply_suppression_is_deterministic():
    cells = [Cell("a", "g", 3), Cell("b", "g", 8), Cell("c", "g", 50)]
    first = apply_suppression(cells)
    second = apply_suppression(list(reversed(cells)))
    assert first.cells == second.cells
    assert first.audit == second.audit


# --------------------------------------------------------------------------
# Rule 2b: derived-field recovery, across every processed output
#
# Added after a defect in which suppressing a count left its rate in place.
# A rate against a published denominator is the count written differently, so
# these tests read the real build outputs rather than synthetic cells: they
# are the structural guard that fails if a future indicator reintroduces the
# pattern. See the "Corrections" section of docs/methods.md.
# --------------------------------------------------------------------------
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

# Fields from which a suppressed count could be reconstructed. A rate needs a
# denominator; a numerator is the count itself under another name.
RECOVERABLE_FIELDS = ("numerator", "rate_per_100", "rate_per_1000",
                      "source_rate", "share", "percentage", "proportion")

# Denominator bases a rate might have been computed against. rate_per_100 is
# a percentage of the denominator, rate_per_1000 a rate per mille.
RATE_BASES = {"rate_per_100": 100, "rate_per_1000": 1000, "share": 1,
              "percentage": 100, "proportion": 1}


def _processed_records():
    """Every record in every processed output that carries a records array."""
    for path in sorted(PROCESSED_DIR.rglob("*.json")):
        if path.name in ("manifest.json", "suppression_audit.json"):
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        records = payload.get("records")
        if not isinstance(records, list):
            continue
        for record in records:
            if isinstance(record, dict):
                yield path.relative_to(PROCESSED_DIR).as_posix(), record


def _population_denominators():
    """Child population by geography and ethnic group, and rolled up to the
    police force areas and upper-tier authorities the crosswalk defines.

    These are the denominators PRISM-R itself publishes, so they are exactly
    what an observer would multiply a leaked rate by.
    """
    populations = json.loads(
        (PROCESSED_DIR / "populations.json").read_text(encoding="utf-8"))["records"]
    crosswalk = json.loads(
        (PROCESSED_DIR / "geo_crosswalk.json").read_text(encoding="utf-8"))["records"]
    parents = {r["la_code"]: (r["parent_force"], r["utla_code"]) for r in crosswalk}

    totals: dict[tuple[str, str], int] = {}

    def add(geo_id, ethnicity, count):
        for key in ((geo_id, ethnicity), (geo_id, "overall")):
            totals[key] = totals.get(key, 0) + count

    for record in populations:
        if record["population"] is None or record["ethnicity"] is None:
            continue
        add(record["geo_id"], record["ethnicity"], record["population"])
        force, utla = parents.get(record["geo_id"], (None, None))
        for parent in (force, utla):
            if parent:
                add(parent, record["ethnicity"], record["population"])
    return totals


def test_suppressed_counts_leave_no_recoverable_field():
    """Rule 2b, the structural guard.

    For every suppressed record in every processed output, no numeric field
    may remain that reproduces a below-threshold count when multiplied by a
    denominator available either on the record itself or in populations.json.
    The strict form is asserted: a suppressed record carries none of the
    recoverable fields at all, because a rate whose denominator we cannot
    locate today may become recoverable the moment that denominator is
    published.
    """
    denominators = _population_denominators()
    offenders = []
    for filename, record in _processed_records():
        suppressed = (record.get("suppressed") is True
                      or record.get("disclosure_status") in
                      ("suppressed", "source_suppressed"))
        if not suppressed:
            continue
        for field in RECOVERABLE_FIELDS:
            value = record.get(field)
            if not isinstance(value, (int, float)):
                continue
            # Name the recovery route in the failure, so a future breakage is
            # actionable rather than merely red.
            denominator = record.get("denominator")
            if not isinstance(denominator, (int, float)):
                ethnicity = record.get("ethnicity") or "overall"
                denominator = denominators.get((record.get("geo_id"), ethnicity))
            base = RATE_BASES.get(field)
            recovered = (value * denominator / base
                         if denominator and base else None)
            offenders.append(
                f"{filename}: {record.get('geo_id')} "
                f"{record.get('indicator')} {record.get('ethnicity')} "
                f"is suppressed but carries {field}={value}"
                + (f", which against a published denominator of "
                   f"{denominator:.0f} recovers {recovered:.1f}"
                   if recovered is not None else ""))
    assert not offenders, (
        f"{len(offenders)} suppressed cells carry a recoverable field, "
        "breaching disclosure rule 2b:\n" + "\n".join(offenders[:12]))


def test_the_guard_would_catch_the_original_defect():
    """The defect this rule was written for: a stop and search count nulled
    while its rate survived. The denominator is the Census child population
    PRISM-R publishes, so the count multiplies straight back out."""
    denominators = _population_denominators()
    # A primary suppression from the affected set: Dorset, Asian children,
    # two searches, hidden as a count of 1 to 5 and then handed back by the
    # rate. Twenty of the thirty affected cells were primary like this one;
    # the other ten were secondary, hiding larger counts to protect these.
    force, ethnicity = "pf-dorset", "Asian"
    denominator = denominators.get((force, ethnicity))
    assert denominator, "the force-level Census denominator must be resolvable"

    # The shape of the original leaking record, reconstructed.
    leaking = {"geo_id": force, "ethnicity": ethnicity,
               "indicator": "stop_search_rate", "value": None,
               "rate_per_1000": 1.08225, "suppressed": True,
               "disclosure_status": "released"}
    recovered = leaking["rate_per_1000"] * denominator / 1000
    assert recovered < 6, (
        "the recovered count must be below the suppression threshold, "
        "which is what made this a disclosure and not merely untidy")
    assert round(recovered) == 2, "the exact suppressed count comes back"

    offending = [f for f in RECOVERABLE_FIELDS
                 if isinstance(leaking.get(f), (int, float))]
    assert offending == ["rate_per_1000"], (
        "the guard must flag the surviving rate field")
