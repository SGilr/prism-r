"""Ingest child income deprivation from the Indices of Multiple Deprivation.

The spec context layer (section 4.5) carries an `imd_score` indicator. PRISM-R
uses a child-focused income deprivation measure, aligned with its youth focus,
rather than the overall index:

  England  Income Deprivation Affecting Children Index (IDACI) average score,
           from the English Indices of Deprivation 2025 (IoD2025, MHCLG,
           published 30 October 2025; income data financial year 2022/23).
           IDACI is the proportion of children aged 0 to 15 in income-deprived
           families. The local authority "average score" is taken from IoD2025
           File 10, lower-tier local authority district summaries.

  Wales    WIMD 2019 income deprivation for children (aged 0 to 15), an
           indicator of the Welsh Index of Multiple Deprivation 2019 (Welsh
           Government; income data financial year 2016/17). Same age band as
           IDACI.

WIMD 2025 has been published as an index, but its income-by-age indicator data
at local authority level was not yet available when PRISM-R ingested it: only
the WIMD 2025 index and domain ranks, and the LSOA-level indicator data, were
out. WIMD 2019 is therefore the most recent obtainable child income figure by
Welsh local authority. This is flagged for re-ingest; see docs/data-sources.md.

England and Wales are carried as parallel scales. They measure the same
concept, child income deprivation, but use different methods, data sources and
reference years, and England's is an index-transformed score while Wales's is
a direct rate. They are not comparable across the border. Every record names
its `jurisdiction`, `measure` and `source_release` so the two scales are
self-labelling. See docs/methods.md.

context_indicators.json is co-written with pipeline/ingest_dfe.py and
pipeline/ingest_home_office.py. This script owns the imd_score records and
preserves the others, so the ingest scripts are order-independent.

IDACI and the WIMD child income measure are proportions, not rates per
population, so the rate-base harmonisation used for exclusions and stop and
search does not apply; the rate fields are null.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
RAW_IMD = REPO_ROOT / "data" / "raw" / "imd"

IOD2025_FILE10 = RAW_IMD / "iod2025_file10_la_lower.xlsx"
WIMD_CHILD_INCOME = RAW_IMD / "wimd2019_income_deprivation_by_age.json"

CONTEXT_OUT = PROCESSED_DIR / "context_indicators.json"

ENGLAND_YEAR = 2025
WALES_YEAR = 2019

# Indicator codes owned by this script; see write_context_indicators.
OWNED_INDICATORS = {"imd_score"}

CONTEXT_SCHEMA_NOTE = (
    "One record per geo_id, year, indicator and breakdown, per spec section "
    "4.5. Exclusion rates carry rate_per_100 (canonical), source_rate and "
    "source_rate_base. stop_search_rate carries rate_per_1000 (canonical) and "
    "rate_per_100 (derived). lac_count and arrest_count carry value, a count. "
    "imd_score carries value as a child income deprivation proportion, with "
    "jurisdiction, measure and source_release; the English and Welsh measures "
    "are parallel scales and are not cross-comparable."
)
CONTEXT_GENERATED_BY = (
    "pipeline/ingest_dfe.py, pipeline/ingest_home_office.py and "
    "pipeline/ingest_imd.py"
)
IMD_COVERAGE_NOTE = (
    "imd_score is a child income deprivation measure, not the overall index: "
    "England uses the IDACI average score (IoD2025, income data 2022/23), "
    "Wales uses the WIMD 2019 income deprivation for children aged 0 to 15 "
    "indicator (income data 2016/17). Both cover children aged 0 to 15 but "
    "use different methods and reference years and are not comparable across "
    "the England-Wales border. England records are at lower-tier local "
    "authority district level; Welsh records are the 22 unitary authorities. "
    "The Welsh figure is WIMD 2019 pending WIMD 2025 local-authority indicator "
    "data; re-ingest when that is published."
)
METHODOLOGY_NOTE = (
    "England carries the Income Deprivation Affecting Children Index (IDACI) "
    "average score from the English Indices of Deprivation 2025, income data "
    "for 2022/23. Wales carries the WIMD 2019 income deprivation for children "
    "(aged 0 to 15) indicator, income data for 2016/17. Both describe income "
    "deprivation among children aged 0 to 15, but use different methods, data "
    "sources and reference years, and England's is an index-transformed score "
    "while Wales's is a direct rate. They are parallel scales and are not "
    "comparable across the England-Wales border. The Welsh figure is WIMD "
    "2019 because the WIMD 2025 income-by-age indicator data at local "
    "authority level was not yet published when PRISM-R ingested it; "
    "re-ingest when it is available. Cross-jurisdiction harmonisation, "
    "including ONS experimental work, is a v2 question."
)

ENGLAND_SOURCE = "MHCLG, English Indices of Deprivation 2025"
ENGLAND_RELEASE = "IoD2025"
ENGLAND_REFERENCE = "income data financial year 2022/23"
ENGLAND_MEASURE = (
    "IDACI average score: the proportion of children aged 0 to 15 in "
    "income-deprived families, averaged over the authority's small areas"
)

WALES_SOURCE = "Welsh Government, Welsh Index of Multiple Deprivation 2019"
WALES_RELEASE = "WIMD 2019"
WALES_REFERENCE = "income data financial year 2016/17"
WALES_MEASURE = (
    "WIMD 2019 income deprivation for children: the percentage of children "
    "aged 0 to 15 living in income-deprived households, carried as a "
    "proportion"
)


def _record(geo_id, year, jurisdiction, value, rank, rank_max, measure,
            source, source_release, reference_period) -> dict:
    """One imd_score context record."""
    return {
        "geo_id": geo_id,
        "year": year,
        "indicator": "imd_score",
        "breakdown": "overall",
        "ethnicity": None,
        "jurisdiction": jurisdiction,
        "value": value,
        "value_type": "proportion",
        "rank": rank,
        "rank_max": rank_max,
        "measure": measure,
        "rate_per_100": None,
        "rate_per_1000": None,
        "source_rate": None,
        "source_rate_base": None,
        "disclosure_status": "released",
        "source": source,
        "source_release": source_release,
        "reference_period": reference_period,
        "methodology_note": METHODOLOGY_NOTE,
    }


def _competition_ranks(pairs: list[tuple[str, float]]) -> dict[str, int]:
    """Rank geo_ids by value, 1 = most deprived (highest). Ties share a rank."""
    return {
        geo_id: 1 + sum(1 for _, other in pairs if other > value)
        for geo_id, value in pairs
    }


# --------------------------------------------------------------------------
# England: IoD2025 File 10, IDACI sheet
# --------------------------------------------------------------------------
def read_england() -> list[dict]:
    """Read the IDACI average score per lower-tier local authority district.

    IoD2025 File 10 sheet "IDACI" columns: LAD code, LAD name, average rank,
    rank of average rank, average score, rank of average score, proportion of
    LSOAs in most deprived 10%, rank of that. The average score, a proportion
    from 0 to 1, is the value; the rank of average score is carried too.
    """
    workbook = openpyxl.load_workbook(IOD2025_FILE10, read_only=True, data_only=True)
    try:
        rows = list(workbook["IDACI"].iter_rows(values_only=True))
    finally:
        workbook.close()

    data = [r for r in rows[1:] if r[0]]
    rank_max = len(data)
    records = []
    for code, _name, _avg_rank, _rank_avg_rank, avg_score, rank_avg_score, *_ in data:
        records.append(
            _record(
                geo_id=code,
                year=ENGLAND_YEAR,
                jurisdiction="England",
                value=round(float(avg_score), 5),
                rank=int(rank_avg_score),
                rank_max=rank_max,
                measure=ENGLAND_MEASURE,
                source=ENGLAND_SOURCE,
                source_release=ENGLAND_RELEASE,
                reference_period=ENGLAND_REFERENCE,
            )
        )
    return records


# --------------------------------------------------------------------------
# Wales: WIMD 2019 income deprivation for children, by local authority
# --------------------------------------------------------------------------
def read_wales() -> list[dict]:
    """Read the WIMD 2019 child income deprivation rate per Welsh authority.

    The StatsWales export at WIMD_CHILD_INCOME holds the income deprivation
    indicator by age for LSOAs and local authorities. The local authority
    (W06) rows for the "0 - 15" age group give the percentage of children
    aged 0 to 15 in income deprivation; it is carried as a proportion. The
    within-Wales rank is computed here, 1 = most deprived.
    """
    if not WIMD_CHILD_INCOME.exists():
        print(
            f"  note: {WIMD_CHILD_INCOME.name} not present; "
            "Welsh imd_score records skipped",
            file=sys.stderr,
        )
        return []
    rows = json.loads(WIMD_CHILD_INCOME.read_text(encoding="utf-8"))
    child_la = [
        row for row in rows
        if row["Area code"].startswith("W06") and row["Age group"] == "0 - 15"
    ]
    pairs = [
        (row["Area code"], float(row["Data values"].strip()) / 100)
        for row in child_la
    ]
    ranks = _competition_ranks(pairs)
    rank_max = len(pairs)
    return [
        _record(
            geo_id=geo_id,
            year=WALES_YEAR,
            jurisdiction="Wales",
            value=round(value, 5),
            rank=ranks[geo_id],
            rank_max=rank_max,
            measure=WALES_MEASURE,
            source=WALES_SOURCE,
            source_release=WALES_RELEASE,
            reference_period=WALES_REFERENCE,
        )
        for geo_id, value in pairs
    ]


# --------------------------------------------------------------------------
# Output: merge into context_indicators.json
# --------------------------------------------------------------------------
def indicator_counts(records: list[dict]) -> dict:
    """Per-indicator record, geography and source-suppression counts."""
    return {
        ind: {
            "records": sum(1 for r in records if r["indicator"] == ind),
            "geographies": len({r["geo_id"] for r in records if r["indicator"] == ind}),
            "source_suppressed": sum(
                1 for r in records
                if r["indicator"] == ind and r["disclosure_status"] == "source_suppressed"
            ),
        }
        for ind in sorted({r["indicator"] for r in records})
    }


def write_context_indicators(records: list[dict]) -> dict:
    """Merge the imd_score records into context_indicators.json.

    Preserves records and coverage notes owned by the other ingest scripts.
    """
    if not CONTEXT_OUT.exists():
        raise FileNotFoundError(
            f"{CONTEXT_OUT} not found; run pipeline/ingest_dfe.py first"
        )
    payload = json.loads(CONTEXT_OUT.read_text(encoding="utf-8"))
    foreign = [r for r in payload["records"] if r["indicator"] not in OWNED_INDICATORS]
    combined = sorted(
        records + foreign,
        key=lambda r: (r["indicator"], r["geo_id"], r["breakdown"], r["ethnicity"] or ""),
    )
    coverage = dict(payload.get("meta", {}).get("coverage_notes", {}))
    coverage["imd"] = IMD_COVERAGE_NOTE

    new_payload = {
        "meta": {
            "dataset": "context_indicators",
            "generated_by": CONTEXT_GENERATED_BY,
            "schema_note": CONTEXT_SCHEMA_NOTE,
            "indicators": indicator_counts(combined),
            "coverage_notes": coverage,
        },
        "records": combined,
    }
    with CONTEXT_OUT.open("w", encoding="utf-8") as handle:
        json.dump(new_payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return new_payload


def main() -> int:
    records = read_england() + read_wales()
    payload = write_context_indicators(records)

    own = [r for r in payload["records"] if r["indicator"] in OWNED_INDICATORS]
    england = [r for r in own if r["jurisdiction"] == "England"]
    wales = [r for r in own if r["jurisdiction"] == "Wales"]
    print(f"context_indicators.json  {len(payload['records'])} records "
          f"({len(own)} imd_score: {len(england)} England, {len(wales)} Wales)")

    for label, subset in (("England", england), ("Wales", wales)):
        if not subset:
            continue
        values = sorted(subset, key=lambda r: r["value"])
        print(f"  {label}: child income deprivation, {len(subset)} authorities, "
              f"value range {values[0]['value']} to {values[-1]['value']}")
        print(f"    least deprived: {values[0]['geo_id']} {values[0]['value']}")
        print(f"    most deprived:  {values[-1]['geo_id']} {values[-1]['value']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
