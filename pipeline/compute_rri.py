"""Compute Relative Rate Index (RRI) values for PRISM-R.

The Relative Rate Index compares the rate at which an ethnic group
experiences an outcome with the rate for the White baseline group. It was
recommended in the Lammy Review (2017) and is used by the Ministry of
Justice in Statistics on Ethnicity and the Criminal Justice System.

    RRI = (event rate for the group) / (event rate for the White group)

A value of 1 is parity, above 1 means the group is more likely to
experience the outcome, below 1 less likely.

Four RRI series are produced:

  custodial_sentence  adult  moj_published    adopted from MoJ Table 9.01
  custodial_sentence  child  prism_r_derived  computed from YJB Table 5.8
  remand              adult  moj_published    adopted from MoJ Table 5.17a
  remand              child  prism_r_derived  computed from YJB remand data

The adult RRIs are adopted verbatim from MoJ's published tables. MoJ does
not publish the underlying counts, the source Court Proceedings Database is
not public, so they cannot be reproduced from public data and carry no
confidence interval. MoJ's p-value-based significance flag is retained.

The child RRIs are computed by PRISM-R from open YJB youth data. No
child-specific RRI exists in published official statistics. Confidence
intervals use the Wald interval on the log of the rate ratio (Altman,
Machin, Bryant and Gardner, Statistics with Confidence, 2nd ed., BMJ Books,
2000):

    SE(ln RRI) = sqrt(1/a + 1/b - 1/A - 1/B)
    95% CI     = exp( ln(RRI) +/- 1.96 * SE(ln RRI) )

Child custodial sentencing counts are small enough that a single year is
statistically fragile, so the primary figure is a three-year pooled
estimate (years ending March 2023, 2024, 2025); single-year values are
retained for inspection. Child remand counts are stable and are not pooled.
See docs/methods.md.

Reporting periods differ: adult rows are calendar year 2024 (the MoJ basis),
child rows are years ending March (the YJB basis). PRISM-R does not force
one onto the other.
"""

from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

MOJ_CH9 = REPO_ROOT / "data" / "raw" / "moj" / "ch9_offence_analysis_2024.ods"
MOJ_CH5 = REPO_ROOT / "data" / "raw" / "moj" / "ch5_defendants_tables_2024.ods"
YJB_CH5 = REPO_ROOT / "data" / "raw" / "yjb-2024-25" / "Ch 5 - Sentencing of children.xlsx"
REMAND_OUTCOMES = PROCESSED_DIR / "remand_outcomes.json"
OUTPUT = PROCESSED_DIR / "rri.json"

# 95% interval. The standard 1.96 multiplier, per the cited method.
Z_95 = 1.96

BASELINE = "White"
GROUPS = ["Asian", "Black", "Mixed", "Other"]
ALL_ETHNICITIES = [BASELINE, *GROUPS]

ADULT_YEAR = 2024
CHILD_REMAND_YEAR = 2025  # year ending March 2025
CHILD_SENTENCING_YEARS = [2023, 2024, 2025]  # years ending March; pooled
POOLED_PERIOD = "pooled_3y_ending_march_2025"

ADULT_SOURCE = {
    "source_publication": "Statistics on Ethnicity and the Criminal Justice System 2024",
    "publication_date": "2025-11-27",
    "url": "https://www.gov.uk/government/statistics/ethnicity-and-the-criminal-justice-system-2024",
}
CHILD_SOURCE = {
    "source_publication": "Youth Justice Statistics 2024 to 2025",
    "publication_date": "2026-01-29",
    "url": "https://www.gov.uk/government/statistics/youth-justice-statistics-2024-to-2025",
}

_NOTE_RE = re.compile(r"\[note[^\]]*\]", re.IGNORECASE)


# --------------------------------------------------------------------------
# RRI and confidence interval
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class RRIResult:
    """An RRI estimate with its 95% Wald log-ratio confidence interval."""

    rri: float
    se_ln: float
    ci_lower: float
    ci_upper: float


def relative_rate_index(
    events: int, total: int, baseline_events: int, baseline_total: int
) -> RRIResult:
    """RRI of a group versus the White baseline, with a 95% confidence interval.

    The interval is the Wald interval on the log of the rate ratio. It is
    unreliable when any count is very small; see docs/methods.md.
    """
    if min(events, total, baseline_events, baseline_total) <= 0:
        raise ValueError("RRI requires positive event counts and totals")
    if events > total or baseline_events > baseline_total:
        raise ValueError("event count cannot exceed its total")

    rate = events / total
    baseline_rate = baseline_events / baseline_total
    rri = rate / baseline_rate
    se_ln = math.sqrt(
        1 / events + 1 / baseline_events - 1 / total - 1 / baseline_total
    )
    half_width = Z_95 * se_ln
    return RRIResult(
        rri=rri,
        se_ln=se_ln,
        ci_lower=math.exp(math.log(rri) - half_width),
        ci_upper=math.exp(math.log(rri) + half_width),
    )


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _clean(value: object) -> str:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return ""
    return re.sub(r"\s+", " ", _NOTE_RE.sub("", str(value))).strip()


def _as_year(value: object) -> int | None:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _row(**fields) -> dict:
    return fields


# --------------------------------------------------------------------------
# Adult RRIs, adopted from MoJ published tables
# --------------------------------------------------------------------------
def read_moj_adult_rri(ods_path: Path, sheet: str) -> dict[str, dict]:
    """Read the 2024 RRI row of a MoJ RRI table.

    Returns {ethnicity: {"rri": float, "significance_flag": str}} for the
    four non-White groups. Works for Table 9.01 and the first table on the
    chapter 5 RRI sheet (Table 5.17a).
    """
    frame = pd.read_excel(ods_path, sheet_name=sheet, engine="odf", header=None)
    rows = frame.values.tolist()

    header_idx = next(i for i, r in enumerate(rows) if _clean(r[0]) == "Year")
    header = [_clean(c) for c in rows[header_idx]]

    columns: dict[str, tuple[int, int]] = {}
    for group in GROUPS:
        rri_col = next(
            j for j, h in enumerate(header)
            if group.lower() in h.lower() and "rri" in h.lower()
        )
        sig_col = next(
            j for j, h in enumerate(header)
            if group.lower() in h.lower() and "significan" in h.lower()
        )
        columns[group] = (rri_col, sig_col)

    data_row = None
    for row in rows[header_idx + 1:]:
        if _clean(row[0]).lower().startswith("table"):
            break  # the next table on the sheet; stop
        if _as_year(row[0]) == ADULT_YEAR:
            data_row = row
            break
    if data_row is None:
        raise ValueError(f"{ods_path.name} {sheet}: {ADULT_YEAR} row not found")

    return {
        group: {
            "rri": float(data_row[rri_col]),
            "significance_flag": _clean(data_row[sig_col]),
        }
        for group, (rri_col, sig_col) in columns.items()
    }


# --------------------------------------------------------------------------
# Child counts, read from open YJB data
# --------------------------------------------------------------------------
def read_child_custodial_counts() -> dict[int, dict[str, dict[str, int]]]:
    """Read YJB Table 5.8: children sentenced for indictable offences.

    Table 5.8 is a time series, so the single 2024-25 publication carries
    every year ending March 2023, 2024 and 2025. Returns
    {year: {ethnicity: {"events": immediate custody, "total": total sentenced}}}.
    """
    workbook = openpyxl.load_workbook(YJB_CH5, data_only=True)
    try:
        rows = list(workbook["5.8"].iter_rows(values_only=True))
    finally:
        workbook.close()

    header_idx = next(i for i, r in enumerate(rows) if _clean(r[0]) == "Ethnicity")
    header = [_clean(c) for c in rows[header_idx]]
    year_columns = {year: header.index(str(year)) for year in CHILD_SENTENCING_YEARS}

    counts: dict[int, dict[str, dict[str, int]]] = {y: {} for y in CHILD_SENTENCING_YEARS}
    for row in rows[header_idx + 1:]:
        ethnicity = _clean(row[0])
        if ethnicity not in ALL_ETHNICITIES:
            continue
        sentence_type = _clean(row[1])
        for year, column in year_columns.items():
            bucket = counts[year].setdefault(ethnicity, {})
            if sentence_type == "Immediate Custody":
                bucket["events"] = int(row[column])
            elif sentence_type == "Total sentenced":
                bucket["total"] = int(row[column])
    return counts


def read_child_remand_counts() -> dict[str, dict[str, int]]:
    """Derive child remand counts from data/processed/remand_outcomes.json.

    Returns {ethnicity: {"events": custodial remand (ydp), "total": all
    remand decisions}} for the year ending March 2025. The rate is the
    proportion of children subject to a remand decision who are remanded to
    youth detention accommodation.
    """
    data = json.loads(REMAND_OUTCOMES.read_text(encoding="utf-8"))
    counts = {e: {"events": 0, "total": 0} for e in ALL_ETHNICITIES}
    for record in data["records"]:
        if record["breakdown"] != "ethnicity" or record["year"] != CHILD_REMAND_YEAR:
            continue
        ethnicity = record["ethnicity"]
        if ethnicity not in counts:
            continue
        counts[ethnicity]["total"] += record["count"]
        if record["remand_type"] == "ydp":
            counts[ethnicity]["events"] = record["count"]
    return counts


# --------------------------------------------------------------------------
# Row assembly
# --------------------------------------------------------------------------
def _adult_block(decision_point: str, source_table: str, rri_data: dict) -> list[dict]:
    """Five rows adopted verbatim from a MoJ RRI table."""
    rows = []
    for ethnicity in ALL_ETHNICITIES:
        is_baseline = ethnicity == BASELINE
        rows.append(
            _row(
                geo_id="ew",
                year=ADULT_YEAR,
                period_basis="calendar_year_2024",
                pooled=False,
                decision_point=decision_point,
                ethnicity=ethnicity,
                provenance="moj_published",
                rri=1.0 if is_baseline else rri_data[ethnicity]["rri"],
                ci_lower=None,
                ci_upper=None,
                ci_method="not_published",
                significance_flag=None if is_baseline else rri_data[ethnicity]["significance_flag"],
                events=None,
                total=None,
                source_table=source_table,
                **ADULT_SOURCE,
            )
        )
    return rows


def _child_block(
    decision_point: str,
    source_table: str,
    counts: dict[str, dict[str, int]],
    year: int,
    period_basis: str,
    pooled: bool,
) -> list[dict]:
    """Five rows computed by PRISM-R from youth counts, with Wald CIs."""
    baseline = counts[BASELINE]
    rows = []
    for ethnicity in ALL_ETHNICITIES:
        if ethnicity == BASELINE:
            rri, ci_lower, ci_upper = 1.0, None, None
        else:
            result = relative_rate_index(
                counts[ethnicity]["events"],
                counts[ethnicity]["total"],
                baseline["events"],
                baseline["total"],
            )
            rri, ci_lower, ci_upper = result.rri, result.ci_lower, result.ci_upper
        rows.append(
            _row(
                geo_id="ew",
                year=year,
                period_basis=period_basis,
                pooled=pooled,
                decision_point=decision_point,
                ethnicity=ethnicity,
                provenance="prism_r_derived",
                rri=rri,
                ci_lower=ci_lower,
                ci_upper=ci_upper,
                ci_method="wald_log_ratio",
                significance_flag=None,
                events=counts[ethnicity]["events"],
                total=counts[ethnicity]["total"],
                source_table=source_table,
                **CHILD_SOURCE,
            )
        )
    return rows


def _pool_counts(by_year: dict[int, dict[str, dict[str, int]]]) -> dict[str, dict[str, int]]:
    """Sum event and total counts across years, per ethnicity."""
    return {
        ethnicity: {
            "events": sum(by_year[y][ethnicity]["events"] for y in by_year),
            "total": sum(by_year[y][ethnicity]["total"] for y in by_year),
        }
        for ethnicity in ALL_ETHNICITIES
    }


def build_rri() -> list[dict]:
    """Build all RRI rows. Returns the record list."""
    rows: list[dict] = []

    # Adult, adopted from MoJ.
    rows += _adult_block("custodial_sentence", "9.01", read_moj_adult_rri(MOJ_CH9, "9_01"))
    rows += _adult_block("remand", "5.17a", read_moj_adult_rri(MOJ_CH5, "5_15"))

    # Child custodial sentencing: single-year rows plus a three-year pooled row.
    by_year = read_child_custodial_counts()
    for year in CHILD_SENTENCING_YEARS:
        rows += _child_block(
            "custodial_sentence", "5.8", by_year[year], year,
            period_basis=f"year_ending_march_{year}", pooled=False,
        )
    rows += _child_block(
        "custodial_sentence", "5.8", _pool_counts(by_year),
        year=CHILD_SENTENCING_YEARS[-1], period_basis=POOLED_PERIOD, pooled=True,
    )

    # Child remand: single year, not pooled (counts are stable).
    rows += _child_block(
        "remand", "6.1", read_child_remand_counts(), CHILD_REMAND_YEAR,
        period_basis=f"year_ending_march_{CHILD_REMAND_YEAR}", pooled=False,
    )

    rows.sort(
        key=lambda r: (
            r["decision_point"],
            r["provenance"],
            0 if r["pooled"] else 1,
            r["year"],
            r["ethnicity"],
        )
    )
    return rows


def write_rri() -> dict:
    rows = build_rri()
    payload = {
        "meta": {
            "dataset": "rri",
            "generated_by": "pipeline/compute_rri.py",
            "methodology": (
                "Relative Rate Index, the event rate for an ethnic group "
                "divided by the event rate for the White baseline group, "
                "following the MoJ methodology recommended in the Lammy "
                "Review (2017)."
            ),
            "confidence_interval": (
                "95% Wald interval on the log of the rate ratio; "
                "SE(ln RRI) = sqrt(1/a + 1/b - 1/A - 1/B); exponentiated. "
                "Altman, Machin, Bryant and Gardner, Statistics with "
                "Confidence, 2nd ed., BMJ Books, 2000. Applied to "
                "prism_r_derived rows only."
            ),
            "pooling": (
                "The child custodial sentencing RRI is presented as a "
                "three-year pooled estimate (period_basis "
                f"{POOLED_PERIOD!r}, pooled true) because single-year "
                "immediate-custody counts for children are small and "
                "unstable. Single-year rows are retained with pooled false. "
                "Child remand is not pooled; its counts are stable."
            ),
            "period_basis": (
                "Adult rows are calendar year 2024, the MoJ basis. Child "
                "rows are years ending March, the YJB basis. The two are "
                "not forced onto a common calendar."
            ),
            "provenance": {
                "moj_published": (
                    "Adopted from MoJ's published tables, cited verbatim, not "
                    "independently reproducible from public data; no "
                    "confidence interval."
                ),
                "prism_r_derived": (
                    "Computed by PRISM-R from open YJB youth data using the "
                    "MoJ-recommended RRI methodology."
                ),
            },
            "schema_note": (
                "One record per decision_point, provenance, period and "
                "ethnicity. White is the baseline, rri 1.0 by definition. "
                "ci_lower and ci_upper are null for moj_published rows and "
                "for White baseline rows. events and total are the rate "
                "numerator and denominator, given for prism_r_derived rows."
            ),
            "counts": {"records": len(rows)},
        },
        "records": rows,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return payload


def main() -> int:
    payload = write_rri()
    print(f"rri.json  {len(payload['records'])} records")
    print()
    for row in payload["records"]:
        ci = (
            f"  CI [{row['ci_lower']:.3f}, {row['ci_upper']:.3f}]"
            if row["ci_lower"] is not None
            else f"  ({row['ci_method']})"
        )
        flag = f"  {row['significance_flag']}" if row["significance_flag"] else ""
        tag = "  POOLED" if row["pooled"] else ""
        print(
            f"  {row['decision_point']:18s} {row['provenance']:16s} "
            f"{row['ethnicity']:7s} {row['period_basis']:28s} "
            f"RRI {row['rri']:.4f}{ci}{flag}{tag}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
