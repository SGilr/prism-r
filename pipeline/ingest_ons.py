"""Ingest ONS Census 2021 child population denominators.

Source: Census 2021, dataset RM032 (Ethnic group by sex by age), pulled
through the ONS filter service. See data/raw/ons-census-2021/filter_manifest.json
for the exact filter requests and download URLs.

Census 2021 disclosure control will not release a fine ethnicity-by-age
cross-tabulation for the smallest authorities, so LA-level coverage comes
in three tiers (see docs/methods.md, "Disclosure-aware coverage of
LA-level population data"):

  full           314 LAs   ethnicity x age band x sex
  sex_aggregated   2 LAs    ethnicity x age band, sex suppressed by ONS
  unavailable      2 LAs    no ethnicity-disaggregated denominator at all

Output: data/processed/populations.json, per spec section 4.2. The ONS
ethnic-group rollup is documented in data/processed/ethnicity_crosswalk.json,
which is written by pipeline/ingest_dfe.py.

The script also reconciles the national total against a separate
national-level filter pull, which has no disclosure restriction.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = REPO_ROOT / "data" / "raw" / "ons-census-2021"
PROCESSED_DIR = REPO_ROOT / "data" / "processed"

CSV_FULL = RAW_DIR / "census2021_5cat_age_sex.csv"
CSV_SEX_AGG = RAW_DIR / "census2021_5cat_sex_aggregated.csv"
CSV_NATIONAL = RAW_DIR / "census2021_5cat_national.csv"
CSV_AGEONLY = RAW_DIR / "census2021_ageonly_2la.csv"

POPULATIONS_OUT = PROCESSED_DIR / "populations.json"

CENSUS_YEAR = 2021
CENSUS_BASIS = "2021"

# ONS 6-category ethnic group labels mapped to the YJB 5 groups.
ETHNICITY_MAP = {
    "Asian, Asian British or Asian Welsh": "Asian",
    "Black, Black British, Black Welsh, Caribbean or African": "Black",
    "Mixed or Multiple ethnic groups": "Mixed",
    "White": "White",
    "Other ethnic group": "Other",
}
SEX_MAP = {"Female": "female", "Male": "male"}
AGE_BANDS = {10: "10-11", 11: "10-11", 12: "12-14", 13: "12-14", 14: "12-14",
             15: "15-17", 16: "15-17", 17: "15-17"}

# LAs that ONS would not release at any ethnicity-by-age granularity.
UNAVAILABLE_LAS = {
    "E06000053": "Isles of Scilly",
    "E09000001": "City of London",
}

YJB_GROUPS = ["Asian", "Black", "Mixed", "Other", "White"]


# --------------------------------------------------------------------------
# Reading the Census filter CSVs
# --------------------------------------------------------------------------
def _read_5cat(path: Path, with_sex: bool) -> pd.DataFrame:
    """Read a 5-category Census filter CSV, banded and mapped to YJB groups.

    Returns columns: geo_id, ethnicity, age_band, sex (or None), population.
    """
    frame = pd.read_csv(path)
    code_col = next(c for c in frame.columns if c.endswith("Code") and "local authorities" in c)
    eth_col = "Ethnic group (6 categories)"
    age_col = "Age (101 categories) Code"

    frame = frame[frame[eth_col].isin(ETHNICITY_MAP)].copy()
    frame["geo_id"] = frame[code_col]
    frame["ethnicity"] = frame[eth_col].map(ETHNICITY_MAP)
    frame["age_band"] = frame[age_col].astype(int).map(AGE_BANDS)
    if with_sex:
        frame["sex"] = frame["Sex (2 categories)"].map(SEX_MAP)
        group_keys = ["geo_id", "ethnicity", "age_band", "sex"]
    else:
        frame["sex"] = None
        group_keys = ["geo_id", "ethnicity", "age_band"]

    grouped = frame.groupby(group_keys, dropna=False)["Observation"].sum().reset_index()
    grouped = grouped.rename(columns={"Observation": "population"})
    if not with_sex:
        grouped["sex"] = None
    return grouped


# --------------------------------------------------------------------------
# Build populations.json
# --------------------------------------------------------------------------
def build_populations() -> list[dict]:
    """Build the population denominator records across the three tiers."""
    records: list[dict] = []

    full = _read_5cat(CSV_FULL, with_sex=True)
    for row in full.itertuples(index=False):
        records.append(
            _population_row(
                row.geo_id, row.ethnicity, row.age_band, row.sex,
                int(row.population), "full", None,
            )
        )

    sex_agg = _read_5cat(CSV_SEX_AGG, with_sex=False)
    for row in sex_agg.itertuples(index=False):
        records.append(
            _population_row(
                row.geo_id, row.ethnicity, row.age_band, None,
                int(row.population), "sex_aggregated",
                "sex dimension suppressed by ONS disclosure control",
            )
        )

    for geo_id in sorted(UNAVAILABLE_LAS):
        records.append(
            _population_row(
                geo_id, None, None, None, None, "unavailable",
                "ONS Census 2021 disclosure control released no "
                "ethnicity-by-age cross-tabulation for this authority at any "
                "granularity attempted; no modelled value is substituted",
            )
        )

    records.sort(
        key=lambda r: (r["geo_id"], r["ethnicity"] or "", r["age_band"] or "", r["sex"] or "")
    )
    return records


def _population_row(geo_id, ethnicity, age_band, sex, population, status, note) -> dict:
    return {
        "geo_id": geo_id,
        "year": CENSUS_YEAR,
        "ethnicity": ethnicity,
        "age_band": age_band,
        "sex": sex,
        "population": population,
        "census_basis": CENSUS_BASIS,
        "disclosure_status": status,
        "note": note,
    }


# --------------------------------------------------------------------------
# Reconciliation
# --------------------------------------------------------------------------
def reconcile(records: list[dict]) -> dict:
    """Reconcile the LA-level total against the national-level pull."""
    national = pd.read_csv(CSV_NATIONAL)
    national = national[national["Ethnic group (6 categories)"].isin(ETHNICITY_MAP)]
    national_by_eth = {
        ETHNICITY_MAP[k]: int(v)
        for k, v in national.groupby("Ethnic group (6 categories)")["Observation"].sum().items()
    }
    national_total = sum(national_by_eth.values())

    covered_by_eth: dict[str, int] = {g: 0 for g in YJB_GROUPS}
    for record in records:
        if record["population"] is not None:
            covered_by_eth[record["ethnicity"]] += record["population"]
    covered_total = sum(covered_by_eth.values())

    age_only = pd.read_csv(CSV_AGEONLY)
    unavailable_by_la = {
        code: int(age_only[age_only.iloc[:, 0] == code]["Observation"].sum())
        for code in UNAVAILABLE_LAS
    }
    unavailable_total = sum(unavailable_by_la.values())

    implied_gap = national_total - covered_total
    return {
        "national_by_ethnicity": national_by_eth,
        "national_total": national_total,
        "covered_by_ethnicity": covered_by_eth,
        "covered_total": covered_total,
        "implied_gap": implied_gap,
        "unavailable_by_la": unavailable_by_la,
        "unavailable_total": unavailable_total,
        "gap_minus_unavailable": implied_gap - unavailable_total,
        "consistent": abs(implied_gap - unavailable_total) <= 20,
    }


def summary_statistics(records: list[dict]) -> dict:
    """Mean and range of LA 10-17 population by ethnicity, across LAs."""
    by_la_eth: dict[tuple[str, str], int] = {}
    for record in records:
        if record["population"] is None:
            continue
        key = (record["geo_id"], record["ethnicity"])
        by_la_eth[key] = by_la_eth.get(key, 0) + record["population"]
    stats = {}
    for group in YJB_GROUPS:
        values = [v for (g, e), v in by_la_eth.items() if e == group]
        stats[group] = {
            "las": len(values),
            "mean": round(sum(values) / len(values), 1),
            "min": min(values),
            "max": max(values),
        }
    return stats


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def write_populations(records: list[dict], reconciliation: dict) -> None:
    counts = {
        status: len({r["geo_id"] for r in records if r["disclosure_status"] == status})
        for status in ("full", "sex_aggregated", "unavailable")
    }
    _write_json(
        POPULATIONS_OUT,
        {
            "meta": {
                "dataset": "populations",
                "generated_by": "pipeline/ingest_ons.py",
                "source": "ONS Census 2021, dataset RM032, via the ONS filter service",
                "source_publication_date": "2023-03-28",
                "reference_date": "Census day, 21 March 2021",
                "geographic_vintage": "2023 lower tier local authorities (ltla23)",
                "schema_note": (
                    "One record per geo_id, year, ethnicity, age_band and sex, "
                    "per spec section 4.2, plus disclosure_status. sex is null "
                    "for sex_aggregated LAs. unavailable LAs carry a single "
                    "stub record with null population."
                ),
                "disclosure_status": {
                    "full": "ethnicity x age band x sex",
                    "sex_aggregated": "ethnicity x age band; sex suppressed by ONS",
                    "unavailable": "no ethnicity-disaggregated denominator released",
                },
                "la_counts": counts,
                "national_reconciliation": reconciliation,
            },
            "records": records,
        },
    )


def main() -> int:
    records = build_populations()
    reconciliation = reconcile(records)
    write_populations(records, reconciliation)

    counts = {
        status: len({r["geo_id"] for r in records if r["disclosure_status"] == status})
        for status in ("full", "sex_aggregated", "unavailable")
    }
    print(f"populations.json  {len(records)} records")
    print(f"  LAs: full {counts['full']}, sex_aggregated {counts['sex_aggregated']}, "
          f"unavailable {counts['unavailable']}  (total {sum(counts.values())})")
    print()
    print("National reconciliation:")
    print(f"  national pull total (10-17, England and Wales): {reconciliation['national_total']:,}")
    print(f"  sum across {counts['full'] + counts['sex_aggregated']} covered LAs:        "
          f"{reconciliation['covered_total']:,}")
    print(f"  implied gap (national minus covered):           {reconciliation['implied_gap']:,}")
    print(f"  Isles of Scilly + City of London (age-only):    {reconciliation['unavailable_total']:,}")
    print(f"  gap minus the two unavailable LAs:              {reconciliation['gap_minus_unavailable']:,}")
    print(f"  consistent within perturbation tolerance:       {reconciliation['consistent']}")
    print()
    print("By ethnicity (national / covered / difference):")
    for group in YJB_GROUPS:
        nat = reconciliation["national_by_ethnicity"][group]
        cov = reconciliation["covered_by_ethnicity"][group]
        print(f"  {group:7s} {nat:>10,} / {cov:>10,} / {nat - cov:>6,}")
    print()
    print("LA 10-17 population by ethnicity (mean, range across covered LAs):")
    for group, stat in summary_statistics(records).items():
        print(f"  {group:7s} mean {stat['mean']:>8,.1f}  range {stat['min']:,} to {stat['max']:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
