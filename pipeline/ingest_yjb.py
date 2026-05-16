"""Ingest Youth Justice Statistics 2024-25 into processed JSON.

Reads the YJB and MoJ Youth Justice Statistics 2024 to 2025 supplementary
tables (chapter 6, use of remand) and the local-level open data tables, and
writes two processed datasets:

    data/processed/remand_outcomes.json   national remand episodes
    data/processed/geographies.json       regions, police forces, youth
                                          justice services and the England
                                          and Wales national unit

The script is idempotent: given the same raw inputs it writes byte-identical
output. It validates its own remand figures against the published national
totals and exits non-zero if any check fails.

First version. Scope notes and deviations from the v1 specification:

1. remand_outcomes covers England and Wales only. The YJB local-level open
   data tables hold children, proven offences, and cautions or sentences,
   not remand, so sub-national remand cannot be built from these sources.
2. The four remand_type values form a partition of total remand episodes.
   YJB groups Bail Supervision and Support, ISS Bail, and Remand to Local
   Authority Accommodation under "community remand with intervention". To
   match the spec enum, rlaa is carved out as its own value and
   community_remand holds Bail Supervision and Support plus ISS Bail.
3. age_band is emitted as the YJB bands "10-14" and "15-17". YJB does not
   publish the finer "10-11" and "12-14" split for remand.
4. ethnicity includes "Unknown" and sex includes "unknown"; both appear in
   the source.
5. remand_outcomes records carry a breakdown field (total, ethnicity, sex,
   age) because Table 6.1 publishes marginal breakdowns, not a full cross
   tabulation. Records must not be summed across breakdown values.
6. geographies use a geo_type of "nation" for the England and Wales unit,
   in addition to the spec enum region, yot, police_force, la.
7. geographies are built from the 2024-25 financial year. ons_code, the
   centroids, and boundary_ref are null pending ingest_ons.py.
8. nation is derived from region, because the Offence table England_Wales
   column contains stray "London" values.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import openpyxl
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw" / "yjb-2024-25"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

SOURCE_LABEL = "YJB and MoJ Youth Justice Statistics 2024 to 2025"
SOURCE_PUBLICATION_DATE = "2026-01-29"

# Financial year ending March 2025.
CURRENT_FY = "2024-25"
CURRENT_YEAR = 2025

REMAND_CHAPTER = RAW_DIR / "Ch 6 - Use of remand for children.xlsx"
LOCAL_LEVEL_FILES = [
    RAW_DIR / "Children_Table.ods",
    RAW_DIR / "Offence_Table v2.ods",
    RAW_DIR / "Outcome_Table.ods",
]

# YJB remand-type leaf rows mapped to the spec remand_type enum. See note 2.
LEAF_REMAND_TYPE = {
    "Unconditional Bail": "bail",
    "Conditional Bail": "bail",
    "Bail Supervision and Support": "community_remand",
    "ISS Bail": "community_remand",
    "Remand to Local Authority Accommodation": "rlaa",
    "Remand to Youth Detention Accommodation": "ydp",
}
REMAND_TYPES = ["bail", "community_remand", "rlaa", "ydp"]

# Table 6.1 marginal columns mapped to spec enum values.
ETHNICITY_COLUMNS = {
    "Asian": "Asian",
    "Black": "Black",
    "Mixed": "Mixed",
    "Other": "Other",
    "White": "White",
    "Unknown Ethnicity": "Unknown",
}
SEX_COLUMNS = {"Girls": "female", "Boys": "male", "Unknown Sex": "unknown"}
AGE_COLUMNS = {"Aged 10 to 14": "10-14", "Aged 15 to 17": "15-17"}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
def _slug(name: str) -> str:
    """Return a stable, url-safe slug for a geography name."""
    text = name.strip().lower().replace("&", " and ")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


_NOTE_RE = re.compile(r"\[note[^\]]*\]", re.IGNORECASE)


def _clean(value: object) -> str:
    """Normalise a cell value: drop YJB note markers, collapse whitespace."""
    if value is None:
        return ""
    text = _NOTE_RE.sub("", str(value))
    return re.sub(r"\s+", " ", text).strip()


def _write_json(path: Path, payload: dict) -> None:
    """Write JSON deterministically: sorted keys, trailing newline."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


# --------------------------------------------------------------------------
# Geographies
# --------------------------------------------------------------------------
def build_geographies() -> list[dict]:
    """Build the geography table from the local-level open data tables.

    Returns one record per geographic unit: the England and Wales nation,
    the YJB regions, the police force areas, and the youth justice services.
    """
    rows: list[tuple[str, str, str | None]] = []  # (yjs, region, pcc)
    for path in LOCAL_LEVEL_FILES:
        frame = pd.read_excel(path, sheet_name="Data", engine="odf")
        frame.columns = [str(c).strip() for c in frame.columns]
        region_col = next(c for c in frame.columns if c.lower() == "wales or english region")
        frame = frame[frame["Financial_Year"].astype(str) == CURRENT_FY]
        for _, row in frame.iterrows():
            yjs = _clean(row["YJS"])
            region = _clean(row[region_col])
            pcc_raw = row["PCC"]
            pcc = _clean(pcc_raw) if not pd.isna(pcc_raw) else None
            if yjs and region:
                rows.append((yjs, region, pcc or None))

    yjs_region: dict[str, str] = {}
    yjs_force: dict[str, str] = {}
    for yjs, region, pcc in rows:
        if yjs in yjs_region and yjs_region[yjs] != region:
            raise ValueError(f"YJS {yjs!r} maps to more than one region")
        yjs_region[yjs] = region
        if pcc is not None:
            if yjs in yjs_force and yjs_force[yjs] != pcc:
                raise ValueError(f"YJS {yjs!r} maps to more than one police force")
            yjs_force[yjs] = pcc

    regions = sorted(set(yjs_region.values()))
    forces = sorted(set(yjs_force.values()))

    records: list[dict] = []

    records.append(
        _geo_record("ew", "England and Wales", "nation", None, None)
    )
    for region in regions:
        records.append(
            _geo_record(f"rgn-{_slug(region)}", region, "region", None, None)
        )
    for force in forces:
        records.append(
            _geo_record(f"pf-{_slug(force)}", force, "police_force", None, None)
        )
    for yjs in sorted(yjs_region):
        region = yjs_region[yjs]
        force = yjs_force.get(yjs)
        records.append(
            _geo_record(
                f"yot-{_slug(yjs)}",
                yjs,
                "yot",
                parent_region=f"rgn-{_slug(region)}",
                parent_force=f"pf-{_slug(force)}" if force else None,
            )
        )

    records.sort(key=lambda r: (r["geo_type"], r["geo_id"]))
    return records


def _geo_record(
    geo_id: str,
    geo_name: str,
    geo_type: str,
    parent_region: str | None,
    parent_force: str | None,
) -> dict:
    return {
        "geo_id": geo_id,
        "geo_name": geo_name,
        "geo_type": geo_type,
        "parent_region": parent_region,
        "parent_force": parent_force,
        "ons_code": None,
        "centroid_lat": None,
        "centroid_lon": None,
        "boundary_ref": None,
    }


# --------------------------------------------------------------------------
# Remand outcomes
# --------------------------------------------------------------------------
def _sheet_rows(path: Path, sheet: str) -> list[tuple]:
    workbook = openpyxl.load_workbook(path, data_only=True)
    try:
        worksheet = workbook[sheet]
        return list(worksheet.iter_rows(values_only=True))
    finally:
        workbook.close()


def _header_index(rows: list[tuple], marker: str) -> int:
    for index, row in enumerate(rows):
        if any(_clean(cell) == marker for cell in row):
            return index
    raise ValueError(f"header row containing {marker!r} not found")


def _read_table_6_1(rows: list[tuple]) -> dict:
    """Parse Table 6.1: remands for the year ending March 2025.

    Returns the per remand_type marginal breakdowns and the published
    "Total remand episodes" row for validation.
    """
    header_idx = _header_index(rows, "Remand type")
    header = [_clean(c) for c in rows[header_idx]]
    col = {name: i for i, name in enumerate(header) if name}

    counts = {
        rt: {"ethnicity": {}, "sex": {}, "age": {}, "total": 0}
        for rt in REMAND_TYPES
    }
    published_total_row: dict[str, int] = {}

    for row in rows[header_idx + 1:]:
        group = _clean(row[0])
        leaf = _clean(row[1])
        if "proportion" in group.lower():
            break  # proportion section starts here; counts are above it
        if leaf == "Total remand episodes":
            published_total_row = _marginal_cells(row, col)
            continue
        if leaf not in LEAF_REMAND_TYPE:
            continue
        remand_type = LEAF_REMAND_TYPE[leaf]
        cells = _marginal_cells(row, col)
        bucket = counts[remand_type]
        for label, value in ETHNICITY_COLUMNS.items():
            bucket["ethnicity"][value] = bucket["ethnicity"].get(value, 0) + cells[label]
        for label, value in SEX_COLUMNS.items():
            bucket["sex"][value] = bucket["sex"].get(value, 0) + cells[label]
        for label, value in AGE_COLUMNS.items():
            bucket["age"][value] = bucket["age"].get(value, 0) + cells[label]
        bucket["total"] += cells["Total"]

    if not published_total_row:
        raise ValueError("Table 6.1: 'Total remand episodes' row not found")
    return {"counts": counts, "published_total": published_total_row}


def _marginal_cells(row: tuple, col: dict[str, int]) -> dict[str, int]:
    wanted = list(ETHNICITY_COLUMNS) + list(SEX_COLUMNS) + list(AGE_COLUMNS) + ["Total"]
    return {name: int(round(float(row[col[name]]))) for name in wanted}


def _read_table_6_2(rows: list[tuple]) -> dict:
    """Parse Table 6.2: remand counts by type, years ending March 2021 to 2025.

    Returns per year, per remand_type leaf counts and the published total rows.
    """
    header_idx = _header_index(rows, "Remand type")
    header = [_clean(c) for c in rows[header_idx]]
    year_cols = {int(name): i for i, name in enumerate(header) if name.isdigit()}

    counts = {year: {rt: 0 for rt in REMAND_TYPES} for year in year_cols}
    published = {year: {} for year in year_cols}

    for row in rows[header_idx + 1:]:
        leaf = _clean(row[1])
        if leaf in LEAF_REMAND_TYPE:
            remand_type = LEAF_REMAND_TYPE[leaf]
            for year, idx in year_cols.items():
                counts[year][remand_type] += int(round(float(row[idx])))
        elif leaf in ("Total", "Total bail remands", "Total community remands with intervention"):
            for year, idx in year_cols.items():
                published[year][leaf] = int(round(float(row[idx])))

    return {"counts": counts, "published": published, "years": sorted(year_cols)}


def build_remand_outcomes(table_6_1: dict, table_6_2: dict) -> list[dict]:
    """Build remand_outcomes records for England and Wales."""
    records: list[dict] = []

    # Trend, year ending March 2021 to 2025, from Table 6.2.
    for year in table_6_2["years"]:
        for remand_type in REMAND_TYPES:
            records.append(
                _remand_record(
                    year=year,
                    remand_type=remand_type,
                    breakdown="total",
                    count=table_6_2["counts"][year][remand_type],
                )
            )

    # Marginal breakdowns for the year ending March 2025, from Table 6.1.
    for remand_type in REMAND_TYPES:
        bucket = table_6_1["counts"][remand_type]
        for ethnicity, count in bucket["ethnicity"].items():
            records.append(
                _remand_record(CURRENT_YEAR, remand_type, "ethnicity", count, ethnicity=ethnicity)
            )
        for sex, count in bucket["sex"].items():
            records.append(
                _remand_record(CURRENT_YEAR, remand_type, "sex", count, sex=sex)
            )
        for age_band, count in bucket["age"].items():
            records.append(
                _remand_record(CURRENT_YEAR, remand_type, "age", count, age_band=age_band)
            )

    records.sort(
        key=lambda r: (
            r["year"],
            r["remand_type"],
            r["breakdown"],
            r["ethnicity"] or "",
            r["sex"] or "",
            r["age_band"] or "",
        )
    )
    return records


def _remand_record(
    year: int,
    remand_type: str,
    breakdown: str,
    count: int,
    ethnicity: str | None = None,
    sex: str | None = None,
    age_band: str | None = None,
) -> dict:
    return {
        "geo_id": "ew",
        "year": year,
        "remand_type": remand_type,
        "breakdown": breakdown,
        "ethnicity": ethnicity,
        "age_band": age_band,
        "sex": sex,
        "offence_band": None,
        "count": count,
        "suppressed": False,
    }


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
def validate_remand(table_6_1: dict, table_6_2: dict) -> list[tuple[str, bool, str]]:
    """Check the ingested figures against the published national totals.

    Returns a list of (check, passed, detail) tuples.
    """
    checks: list[tuple[str, bool, str]] = []
    counts = table_6_1["counts"]
    published = table_6_1["published_total"]

    def add(name: str, got: int, expected: int) -> None:
        checks.append((name, got == expected, f"got {got}, published {expected}"))

    # Table 6.1: the four remand types partition each published marginal.
    for label in list(ETHNICITY_COLUMNS) + list(SEX_COLUMNS) + list(AGE_COLUMNS):
        if label in ETHNICITY_COLUMNS:
            key, dimension = ETHNICITY_COLUMNS[label], "ethnicity"
        elif label in SEX_COLUMNS:
            key, dimension = SEX_COLUMNS[label], "sex"
        else:
            key, dimension = AGE_COLUMNS[label], "age"
        got = sum(counts[rt][dimension][key] for rt in REMAND_TYPES)
        add(f"6.1 total remand episodes, {label}", got, published[label])

    grand_total = sum(counts[rt]["total"] for rt in REMAND_TYPES)
    add("6.1 total remand episodes", grand_total, published["Total"])

    # Table 6.1: each marginal of a remand type reproduces that type's total.
    for rt in REMAND_TYPES:
        total = counts[rt]["total"]
        for dimension in ("ethnicity", "sex", "age"):
            got = sum(counts[rt][dimension].values())
            checks.append(
                (
                    f"6.1 {rt}, {dimension} marginal sums to type total",
                    got == total,
                    f"{dimension} sum {got}, type total {total}",
                )
            )

    # Table 6.2: yearly totals reproduce the published rows.
    for year in table_6_2["years"]:
        year_counts = table_6_2["counts"][year]
        pub = table_6_2["published"][year]
        add(f"6.2 {year} total", sum(year_counts.values()), pub["Total"])
        add(f"6.2 {year} bail", year_counts["bail"], pub["Total bail remands"])
        add(
            f"6.2 {year} community_remand plus rlaa",
            year_counts["community_remand"] + year_counts["rlaa"],
            pub["Total community remands with intervention"],
        )

    # Consistency: Table 6.1 and Table 6.2 agree for the current year.
    for rt in REMAND_TYPES:
        add(
            f"6.1 vs 6.2 {CURRENT_YEAR} {rt}",
            counts[rt]["total"],
            table_6_2["counts"][CURRENT_YEAR][rt],
        )

    return checks


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------
def ingest() -> dict:
    """Run the full ingest. Returns a summary dict. Raises on validation failure."""
    geographies = build_geographies()

    rows_6_1 = _sheet_rows(REMAND_CHAPTER, "6.1")
    rows_6_2 = _sheet_rows(REMAND_CHAPTER, "6.2")
    table_6_1 = _read_table_6_1(rows_6_1)
    table_6_2 = _read_table_6_2(rows_6_2)

    checks = validate_remand(table_6_1, table_6_2)
    failed = [c for c in checks if not c[1]]

    remand = build_remand_outcomes(table_6_1, table_6_2)

    source_files = sorted(p.name for p in [REMAND_CHAPTER, *LOCAL_LEVEL_FILES])

    _write_json(
        PROCESSED_DIR / "geographies.json",
        {
            "meta": {
                "dataset": "geographies",
                "source": SOURCE_LABEL,
                "source_publication_date": SOURCE_PUBLICATION_DATE,
                "source_files": [p.name for p in LOCAL_LEVEL_FILES],
                "generated_by": "pipeline/ingest_yjb.py",
                "financial_year": CURRENT_FY,
                "schema_note": (
                    "One record per geographic unit. geo_type 'nation' is used "
                    "for England and Wales in addition to the spec enum. "
                    "ons_code, centroids and boundary_ref are null pending "
                    "ingest_ons.py."
                ),
                "counts": {
                    geo_type: sum(1 for g in geographies if g["geo_type"] == geo_type)
                    for geo_type in ("nation", "region", "police_force", "yot")
                },
            },
            "records": geographies,
        },
    )

    _write_json(
        PROCESSED_DIR / "remand_outcomes.json",
        {
            "meta": {
                "dataset": "remand_outcomes",
                "source": SOURCE_LABEL,
                "source_publication_date": SOURCE_PUBLICATION_DATE,
                "source_files": [REMAND_CHAPTER.name],
                "source_tables": ["6.1", "6.2"],
                "generated_by": "pipeline/ingest_yjb.py",
                "geography": "England and Wales only",
                "schema_note": (
                    "One record per geo_id, year, remand_type and breakdown. "
                    "breakdown is total, ethnicity, sex or age. Records must "
                    "not be summed across breakdown values. age_band uses the "
                    "YJB bands 10-14 and 15-17. remand_type community_remand "
                    "is Bail Supervision and Support plus ISS Bail; rlaa is "
                    "Remand to Local Authority Accommodation."
                ),
            },
            "records": remand,
        },
    )

    return {
        "geographies": len(geographies),
        "remand_records": len(remand),
        "checks": checks,
        "failed": failed,
        "source_files": source_files,
    }


def main() -> int:
    summary = ingest()
    print(f"geographies.json      {summary['geographies']} records")
    print(f"remand_outcomes.json  {summary['remand_records']} records")
    print()
    print("Validation against published national totals:")
    for name, passed, detail in summary["checks"]:
        mark = "pass" if passed else "FAIL"
        print(f"  [{mark}] {name}: {detail}")
    print()
    if summary["failed"]:
        print(f"{len(summary['failed'])} check(s) failed.")
        return 1
    print(f"All {len(summary['checks'])} checks passed. Published totals reproduced.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
