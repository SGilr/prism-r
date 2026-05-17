"""Compute Relative Rate Index (RRI) values for PRISM-R.

The Relative Rate Index compares the rate at which an ethnic group
experiences an outcome with the rate for the White baseline group. It was
recommended in the Lammy Review (2017) and is used by the Ministry of
Justice in Statistics on Ethnicity and the Criminal Justice System.

    RRI = (event rate for the group) / (event rate for the White group)

A value of 1 is parity, above 1 means the group is more likely to
experience the outcome, below 1 less likely.

Six RRI series are produced:

  stop_search         child  prism_r_derived  Home Office, child population
  arrest              child  prism_r_derived  Home Office, child population
  custodial_sentence  adult  moj_published    adopted from MoJ Table 9.01
  custodial_sentence  child  prism_r_derived  computed from YJB Table 5.8
  remand              adult  moj_published    adopted from MoJ Table 5.17a
  remand              child  prism_r_derived  computed from YJB remand data

Together with charge, which is not available from open data, these trace the
spec's road-to-remand cascade: stop and search, arrest, charge, remand,
custodial sentence. The cascade panel therefore shows four of the five
stages.

The adult RRIs are adopted verbatim from MoJ's published tables. MoJ does
not publish the underlying counts, the source Court Proceedings Database is
not public, so they cannot be reproduced from public data and carry no
confidence interval. MoJ's p-value-based significance flag is retained.

The stop and search and arrest RRIs are computed by PRISM-R from Home Office
open data: the event rate is searches, or arrests, of children aged 10 to 17
in the year ending March 2025 over the Census 2021 child population for the
ethnic group. These national counts are summed from the by-ethnicity records
in context_indicators.json, written by pipeline/ingest_home_office.py.

The child RRIs are computed by PRISM-R from open data. No child-specific RRI
exists in published official statistics. Confidence intervals use the Wald
interval on the log of the rate ratio (Altman, Machin, Bryant and Gardner,
Statistics with Confidence, 2nd ed., BMJ Books, 2000):

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
CONTEXT_INDICATORS = PROCESSED_DIR / "context_indicators.json"
POPULATIONS = PROCESSED_DIR / "populations.json"
OUTPUT = PROCESSED_DIR / "rri.json"

# 95% interval. The standard 1.96 multiplier, per the cited method.
Z_95 = 1.96

BASELINE = "White"
GROUPS = ["Asian", "Black", "Mixed", "Other"]
ALL_ETHNICITIES = [BASELINE, *GROUPS]

ADULT_YEAR = 2024
CHILD_REMAND_YEAR = 2025  # year ending March 2025
CHILD_SENTENCING_YEARS = [2023, 2024, 2025]  # years ending March; pooled
HOME_OFFICE_YEAR = 2025  # year ending March 2025
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
HOME_OFFICE_SOURCE = {
    "source_publication": (
        "Police powers and procedures: stop and search, arrests and mental "
        "health detentions, England and Wales, year ending 31 March 2025"
    ),
    "publication_date": "2025-11-06",
    "url": "https://www.gov.uk/government/statistics/stop-and-search-arrests-and-mental-health-detentions-march-2025",
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
# Home Office stop and search and arrest counts, with the Census denominator
# --------------------------------------------------------------------------
def read_child_population() -> dict[str, int]:
    """National child population aged 10 to 17 by ethnicity, from the Census.

    Sums populations.json across local authority, age band and sex. The two
    ethnicity-unavailable LAs carry no population and contribute nothing.
    """
    data = json.loads(POPULATIONS.read_text(encoding="utf-8"))
    population = {ethnicity: 0 for ethnicity in ALL_ETHNICITIES}
    for record in data["records"]:
        if record["population"] is None or record["ethnicity"] not in population:
            continue
        population[record["ethnicity"]] += record["population"]
    return population


def read_home_office_counts(indicator: str) -> dict[str, dict[str, int]]:
    """National event counts and the child-population denominator.

    The events are summed from the by-ethnicity records of context_indicators.json
    (written by pipeline/ingest_home_office.py); the denominator is the Census
    child population. Returns {ethnicity: {"events": ..., "total": ...}}.
    """
    data = json.loads(CONTEXT_INDICATORS.read_text(encoding="utf-8"))
    events = {ethnicity: 0 for ethnicity in ALL_ETHNICITIES}
    for record in data["records"]:
        if record["indicator"] != indicator or record["breakdown"] != "by_ethnicity":
            continue
        if record["ethnicity"] in events:
            events[record["ethnicity"]] += record["value"]
    population = read_child_population()
    return {
        ethnicity: {"events": events[ethnicity], "total": population[ethnicity]}
        for ethnicity in ALL_ETHNICITIES
    }


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
    source: dict = CHILD_SOURCE,
) -> list[dict]:
    """Five rows computed by PRISM-R from child counts, with Wald CIs.

    For custodial sentencing and remand the rate is events over a count of
    children; for stop and search and arrests it is events over the Census
    child population. events and total are the rate numerator and denominator
    in either case.
    """
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
                **source,
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

    # Road-to-remand cascade, upstream stages: stop and search and arrests,
    # computed by PRISM-R from Home Office counts over the Census denominator.
    rows += _child_block(
        "stop_search", "stop and search open data tables",
        read_home_office_counts("stop_search_rate"), HOME_OFFICE_YEAR,
        period_basis=f"year_ending_march_{HOME_OFFICE_YEAR}", pooled=False,
        source=HOME_OFFICE_SOURCE,
    )
    rows += _child_block(
        "arrest", "arrests open data tables",
        read_home_office_counts("arrest_count"), HOME_OFFICE_YEAR,
        period_basis=f"year_ending_march_{HOME_OFFICE_YEAR}", pooled=False,
        source=HOME_OFFICE_SOURCE,
    )

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
                "rows are years ending March: youth justice on the YJB basis, "
                "stop and search and arrests on the Home Office basis. The "
                "calendars are not forced onto each other."
            ),
            "cascade": (
                "The decision points trace the road-to-remand cascade of "
                "spec section 6.2: stop_search, arrest, charge, remand, "
                "custodial_sentence. charge is not available from open data, "
                "so four of the five stages are populated. stop_search and "
                "arrest rates use the Census child population as the "
                "denominator; remand and custodial sentencing use a count of "
                "children as the denominator."
            ),
            "provenance": {
                "moj_published": (
                    "Adopted from MoJ's published tables, cited verbatim, not "
                    "independently reproducible from public data; no "
                    "confidence interval."
                ),
                "prism_r_derived": (
                    "Computed by PRISM-R using the MoJ-recommended RRI "
                    "methodology: youth justice rows from open YJB data, stop "
                    "and search and arrest rows from Home Office counts over "
                    "the Census child population."
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
