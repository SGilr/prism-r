"""Disclosure control for PRISM-R, per specification section 5.

Five rules:

  1. Primary suppression: counts below 6 are suppressed.
  2. Secondary suppression: if a group holds exactly one suppressed cell, the
     next-smallest non-zero cell in that group is suppressed too, so the
     single value cannot be recovered by subtraction. A true zero is
     suppressed only as a fallback, when no non-zero cell remains.
  3. Rate threshold: a rate is not shown where its denominator is below 100.
  4. Audit: every decision is recorded, so the rule is visible and not just
     its effect. write_audit emits the audit trail as JSON.
  5. Inherited suppression: a value already suppressed in the source data
     stays suppressed and is flagged as inherited.

The module is a library. Ingest steps build Cell records, call
apply_suppression, and write the audit through write_audit. A group is a set
of cells that sum to a meaningful total, for example one local authority's
counts across the ethnicity categories.

A count of exactly 0 is a true zero, not a disclosure risk. It is not
suppressed: it is shown as "0". Only counts of 1 to 5 are primarily
suppressed.

Each result cell carries a value_type, one of: observed, true_zero,
suppressed_primary, suppressed_secondary, suppressed_inherited, rate_hidden.
A suppressed count takes precedence in this classification; rate_hidden
applies only where the count itself is shown but its rate is not.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PRIMARY_THRESHOLD = 6
RATE_MIN_DENOMINATOR = 100

SUPPRESSED_LABEL = "<6, suppressed for disclosure control"
RATE_NOT_SHOWN_LABEL = "rate not shown, population too small"


@dataclass(frozen=True)
class Cell:
    """One count to be assessed for disclosure control.

    cell_id            unique identifier
    group              cells sharing a group form one suppression dimension
    count              the count, or None where the source gives no value
    denominator        the population behind a rate, used by rule 3; optional
    source_suppressed  True where the source has already suppressed the value
    """

    cell_id: str
    group: str
    count: int | None = None
    denominator: int | None = None
    source_suppressed: bool = False


@dataclass
class SuppressionResult:
    """Outcome of apply_suppression: annotated cells and the audit trail."""

    cells: list[dict]
    audit: list[dict]


def apply_suppression(cells: list[Cell]) -> SuppressionResult:
    """Apply the five disclosure control rules to a list of cells."""
    ordered = sorted(cells, key=lambda c: c.cell_id)
    state: dict[str, dict] = {
        cell.cell_id: {
            "cell_id": cell.cell_id,
            "group": cell.group,
            "count": cell.count,
            "suppressed": False,
            "rule": None,
            "rate_suppressed": False,
        }
        for cell in ordered
    }
    audit: list[dict] = []

    def _suppress(
        cell_id: str,
        rule: str,
        original: int | None,
        detail: str,
        reason: str | None = None,
    ) -> None:
        cell_state = state[cell_id]
        cell_state["suppressed"] = True
        cell_state["rule"] = rule
        cell_state["count"] = None
        audit.append(
            {
                "cell_id": cell_id,
                "group": cell_state["group"],
                "rule": rule,
                "reason": reason,
                "original_count": original,
                "resulting_state": "suppressed",
                "detail": detail,
            }
        )

    # Rule 5: inherited suppression.
    for cell in ordered:
        if cell.source_suppressed:
            _suppress(
                cell.cell_id,
                "inherited",
                cell.count,
                "value already suppressed in source data",
            )

    # Rule 1: primary suppression. A count of 0 is a true zero, not a small
    # cell, so only counts of 1 to 5 are suppressed here.
    for cell in ordered:
        if state[cell.cell_id]["suppressed"] or cell.count is None:
            continue
        if 0 < cell.count < PRIMARY_THRESHOLD:
            _suppress(
                cell.cell_id,
                "primary",
                cell.count,
                f"count {cell.count} below threshold {PRIMARY_THRESHOLD}",
            )

    # Rule 2: secondary suppression, per group.
    groups: dict[str, list[Cell]] = {}
    for cell in ordered:
        groups.setdefault(cell.group, []).append(cell)
    for group in sorted(groups):
        members = groups[group]
        suppressed = [c for c in members if state[c.cell_id]["suppressed"]]
        if len(suppressed) != 1:
            continue
        candidates = [
            c
            for c in members
            if not state[c.cell_id]["suppressed"] and c.count is not None
        ]
        if not candidates:
            audit.append(
                {
                    "cell_id": None,
                    "group": group,
                    "rule": "secondary",
                    "reason": None,
                    "original_count": None,
                    "resulting_state": "not applied",
                    "detail": "one cell suppressed but no further cell to suppress",
                }
            )
            continue
        # The next-smallest rule prefers a non-zero cell: suppressing a true
        # zero protects the primary cell but needlessly hides a zero. A zero
        # is suppressed only as a fallback, when no non-zero cell remains.
        non_zero = [c for c in candidates if c.count > 0]
        if non_zero:
            target = min(non_zero, key=lambda c: (c.count, c.cell_id))
            reason = "next_smallest_nonzero"
            detail = (
                f"secondary suppression of the smallest non-zero cell so the "
                f"single suppressed cell in group {group!r} cannot be recovered"
            )
        else:
            target = min(candidates, key=lambda c: c.cell_id)
            reason = "secondary_skipped_zero"
            detail = (
                f"every remaining cell in group {group!r} is a true zero; a "
                f"zero is suppressed to preserve the primary suppressed cell"
            )
        _suppress(target.cell_id, "secondary", target.count, detail, reason=reason)

    # Rule 3: rate threshold.
    for cell in ordered:
        if cell.denominator is not None and cell.denominator < RATE_MIN_DENOMINATOR:
            state[cell.cell_id]["rate_suppressed"] = True
            audit.append(
                {
                    "cell_id": cell.cell_id,
                    "group": cell.group,
                    "rule": "rate-threshold",
                    "reason": None,
                    "original_count": cell.count,
                    "resulting_state": "rate not shown",
                    "detail": f"denominator {cell.denominator} below {RATE_MIN_DENOMINATOR}",
                }
            )

    result_cells = []
    for cell in ordered:
        cell_state = state[cell.cell_id]
        rule = cell_state["rule"]
        if rule == "inherited":
            value_type = "suppressed_inherited"
        elif rule == "secondary":
            value_type = "suppressed_secondary"
        elif rule == "primary":
            value_type = "suppressed_primary"
        elif cell_state["count"] == 0:
            value_type = "true_zero"
        elif cell_state["rate_suppressed"]:
            value_type = "rate_hidden"
        else:
            value_type = "observed"

        if cell_state["suppressed"]:
            display = SUPPRESSED_LABEL
        elif cell_state["count"] is None:
            display = "n/a"
        else:
            display = str(cell_state["count"])

        result_cells.append(
            {
                "cell_id": cell_state["cell_id"],
                "group": cell_state["group"],
                "count": cell_state["count"],
                "suppressed": cell_state["suppressed"],
                "rule": rule,
                "value_type": value_type,
                "display": display,
                "rate_suppressed": cell_state["rate_suppressed"],
                "rate_display": RATE_NOT_SHOWN_LABEL
                if cell_state["rate_suppressed"]
                else None,
            }
        )

    audit.sort(key=lambda a: (a["group"], a["cell_id"] or "", a["rule"]))
    return SuppressionResult(cells=result_cells, audit=audit)


def write_audit(audit: list[dict], path: Path) -> None:
    """Write the suppression audit trail as JSON, with a rule summary."""
    by_rule: dict[str, int] = {}
    for entry in audit:
        by_rule[entry["rule"]] = by_rule.get(entry["rule"], 0) + 1
    payload = {
        "meta": {
            "dataset": "suppression_audit",
            "generated_by": "pipeline/suppress.py",
            "schema_note": (
                "One record per disclosure control decision. rule is "
                "inherited, primary, secondary or rate-threshold. The trail "
                "lets a reader see the rule applied, not just its effect."
            ),
            "counts": {"decisions": len(audit), "by_rule": by_rule},
        },
        "records": audit,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
