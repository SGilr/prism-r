"""Build the geography crosswalk: local authority to YOT to police force.

Reads the ONS UK Authority Codes 2024 lookup and the Sprint 1 geographies,
and writes data/processed/geo_crosswalk.json with one record per local
authority district in England and Wales.

The ONS code (E06, E07, E08, E09, W06) is the canonical local authority
identifier. Each local authority is mapped to:

  - its parent youth justice service (YOT), via its upper-tier authority
  - its parent police force, from the ONS police force area column

YOTs operate at upper-tier level. Most upper-tier authorities map one to one
to a YOT of the same name. The exceptions, partnership YOTs covering several
authorities and a few name variants and post-reorganisation cases, are held
in UTLA_TO_YOT below and flagged in the output.

The script is idempotent. It validates that every local authority resolves
to a YOT and a force that exist in geographies.json, and raises otherwise.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import openpyxl

REPO_ROOT = Path(__file__).resolve().parent.parent
ONS_LOOKUP = REPO_ROOT / "data" / "raw" / "geo" / "uk_authority_codes_2024.xlsx"
GEOGRAPHIES = REPO_ROOT / "data" / "processed" / "geographies.json"
OUTPUT = REPO_ROOT / "data" / "processed" / "geo_crosswalk.json"

SOURCE_LABEL = "ONS lookup table for UK Authority Codes 2024 (FOI-2024-2008)"
SOURCE_PUBLICATION_DATE = "2024-05-20"

# ONS police force area name -> YJB force name (YJB folds City of London into
# London, giving 42 forces; ONS lists 43).
PFA_TO_FORCE = {
    "Metropolitan Police": "London",
    "London, City of": "London",
    "Devon & Cornwall": "Devon and Cornwall",
    "Dyfed-Powys": "Dyfed Powys",
}

# Upper-tier authority name -> (YOT name, assignment basis).
# Authorities not listed here map to a YOT of the same name (basis name-match).
UTLA_TO_YOT = {
    # Name variants: same body, cosmetically different name.
    "Bristol, City of": ("Bristol", "name-variant"),
    "County Durham": ("Durham", "name-variant"),
    "Kingston upon Hull, City of": ("Kingston-upon-Hull", "name-variant"),
    "Leicester": ("Leicester City", "name-variant"),
    # Partnership YOTs: one service covering several authorities.
    "Bedford": ("Bedfordshire", "partnership"),
    "Central Bedfordshire": ("Bedfordshire", "partnership"),
    "Bury": ("Bury and Rochdale", "partnership"),
    "Rochdale": ("Bury and Rochdale", "partnership"),
    "Cheshire East": ("Cheshire East, Cheshire West, Halton and Warrington", "partnership"),
    "Cheshire West and Chester": ("Cheshire East, Cheshire West, Halton and Warrington", "partnership"),
    "Halton": ("Cheshire East, Cheshire West, Halton and Warrington", "partnership"),
    "Warrington": ("Cheshire East, Cheshire West, Halton and Warrington", "partnership"),
    "Kingston upon Thames": ("Kingston and Richmond", "partnership"),
    "Richmond upon Thames": ("Kingston and Richmond", "partnership"),
    "City of London": ("Tower Hamlets and City of London", "partnership"),
    "Tower Hamlets": ("Tower Hamlets and City of London", "partnership"),
    "Middlesbrough": ("South Tees", "partnership"),
    "Redcar and Cleveland": ("South Tees", "partnership"),
    "Blaenau Gwent": ("Blaenau Gwent and Caerphilly", "partnership"),
    "Caerphilly": ("Blaenau Gwent and Caerphilly", "partnership"),
    "Conwy": ("Conwy and Denbighshire", "partnership"),
    "Denbighshire": ("Conwy and Denbighshire", "partnership"),
    "Merthyr Tydfil": ("Cwm Taf", "partnership"),
    "Rhondda Cynon Taf": ("Cwm Taf", "partnership"),
    "Monmouthshire": ("Monmouthshire and Torfaen", "partnership"),
    "Torfaen": ("Monmouthshire and Torfaen", "partnership"),
    # Derived: assignment not evident from the name, flagged for confirmation.
    "Bournemouth, Christchurch and Poole": ("Dorset Combined YOS", "derived"),
    "Dorset": ("Dorset Combined YOS", "derived"),
    "Herefordshire, County of": ("West Mercia", "derived"),
    "Shropshire": ("West Mercia", "derived"),
    "Telford and Wrekin": ("West Mercia", "derived"),
    "Worcestershire": ("West Mercia", "derived"),
    "North Northamptonshire": ("Northamptonshire", "derived"),
    "West Northamptonshire": ("Northamptonshire", "derived"),
    "Isles of Scilly": ("Cornwall", "derived"),
    "Rutland": ("Leicestershire", "derived"),
    "Gwynedd": ("Gwynedd and Ynys Môn", "derived"),
    "Isle of Anglesey": ("Gwynedd and Ynys Môn", "derived"),
}

# Notes attached to derived assignments in the output.
FLAG_NOTES = {
    "Dorset Combined YOS": (
        "Dorset Combined YOS covers both Dorset unitary authorities, Bournemouth, "
        "Christchurch and Poole, and Dorset."
    ),
    "West Mercia": (
        "Confirmed against the gov.uk youth justice services directory: a single "
        "West Mercia service covers Herefordshire, Shropshire, Telford and Wrekin "
        "and Worcestershire."
    ),
    "Northamptonshire": (
        "Confirmed against the gov.uk youth justice services directory: a single "
        "Northamptonshire service covers both successor unitaries of the 2021 "
        "reorganisation."
    ),
    "Cornwall": (
        "Isles of Scilly has no dedicated YOT and is taken to be served by "
        "Cornwall. Not directly confirmed; the child population is immaterial."
    ),
    "Leicestershire": (
        "Confirmed against the gov.uk youth justice services directory: Rutland "
        "has no distinct service and is served by Leicestershire."
    ),
    "Gwynedd and Ynys Môn": (
        "The YJB local-level tables spell this Welsh service two ways; "
        "geographies.json now holds a single record under the gov.uk directory "
        "spelling. See docs/methods.md."
    ),
}


def _load_geographies() -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    """Return (yot name->geo_id, force name->geo_id, yot geo_id->parent_force)."""
    geo = json.loads(GEOGRAPHIES.read_text(encoding="utf-8"))
    yot_ids, force_ids, yot_force = {}, {}, {}
    for record in geo["records"]:
        if record["geo_type"] == "yot":
            yot_ids[record["geo_name"]] = record["geo_id"]
            yot_force[record["geo_id"]] = record["parent_force"]
        elif record["geo_type"] == "police_force":
            force_ids[record["geo_name"]] = record["geo_id"]
    return yot_ids, force_ids, yot_force


def _read_lads() -> list[dict]:
    """Read England and Wales local authority districts from the ONS lookup.

    The lookup holds one row per community safety partnership, so a district
    spanning several partnerships appears more than once. Districts are
    deduplicated by code; upper-tier authority and police force area are
    constant across a district's rows.
    """
    workbook = openpyxl.load_workbook(ONS_LOOKUP, read_only=True, data_only=True)
    rows = list(workbook.worksheets[0].iter_rows(values_only=True))
    workbook.close()
    idx = {name: i for i, name in enumerate(rows[0])}
    lads: dict[str, dict] = {}
    for row in rows[1:]:
        code = row[idx["LAD24CD"]]
        if not code or code[0] not in ("E", "W"):
            continue
        record = {
            "la_code": code,
            "la_name": row[idx["LAD24NM"]],
            "la_type": code[:3],
            "utla_code": row[idx["UTLA24CD"]],
            "utla_name": row[idx["UTLA24NM"]],
            "ons_pfa_name": row[idx["PFA24NM"]],
        }
        if code in lads and lads[code] != record:
            raise ValueError(f"local authority {code} has inconsistent rows in the ONS lookup")
        lads[code] = record
    return list(lads.values())


def build_crosswalk() -> dict:
    yot_ids, force_ids, yot_force = _load_geographies()
    lads = _read_lads()

    records: list[dict] = []
    issues: list[str] = []

    for lad in lads:
        utla = lad["utla_name"]
        if utla in UTLA_TO_YOT:
            yot_name, basis = UTLA_TO_YOT[utla]
        else:
            yot_name, basis = utla, "name-match"

        if yot_name not in yot_ids:
            issues.append(f"{lad['la_code']} {lad['la_name']}: YOT {yot_name!r} not in geographies.json")
            continue
        yot_id = yot_ids[yot_name]

        force_name = PFA_TO_FORCE.get(lad["ons_pfa_name"], lad["ons_pfa_name"])
        if force_name not in force_ids:
            issues.append(f"{lad['la_code']} {lad['la_name']}: force {force_name!r} not in geographies.json")
            continue
        force_id = force_ids[force_name]

        # Integrity check: does the ONS force agree with the YOT's force?
        yot_parent_force = yot_force.get(yot_id)
        force_consistent = yot_parent_force is None or yot_parent_force == force_id

        flagged = basis == "derived" or not force_consistent
        flag_note = FLAG_NOTES.get(yot_name, "")
        if not force_consistent:
            flag_note = (flag_note + " " if flag_note else "") + (
                f"ONS force {force_id} differs from the YOT force {yot_parent_force} recorded in Sprint 1."
            )

        records.append(
            {
                "la_code": lad["la_code"],
                "la_name": lad["la_name"],
                "la_type": lad["la_type"],
                "utla_code": lad["utla_code"],
                "utla_name": utla,
                "parent_yot": yot_id,
                "parent_yot_name": yot_name,
                "parent_force": force_id,
                "parent_force_name": force_name,
                "ons_pfa_name": lad["ons_pfa_name"],
                "assignment_basis": basis,
                "flagged": flagged,
                "flag_note": flag_note,
            }
        )

    if issues:
        raise ValueError("crosswalk build failed:\n  " + "\n  ".join(issues))

    records.sort(key=lambda r: r["la_code"])
    return {"records": records, "yot_force": yot_force}


def write_crosswalk() -> dict:
    built = build_crosswalk()
    records = built["records"]

    basis_counts: dict[str, int] = {}
    for record in records:
        basis_counts[record["assignment_basis"]] = basis_counts.get(record["assignment_basis"], 0) + 1

    payload = {
        "meta": {
            "dataset": "geo_crosswalk",
            "source": SOURCE_LABEL,
            "source_publication_date": SOURCE_PUBLICATION_DATE,
            "source_files": ["uk_authority_codes_2024.xlsx"],
            "generated_by": "pipeline/build_crosswalk.py",
            "schema_note": (
                "One record per local authority district in England and Wales. "
                "la_code is the canonical ONS identifier. parent_yot and "
                "parent_force reference geo_ids in geographies.json. "
                "assignment_basis is name-match, name-variant, partnership or "
                "derived; derived assignments are flagged for review."
            ),
            "counts": {
                "local_authorities": len(records),
                "distinct_yots": len({r["parent_yot"] for r in records}),
                "distinct_forces": len({r["parent_force"] for r in records}),
                "by_assignment_basis": basis_counts,
                "flagged": sum(1 for r in records if r["flagged"]),
            },
        },
        "records": records,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
    return payload


def main() -> int:
    payload = write_crosswalk()
    counts = payload["meta"]["counts"]
    print(f"geo_crosswalk.json  {counts['local_authorities']} local authorities")
    print(f"  distinct YOTs:   {counts['distinct_yots']}")
    print(f"  distinct forces: {counts['distinct_forces']}")
    print(f"  assignment basis: {counts['by_assignment_basis']}")
    print(f"  flagged for review: {counts['flagged']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
